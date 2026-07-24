from __future__ import annotations

from datetime import datetime, timedelta, timezone
import httpx
import pytest
from threading import Lock
from urllib.parse import parse_qs, urlparse
from fastapi import HTTPException

from app.core.config import settings
from app.services import etsy


class _FakeHttpxClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str]] = []
        self.request_kwargs: list[dict[str, object]] = []

    def __enter__(self) -> _FakeHttpxClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        self.calls.append((method, path))
        self.request_kwargs.append(kwargs)
        response = self._responses.pop(0)
        response.request = httpx.Request(method, f"https://api.etsy.com/v3{path}")
        return response


def test_sync_product_listing_images_replaces_ordered_gallery_and_removes_extras(monkeypatch) -> None:
    monkeypatch.setattr(etsy, "_refresh_access_token", lambda _token: "access-token")
    monkeypatch.setattr(etsy, "_wait_for_effective_rate_slot", lambda **_kwargs: (0.0, "test"))
    client = _FakeHttpxClient(
        [
            httpx.Response(201, json={"listing_image_id": 101, "rank": 1}),
            httpx.Response(201, json={"listing_image_id": 102, "rank": 2}),
            httpx.Response(
                200,
                json={
                    "results": [
                        {"listing_image_id": 101, "rank": 1},
                        {"listing_image_id": 102, "rank": 2},
                        {"listing_image_id": 103, "rank": 3},
                    ]
                },
            ),
            httpx.Response(204),
        ]
    )
    monkeypatch.setattr(etsy.httpx, "Client", lambda **_kwargs: client)

    uploaded_count = etsy.sync_product_listing_images_to_etsy(
        listing_id="listing-123",
        etsy_shop_id="shop-456",
        refresh_token="refresh-token",
        images=[
            etsy.EtsyListingImageUpload("hero.png", "image/png", b"hero-bytes"),
            etsy.EtsyListingImageUpload("detail.jpg", "image/jpeg", b"detail-bytes"),
        ],
    )

    assert uploaded_count == 2
    assert client.calls == [
        ("POST", "/application/shops/shop-456/listings/listing-123/images"),
        ("POST", "/application/shops/shop-456/listings/listing-123/images"),
        ("GET", "/application/listings/listing-123/images"),
        ("DELETE", "/application/shops/shop-456/listings/listing-123/images/103"),
    ]
    first_upload = client.request_kwargs[0]
    second_upload = client.request_kwargs[1]
    assert first_upload["data"] == {"rank": 1, "overwrite": True}
    assert second_upload["data"] == {"rank": 2, "overwrite": True}
    assert first_upload["files"] == {"image": ("hero.png", b"hero-bytes", "image/png")}
    assert second_upload["files"] == {
        "image": ("detail.jpg", b"detail-bytes", "image/jpeg")
    }


def test_build_etsy_listing_edit_url_targets_the_seller_editor() -> None:
    assert etsy.build_etsy_listing_edit_url("123456789") == (
        "https://www.etsy.com/your/shops/me/listing-editor/edit/123456789"
    )


def test_ledger_history_uses_bounded_parallel_thirty_day_windows(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(settings, "etsy_shared_secret", "etsy-secret")
    monkeypatch.setattr(settings, "etsy_max_requests_per_second", 5)
    monkeypatch.setattr(settings, "etsy_ledger_max_concurrency", 3)
    monkeypatch.setattr(
        etsy,
        "_wait_for_effective_rate_slot",
        lambda **_kwargs: (0.0, "test"),
    )
    calls: list[str] = []
    clients: list[object] = []
    calls_lock = Lock()

    class LedgerClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def request(self, method: str, path: str, **_kwargs: object) -> httpx.Response:
            with calls_lock:
                calls.append(path)
            response = httpx.Response(200, json={"count": 0, "results": []})
            response.request = httpx.Request(
                method,
                f"https://api.etsy.com/v3{path}",
            )
            return response

    def client_factory(**_kwargs: object) -> LedgerClient:
        client = LedgerClient()
        with calls_lock:
            clients.append(client)
        return client

    monkeypatch.setattr(etsy.httpx, "Client", client_factory)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = etsy.fetch_etsy_ledger_entries(
        access_token="access-token",
        shop_id="shop-1",
        min_created=start,
        max_created=start + timedelta(days=95),
    )

    assert result == []
    assert len(clients) == 3
    assert len(calls) == 4
    for path in calls:
        query = parse_qs(urlparse(path).query)
        window_seconds = int(query["max_created"][0]) - int(query["min_created"][0])
        assert window_seconds <= 30 * 24 * 60 * 60


def test_analytics_authorization_upgrade_rejects_a_different_seller(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(settings, "etsy_shared_secret", "etsy-secret")
    monkeypatch.setattr(
        settings,
        "etsy_oauth_redirect_uri",
        "https://velora.test/settings/etsy/callback",
    )
    authorization = etsy.build_etsy_oauth_authorization(
        actor_id="user-1",
        organization_id="org-1",
        expected_seller_user_id="seller-expected",
    )
    monkeypatch.setattr(
        etsy,
        "_request_oauth_token",
        lambda **_kwargs: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        etsy,
        "fetch_etsy_authenticated_user_id",
        lambda **_kwargs: "seller-other",
    )

    with pytest.raises(HTTPException) as exc_info:
        etsy.exchange_etsy_authorization_code(
            code="authorization-code",
            state=authorization["state"],
            actor_id="user-1",
            organization_id="org-1",
        )

    assert exc_info.value.status_code == 409
    assert "different seller account" in exc_info.value.detail


def test_wait_for_etsy_rate_slot_blocks_after_five_requests_in_one_second(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_max_requests_per_second", 5)
    etsy._RATE_LIMIT_BUCKETS.clear()
    elapsed = {"value": 0.0}
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return elapsed["value"]

    def fake_sleep(duration: float) -> None:
        sleeps.append(duration)
        elapsed["value"] += duration

    monkeypatch.setattr(etsy.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(etsy.time, "sleep", fake_sleep)

    for _ in range(6):
        etsy._wait_for_rate_slot(rate_key="etsy-test")

    assert sleeps == [1.0]


def test_fetch_etsy_shops_uses_redis_shared_rate_limiter_when_available(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(settings, "etsy_shared_secret", "etsy-secret")
    waited_calls: list[tuple[str, int, float]] = []

    def fake_wait_for_redis_sliding_window_slot(*, redis_key: str, limit: int, window_seconds: float) -> float:
        waited_calls.append((redis_key, limit, window_seconds))
        return 0.0

    def fail_local_wait(*, rate_key: str) -> float:
        raise AssertionError("Local limiter should not be used when Redis shared limiter is available.")

    monkeypatch.setattr(etsy, "wait_for_redis_sliding_window_slot", fake_wait_for_redis_sliding_window_slot)
    monkeypatch.setattr(etsy, "_wait_for_rate_slot", fail_local_wait)
    monkeypatch.setattr(
        etsy.httpx,
        "Client",
        lambda **kwargs: _FakeHttpxClient(
            [
                httpx.Response(
                    200,
                    json={
                        "shop_id": 445566,
                        "shop_name": "Sunset Paper Co",
                        "url": "https://www.etsy.com/shop/SunsetPaperCo",
                    },
                )
            ]
        ),
    )

    shops = etsy.fetch_etsy_shops(access_token="12345678.access-token", user_id="12345678")

    assert shops == [
        {
            "shop_id": "445566",
            "shop_name": "Sunset Paper Co",
            "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
        }
    ]
    assert waited_calls == [("ratelimit:etsy:etsy-key:global", 5, 1.0)]


def test_fetch_etsy_shops_falls_back_to_local_rate_limiter_when_redis_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(settings, "etsy_shared_secret", "etsy-secret")
    fallback_calls: list[str] = []

    def fail_redis_wait(*, redis_key: str, limit: int, window_seconds: float) -> float:
        raise etsy.RateLimiterUnavailable("redis offline")

    def fake_local_wait(*, rate_key: str) -> float:
        fallback_calls.append(rate_key)
        return 0.0

    monkeypatch.setattr(etsy, "wait_for_redis_sliding_window_slot", fail_redis_wait)
    monkeypatch.setattr(etsy, "_wait_for_rate_slot", fake_local_wait)
    monkeypatch.setattr(
        etsy.httpx,
        "Client",
        lambda **kwargs: _FakeHttpxClient(
            [
                httpx.Response(
                    200,
                    json={
                        "shop_id": 445566,
                        "shop_name": "Sunset Paper Co",
                        "url": "https://www.etsy.com/shop/SunsetPaperCo",
                    },
                )
            ]
        ),
    )

    shops = etsy.fetch_etsy_shops(access_token="12345678.access-token", user_id="12345678")

    assert shops == [
        {
            "shop_id": "445566",
            "shop_name": "Sunset Paper Co",
            "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
        }
    ]
    assert fallback_calls == ["etsy-key"]


def test_fetch_etsy_shops_retries_after_429_retry_after_header(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(settings, "etsy_shared_secret", "etsy-secret")
    monkeypatch.setattr(settings, "etsy_max_retry_attempts", 1)
    etsy._RATE_LIMIT_BUCKETS.clear()
    elapsed = {"value": 0.0}
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return elapsed["value"]

    def fake_sleep(duration: float) -> None:
        sleeps.append(duration)
        elapsed["value"] += duration

    monkeypatch.setattr(etsy.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(etsy.time, "sleep", fake_sleep)
    client = _FakeHttpxClient(
        [
            httpx.Response(429, headers={"retry-after": "2"}, json={"error": "too_many_requests"}),
            httpx.Response(
                200,
                json={
                    "shop_id": 445566,
                    "shop_name": "Sunset Paper Co",
                    "url": "https://www.etsy.com/shop/SunsetPaperCo",
                },
            ),
        ]
    )
    monkeypatch.setattr(etsy.httpx, "Client", lambda **kwargs: client)

    shops = etsy.fetch_etsy_shops(access_token="12345678.access-token", user_id="12345678")

    assert shops == [
        {
            "shop_id": "445566",
            "shop_name": "Sunset Paper Co",
            "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
        }
    ]
    assert sleeps == [2.0]
    assert client.calls == [
        ("GET", "/application/users/12345678/shops"),
        ("GET", "/application/users/12345678/shops"),
    ]


def test_fetch_etsy_shops_accepts_single_shop_object_response(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(settings, "etsy_shared_secret", "etsy-secret")
    monkeypatch.setattr(
        etsy.httpx,
        "Client",
        lambda **kwargs: _FakeHttpxClient(
            [
                httpx.Response(
                    200,
                    json={
                        "shop_id": 445566,
                        "shop_name": "Sunset Paper Co",
                        "url": "https://www.etsy.com/shop/SunsetPaperCo",
                    },
                )
            ]
        ),
    )

    shops = etsy.fetch_etsy_shops(access_token="12345678.access-token", user_id="12345678")

    assert shops == [
        {
            "shop_id": "445566",
            "shop_name": "Sunset Paper Co",
            "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
        }
    ]


def test_fetch_etsy_shops_keeps_results_list_compatibility(monkeypatch) -> None:
    monkeypatch.setattr(settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(settings, "etsy_shared_secret", "etsy-secret")
    monkeypatch.setattr(
        etsy.httpx,
        "Client",
        lambda **kwargs: _FakeHttpxClient(
            [
                httpx.Response(
                    200,
                    json={
                        "count": 1,
                        "results": [
                            {
                                "shop_id": 445566,
                                "shop_name": "Sunset Paper Co",
                                "url": "https://www.etsy.com/shop/SunsetPaperCo",
                            }
                        ],
                    },
                )
            ]
        ),
    )

    shops = etsy.fetch_etsy_shops(access_token="12345678.access-token", user_id="12345678")

    assert shops == [
        {
            "shop_id": "445566",
            "shop_name": "Sunset Paper Co",
            "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
        }
    ]
