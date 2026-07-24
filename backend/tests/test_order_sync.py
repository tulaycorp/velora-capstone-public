from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

import app.services.orders as orders_service
from app.core.config import settings
from app.db.models import Order, ProviderStoreConnection, SyncEvent, SyncJob
from app.providers import ProviderOrderPage
from app.providers.gelato import GelatoAdapter
from app.providers.printify import PrintifyAdapter
from app.services.orders import OrderSyncInterruptedError, execute_connection_sync


def _timestamp(day: int) -> datetime:
    return datetime(2026, 7, day, 12, 0, tzinfo=timezone.utc)


def _seed_sync_scope(session_local, *, last_successful_at: datetime | None = None) -> None:
    with session_local() as session:
        session.add(
            ProviderStoreConnection(
                id="connection-1",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="shop-1",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Order Sync Shop",
                status="connected",
                order_sync_last_success_at=last_successful_at,
            )
        )
        session.add(
            SyncJob(
                id="job-1",
                organization_id="default-org",
                job_type="order_sync",
                status="completed",
            )
        )
        session.commit()


class FakeOrderAdapter:
    def __init__(self, pages: dict[str | None, ProviderOrderPage | Exception]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    async def fetch_orders(self, **kwargs) -> ProviderOrderPage:
        self.calls.append(kwargs)
        page = self.pages[kwargs["cursor"]]
        if isinstance(page, Exception):
            raise page
        return page

    def normalize_order(
        self,
        *,
        raw_order: dict[str, object],
        organization_id: str,
        provider_store_connection_id: str,
    ) -> dict[str, object]:
        if raw_order.get("invalid"):
            raise ValueError("invalid fixture")
        external_order_id = str(raw_order["id"])
        return {
            "organization_id": organization_id,
            "provider_store_connection_id": provider_store_connection_id,
            "provider": "printify",
            "external_order_id": external_order_id,
            "display_order_id": external_order_id,
            "fulfillment_status": str(raw_order.get("status") or "pending"),
            "currency": "USD",
            "total_amount": Decimal(str(raw_order.get("total") or "10.00")),
            "raw_payload_json": raw_order,
        }


def _configure_service(client, monkeypatch, adapter: FakeOrderAdapter) -> None:
    monkeypatch.setattr(orders_service, "SessionLocal", client.app.state.testing_session_local)
    monkeypatch.setattr(orders_service, "get_provider_credentials", lambda *args, **kwargs: {"api_token": "test"})
    monkeypatch.setattr(orders_service, "get_provider_adapter", lambda *args, **kwargs: adapter)


@pytest.mark.asyncio
async def test_connection_sync_commits_multiple_pages_and_reports_bulk_counts(client, monkeypatch) -> None:
    session_local = client.app.state.testing_session_local
    _seed_sync_scope(session_local)
    with session_local() as session:
        session.add(
            Order(
                id="existing-order",
                organization_id="default-org",
                provider_store_connection_id="connection-1",
                provider="printify",
                external_order_id="order-1",
                display_order_id="order-1",
                fulfillment_status="pending",
                currency="USD",
                total_amount=Decimal("9.00"),
            )
        )
        session.commit()

    adapter = FakeOrderAdapter(
        {
            None: ProviderOrderPage(
                orders=[{"id": "order-1", "status": "shipped"}, {"id": "order-2"}],
                fetched_count=2,
                next_cursor="2",
                observed_watermark_at=_timestamp(14),
            ),
            "2": ProviderOrderPage(
                orders=[{"id": "order-3"}],
                fetched_count=1,
                observed_watermark_at=_timestamp(15),
            ),
        }
    )
    _configure_service(client, monkeypatch, adapter)
    heartbeat_count = 0

    def heartbeat() -> bool:
        nonlocal heartbeat_count
        heartbeat_count += 1
        return True

    result = await execute_connection_sync("job-1", "connection-1", heartbeat=heartbeat)

    assert result.outcome == "completed"
    assert (result.pages, result.fetched, result.inserted, result.updated) == (2, 3, 2, 1)
    assert result.skipped == 0
    assert result.failed == 0
    assert heartbeat_count == 2
    assert [call["cursor"] for call in adapter.calls] == [None, "2"]
    with session_local() as session:
        orders = session.scalars(select(Order).order_by(Order.external_order_id)).all()
        connection = session.get(ProviderStoreConnection, "connection-1")
        events = session.scalars(select(SyncEvent).where(SyncEvent.sync_job_id == "job-1")).all()

    assert [order.external_order_id for order in orders] == ["order-1", "order-2", "order-3"]
    assert orders[0].fulfillment_status == "shipped"
    assert connection is not None
    assert connection.order_sync_cursor_json is None
    assert connection.order_sync_watermark_at == _timestamp(15).replace(tzinfo=None)
    assert connection.order_sync_last_success_at is not None
    assert sum(event.event_type == "order_page_committed" for event in events) == 2


@pytest.mark.asyncio
async def test_connection_sync_resumes_from_committed_cursor_after_interruption(client, monkeypatch) -> None:
    session_local = client.app.state.testing_session_local
    _seed_sync_scope(session_local)
    first_adapter = FakeOrderAdapter(
        {
            None: ProviderOrderPage(
                orders=[{"id": "order-1"}],
                fetched_count=1,
                next_cursor="2",
                observed_watermark_at=_timestamp(14),
            )
        }
    )
    _configure_service(client, monkeypatch, first_adapter)

    with pytest.raises(OrderSyncInterruptedError):
        await execute_connection_sync("job-1", "connection-1", heartbeat=lambda: False)

    with session_local() as session:
        connection = session.get(ProviderStoreConnection, "connection-1")
        order_ids = session.scalars(select(Order.external_order_id)).all()
    assert connection is not None
    assert connection.order_sync_cursor_json["cursor"] == "2"
    assert order_ids == ["order-1"]

    second_adapter = FakeOrderAdapter(
        {
            "2": ProviderOrderPage(
                orders=[{"id": "order-2"}],
                fetched_count=1,
                observed_watermark_at=_timestamp(15),
            )
        }
    )
    _configure_service(client, monkeypatch, second_adapter)
    result = await execute_connection_sync("job-1", "connection-1")

    assert result.outcome == "completed"
    assert second_adapter.calls[0]["cursor"] == "2"
    with session_local() as session:
        connection = session.get(ProviderStoreConnection, "connection-1")
        order_ids = session.scalars(select(Order.external_order_id).order_by(Order.external_order_id)).all()
    assert connection is not None
    assert connection.order_sync_cursor_json is None
    assert order_ids == ["order-1", "order-2"]


@pytest.mark.asyncio
async def test_connection_sync_keeps_cursor_and_reports_partial_provider_failure(client, monkeypatch) -> None:
    session_local = client.app.state.testing_session_local
    previous_success = _timestamp(10)
    _seed_sync_scope(session_local, last_successful_at=previous_success)
    adapter = FakeOrderAdapter(
        {
            None: ProviderOrderPage(
                orders=[{"id": "order-1"}],
                fetched_count=1,
                next_cursor="2",
                observed_watermark_at=_timestamp(14),
            ),
            "2": RuntimeError("provider payload must not be persisted"),
        }
    )
    _configure_service(client, monkeypatch, adapter)

    result = await execute_connection_sync("job-1", "connection-1")

    assert result.outcome == "partial"
    assert result.pages == 1
    assert result.failed == 1
    assert result.last_successful_at == previous_success
    assert result.failure_summaries == [
        {"code": "provider_page_request_failed", "count": 1, "error_type": "RuntimeError"}
    ]
    with session_local() as session:
        connection = session.get(ProviderStoreConnection, "connection-1")
        error_event = session.scalars(
            select(SyncEvent).where(SyncEvent.event_type == "connection_error")
        ).one()
    assert connection is not None
    assert connection.order_sync_cursor_json["cursor"] == "2"
    assert connection.order_sync_watermark_at is None
    assert "payload" not in str(error_event.details_json)


@pytest.mark.asyncio
async def test_connection_sync_reports_item_failure_without_advancing_watermark(client, monkeypatch) -> None:
    session_local = client.app.state.testing_session_local
    _seed_sync_scope(session_local)
    adapter = FakeOrderAdapter(
        {
            None: ProviderOrderPage(
                orders=[{"id": "order-1"}, {"id": "bad-order", "invalid": True}],
                fetched_count=2,
                observed_watermark_at=_timestamp(15),
            )
        }
    )
    _configure_service(client, monkeypatch, adapter)

    result = await execute_connection_sync("job-1", "connection-1")

    assert result.outcome == "partial"
    assert (result.fetched, result.inserted, result.failed) == (2, 1, 1)
    with session_local() as session:
        connection = session.get(ProviderStoreConnection, "connection-1")
    assert connection is not None
    assert connection.order_sync_watermark_at is None
    assert connection.order_sync_last_success_at is None


@pytest.mark.asyncio
async def test_printify_order_page_uses_cursor_and_bounds_detail_concurrency(monkeypatch) -> None:
    adapter = PrintifyAdapter({"api_token": "test"})
    active_detail_requests = 0
    max_active_detail_requests = 0
    requested_paths: list[str] = []

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_request(_client, method: str, path: str, **kwargs):
        nonlocal active_detail_requests, max_active_detail_requests
        requested_paths.append(path)
        request = httpx.Request(method, f"https://api.printify.test{path}")
        if path.endswith("orders.json?page=3&limit=3"):
            return httpx.Response(
                200,
                json={
                    "current_page": 3,
                    "last_page": 4,
                    "data": [
                        {"id": "order-1", "updated_at": "2026-07-15T12:00:00Z"},
                        {"id": "order-2", "updated_at": "2026-07-14T12:00:00Z"},
                        {"id": "order-3", "updated_at": "2026-07-13T12:00:00Z"},
                    ],
                },
                request=request,
            )
        active_detail_requests += 1
        max_active_detail_requests = max(max_active_detail_requests, active_detail_requests)
        await asyncio.sleep(0)
        active_detail_requests -= 1
        if "/orders/order-2.json" in path:
            raise httpx.ConnectError("fixture detail failure", request=request)
        return httpx.Response(200, json={"id": path.split("/")[-1].split(".")[0]}, request=request)

    monkeypatch.setattr(settings, "order_sync_detail_concurrency", 2)
    monkeypatch.setattr(adapter, "_get_client", lambda: DummyClient())
    monkeypatch.setattr(adapter, "_request_with_retry", fake_request)

    page = await adapter.fetch_orders(provider_store_id="shop-1", cursor="3", limit=3)

    assert page.fetched_count == 3
    assert len(page.orders) == 2
    assert page.failed_count == 1
    assert page.next_cursor == "4"
    assert max_active_detail_requests == 2
    assert requested_paths[0].endswith("orders.json?page=3&limit=3")


@pytest.mark.asyncio
async def test_printify_order_page_stops_at_overlap_boundary(monkeypatch) -> None:
    adapter = PrintifyAdapter({"api_token": "test"})

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_request(_client, method: str, path: str, **kwargs):
        request = httpx.Request(method, f"https://api.printify.test{path}")
        if path.endswith("orders.json?page=1&limit=2"):
            return httpx.Response(
                200,
                json={
                    "current_page": 1,
                    "last_page": 5,
                    "data": [
                        {"id": "new-order", "updated_at": "2026-07-15T12:00:00Z"},
                        {"id": "old-order", "updated_at": "2026-07-10T12:00:00Z"},
                    ],
                },
                request=request,
            )
        return httpx.Response(200, json={"id": "new-order"}, request=request)

    monkeypatch.setattr(adapter, "_get_client", lambda: DummyClient())
    monkeypatch.setattr(adapter, "_request_with_retry", fake_request)

    page = await adapter.fetch_orders(
        provider_store_id="shop-1",
        since=_timestamp(14),
        limit=2,
    )

    assert page.fetched_count == 1
    assert [order["id"] for order in page.orders] == ["new-order"]
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_gelato_order_page_sends_watermark_and_offset(monkeypatch) -> None:
    adapter = GelatoAdapter({"api_key": "test"})
    captured_payload: dict[str, object] = {}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post(_client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        captured_payload.update(payload)
        request = httpx.Request("POST", f"https://order.gelato.test{endpoint}")
        return httpx.Response(
            200,
            json={
                "orders": [
                    {"id": "order-1", "storeId": "store-1", "updatedAt": "2026-07-15T12:00:00Z"},
                    {"id": "other-order", "storeId": "other-store", "updatedAt": "2026-07-15T12:00:00Z"},
                ]
            },
            request=request,
        )

    async def fake_get(_client, *, endpoint: str, timeout: float, action: str):
        request = httpx.Request("GET", f"https://order.gelato.test{endpoint}")
        if endpoint.startswith("/v4/orders/"):
            return httpx.Response(200, json={"id": "order-1", "orderReferenceId": "ref-1"}, request=request)
        return httpx.Response(200, json={"status": "printed"}, request=request)

    monkeypatch.setattr(adapter, "_get_orders_client", lambda: DummyClient())
    monkeypatch.setattr(adapter, "_post_with_backoff", fake_post)
    monkeypatch.setattr(adapter, "_get_with_backoff", fake_get)

    page = await adapter.fetch_orders(
        provider_store_id="store-1",
        since=_timestamp(14),
        cursor="4",
        limit=2,
    )

    assert captured_payload == {
        "orderTypes": ["order"],
        "storeIds": ["store-1"],
        "limit": 2,
        "offset": 4,
        "startDate": _timestamp(14).isoformat(),
    }
    assert page.fetched_count == 1
    assert page.next_cursor == "6"
    assert page.orders[0]["_production_status"] == {"status": "printed"}
