from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

import app.services.products as product_service
from app.core.config import settings
from app.db.models import DesignAsset
from app.services.storage_orphans import cleanup_orphaned_media
from tests.media_fixtures import VALID_JPEG_BYTES, VALID_PNG_BYTES, VALID_WEBP_BYTES


def _create_product(client) -> dict[str, object]:
    assert client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    ).status_code == 200
    connection = client.post("/provider-store-connections/sync/printify").json()["connections"][0]
    design_asset = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    ).json()
    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Bounded media blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": connection["id"],
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/bounded-media",
        },
    )
    assert blueprint_response.status_code == 201
    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint_response.json()["id"],
            "design_asset_id": design_asset["id"],
            "title": "Bounded media product",
        },
    )
    assert product_response.status_code == 201
    return product_response.json()


@pytest.mark.parametrize(
    ("file_name", "content_type", "content"),
    (
        ("design.png", "image/png", VALID_PNG_BYTES),
        ("design.jpg", "image/jpeg", VALID_JPEG_BYTES),
        ("design.webp", "image/webp", VALID_WEBP_BYTES),
    ),
)
def test_upload_accepts_allowlisted_image_formats(client, file_name, content_type, content) -> None:
    response = client.post(
        "/design-assets",
        files={"file": (file_name, content, content_type)},
    )
    assert response.status_code == 201
    assert response.json()["content_type"] == content_type


def test_upload_rejects_svg_spoofed_and_malformed_images(client) -> None:
    svg_response = client.post(
        "/design-assets",
        files={"file": ("design.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
    )
    assert svg_response.status_code == 415
    assert "SVG" in svg_response.json()["detail"]

    spoofed_response = client.post(
        "/design-assets",
        files={"file": ("design.jpg", VALID_PNG_BYTES, "image/jpeg")},
    )
    assert spoofed_response.status_code == 415
    assert "does not match" in spoofed_response.json()["detail"]

    malformed_response = client.post(
        "/design-assets",
        files={"file": ("design.png", b"\x89PNG\r\n\x1a\ntruncated", "image/png")},
    )
    assert malformed_response.status_code == 415
    assert "malformed" in malformed_response.json()["detail"]
    assert client.app.state.fake_storage.objects == {}


def test_upload_enforces_known_request_and_streamed_file_limits(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_max_request_bytes", 100)
    known_length_response = client.post(
        "/design-assets",
        headers={"content-length": "101"},
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert known_length_response.status_code == 413
    assert "request exceeds" in known_length_response.json()["detail"]

    monkeypatch.setattr(settings, "upload_max_request_bytes", 10_000)
    monkeypatch.setattr(settings, "upload_max_file_bytes", len(VALID_PNG_BYTES) - 1)
    streamed_limit_response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert streamed_limit_response.status_code == 413
    assert "file limit" in streamed_limit_response.json()["detail"]
    assert client.app.state.fake_storage.objects == {}


def test_upload_enforces_request_limit_without_content_length(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_max_request_bytes", 100)
    response = client.post(
        "/design-assets",
        content=iter((b"x" * 60, b"y" * 60)),
        headers={"content-type": "multipart/form-data; boundary=bounded"},
    )
    assert response.status_code == 413
    assert "request exceeds" in response.json()["detail"]
    assert client.app.state.fake_storage.objects == {}


def test_product_image_count_is_enforced_by_the_backend(client, monkeypatch) -> None:
    product = _create_product(client)
    monkeypatch.setattr(settings, "upload_max_mockups_per_product", 1)
    first = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("first.png", VALID_PNG_BYTES, "image/png")},
    )
    assert first.status_code == 201
    second = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("second.png", VALID_PNG_BYTES, "image/png")},
    )
    assert second.status_code == 409
    assert "maximum of 1" in second.json()["detail"]


def test_design_upload_compensates_when_database_persistence_fails(client, monkeypatch) -> None:
    existing_keys = set(client.app.state.fake_storage.objects)

    def fail_persistence(_session, _row) -> None:
        raise RuntimeError("injected database failure")

    monkeypatch.setattr(product_service, "_persist_uploaded_media", fail_persistence)
    response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert response.status_code == 500
    assert "rolled back" in response.json()["detail"]
    assert set(client.app.state.fake_storage.objects) == existing_keys


def test_design_upload_storage_failure_creates_neither_object_nor_row(client, monkeypatch) -> None:
    storage = client.app.state.fake_storage
    existing_keys = set(storage.objects)
    with client.app.state.testing_session_local() as db:
        existing_rows = db.scalar(select(func.count()).select_from(DesignAsset))

    def fail_upload(**_kwargs):
        raise RuntimeError("injected storage failure")

    monkeypatch.setattr(storage, "upload_file", fail_upload)
    response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert response.status_code == 502
    assert set(storage.objects) == existing_keys
    with client.app.state.testing_session_local() as db:
        assert db.scalar(select(func.count()).select_from(DesignAsset)) == existing_rows


def test_mockup_upload_compensates_when_database_persistence_fails(client, monkeypatch) -> None:
    product = _create_product(client)
    existing_keys = set(client.app.state.fake_storage.objects)

    def fail_persistence(_session, _row) -> None:
        raise RuntimeError("injected database failure")

    monkeypatch.setattr(product_service, "_persist_uploaded_media", fail_persistence)
    response = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("mockup.png", VALID_PNG_BYTES, "image/png")},
    )
    assert response.status_code == 500
    assert "rolled back" in response.json()["detail"]
    assert set(client.app.state.fake_storage.objects) == existing_keys


def test_orphan_cleanup_is_aged_idempotent_and_retryable(client, monkeypatch) -> None:
    product = _create_product(client)
    referenced_key = product["design_asset"]["storage_key"]
    storage = client.app.state.fake_storage
    now = datetime.now(timezone.utc)
    old_orphan = "organizations/default-org/design-assets/orphan-old/source.png"
    new_orphan = "organizations/default-org/design-assets/orphan-new/source.png"
    storage.objects[old_orphan] = VALID_PNG_BYTES
    storage.objects[new_orphan] = VALID_PNG_BYTES
    storage.object_modified_at[old_orphan] = now - timedelta(hours=2)
    storage.object_modified_at[new_orphan] = now
    monkeypatch.setattr(settings, "storage_orphan_min_age_seconds", 3600)

    with client.app.state.testing_session_local() as db:
        dry_run = cleanup_orphaned_media(db, apply=False, now=now)
    assert dry_run.referenced == 1
    assert dry_run.orphaned == 1
    assert dry_run.too_new == 1
    assert dry_run.deleted == 0

    original_delete = storage.delete_object
    attempts = 0

    def fail_once(storage_key: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected delete failure")
        original_delete(storage_key)

    monkeypatch.setattr(storage, "delete_object", fail_once)
    with client.app.state.testing_session_local() as db:
        failed_run = cleanup_orphaned_media(db, apply=True, now=now)
    assert failed_run.failed == 1
    assert old_orphan in storage.objects

    with client.app.state.testing_session_local() as db:
        retry_run = cleanup_orphaned_media(db, apply=True, now=now)
    assert retry_run.deleted == 1
    assert old_orphan not in storage.objects
    assert new_orphan in storage.objects
    assert referenced_key in storage.objects

    with client.app.state.testing_session_local() as db:
        idempotent_run = cleanup_orphaned_media(db, apply=True, now=now)
    assert idempotent_run.orphaned == 0
    assert idempotent_run.deleted == 0
