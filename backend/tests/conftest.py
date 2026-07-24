from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("VELORA_SECRET_ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")

import app.services.provider_connections as commerce
import app.services.publishing as publishing_service
import app.services.products as product_service
import app.services.storage_backfill as storage_backfill
import app.services.storage_orphans as storage_orphans
import app.jobs.publishing as publishing_jobs
from app.api.deps import get_db
from app.core.config import settings
from app.db.database import Base, build_engine
from app.db.encryption import encrypt_value
from app.db.models import ProviderCredential
from app.main import create_app
from app.providers.base import (
    ProviderProductCreateInput,
    ProviderProductCreateResult,
    ProviderProductStatus,
    ProviderPublishResult,
    ProviderStoreRecord,
    ReferenceSnapshotResult,
    ReferenceValidationResult,
)
from app.storage.s3 import StorageObjectInfo, StoredObject


class FakeStorageService:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.object_modified_at: dict[str, datetime] = {}

    def is_configured(self) -> bool:
        return True

    def build_public_url(self, storage_key: str) -> str:
        return f"https://storage.test/{storage_key}"

    def upload_bytes(
        self,
        *,
        storage_key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        self.objects[storage_key] = content
        self.object_modified_at[storage_key] = datetime.now(timezone.utc)
        return StoredObject(
            storage_key=storage_key,
            public_url=self.build_public_url(storage_key),
            checksum=f"sha256-{len(content)}",
            size_bytes=len(content),
        )

    def upload_file(
        self,
        *,
        storage_key: str,
        file,
        size_bytes: int,
        checksum: str,
        content_type: str,
        file_name: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        file.seek(0)
        content = file.read()
        assert len(content) == size_bytes
        self.objects[storage_key] = content
        self.object_modified_at[storage_key] = datetime.now(timezone.utc)
        return StoredObject(
            storage_key=storage_key,
            public_url=self.build_public_url(storage_key),
            checksum=checksum,
            size_bytes=size_bytes,
        )

    def copy_object(self, source_key: str, target_key: str) -> None:
        self.objects[target_key] = self.objects[source_key]
        self.object_modified_at[target_key] = datetime.now(timezone.utc)

    def object_exists(self, storage_key: str) -> bool:
        return storage_key in self.objects

    def delete_object(self, storage_key: str) -> None:
        self.objects.pop(storage_key, None)
        self.object_modified_at.pop(storage_key, None)

    def list_objects(self, prefix: str) -> list[StorageObjectInfo]:
        return [
            StorageObjectInfo(
                storage_key=storage_key,
                last_modified=self.object_modified_at.get(storage_key, datetime.now(timezone.utc)),
                size_bytes=len(content),
            )
            for storage_key, content in self.objects.items()
            if storage_key.startswith(prefix)
        ]

    def read_bytes_limited(self, storage_key: str, *, max_bytes: int) -> bytes:
        content = self.objects[storage_key]
        if len(content) > max_bytes:
            raise ValueError("Object exceeds configured read limit.")
        return content


class FakePrintifyAdapter:
    created_products: dict[str, dict[str, object]] = {}
    updated_products: dict[str, dict[str, object]] = {}
    published_product_ids: set[str] = set()
    publish_failures_remaining: int = 0

    def __init__(self, credentials: dict[str, object]) -> None:
        self.credentials = credentials

    async def discover_store_connections(self) -> list[ProviderStoreRecord]:
        return [
            ProviderStoreRecord(
                provider_store_id="shop-etsy",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Printify Test Shop -> Etsy",
                etsy_shop_id="etsy-shop-fixture",
                discovery_source="provider_api",
            ),
            ProviderStoreRecord(
                provider_store_id="shop-shopify",
                storefront_type="shopify",
                storefront_display_name="Shopify",
                label="Printify Test Shop -> Shopify",
                discovery_source="provider_api",
            ),
        ]

    async def validate_reference(self, *, reference_type: str, reference_value: str) -> ReferenceValidationResult:
        normalized = reference_value.rsplit("/", 1)[-1]
        return ReferenceValidationResult(
            reference_type="printify_product_url",
            normalized_reference_value=normalized,
            provider_resource_id=normalized,
            provider_display_name="Abstract Canvas Template",
        )

    async def fetch_reference_snapshot(
        self,
        *,
        reference_type: str,
        reference_value: str,
        provider_resource_id: str,
    ) -> ReferenceSnapshotResult:
        snapshot = {
            "id": provider_resource_id,
            "title": "Abstract Canvas Template",
            "description": "Template description",
            "tags": ["modern art", "canvas"],
            "blueprint_id": 123,
            "print_provider_id": 456,
            "variants": [
                {"id": 1, "price": 2999, "cost": 1499, "is_enabled": True, "sku": "SRC-10001"},
                {"id": 2, "price": 3499, "cost": 1899, "is_enabled": True, "sku": "SRC-10002"},
            ],
            "print_areas": [
                {
                    "variant_ids": [1, 2],
                    "placeholders": [
                        {
                            "position": "front",
                            "images": [{"x": 0.5, "y": 0.5, "scale": 1.2, "angle": 0}],
                        }
                    ],
                }
            ],
            "sales_channel_properties": [{"listing_id": "etsy-listing-1"}],
        }
        return ReferenceSnapshotResult(
            provider_resource_id=provider_resource_id,
            provider_display_name="Abstract Canvas Template",
            provider_snapshot_json=snapshot,
            product_type="Canvas 16x20",
            configuration_summary="2 variants, 1 print placeholders, blueprint 123, provider 456",
            variant_count=2,
            base_cost_amount=14.99,
            currency="USD",
            base_title="Abstract Canvas Template",
            base_description="Template description",
            base_tags=["modern art", "canvas"],
        )

    async def create_provider_product(self, payload: ProviderProductCreateInput) -> ProviderProductCreateResult:
        provider_product_id = f"pf-{payload.product_id}"
        self.created_products[provider_product_id] = {"payload": payload.model_dump()}
        return ProviderProductCreateResult(
            provider_product_id=provider_product_id,
            external_listing_id=None,
            provider_status="created",
            raw_provider_payload_json={"id": provider_product_id, "title": payload.title},
        )

    async def update_provider_product(
        self,
        *,
        provider_product_id: str,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult:
        self.updated_products[provider_product_id] = {"payload": payload.model_dump()}
        return ProviderProductCreateResult(
            provider_product_id=provider_product_id,
            external_listing_id=f"etsy-{provider_product_id}",
            provider_status="created",
            raw_provider_payload_json={"id": provider_product_id, "title": payload.title},
        )

    async def publish_provider_product(self, *, provider_product_id: str) -> ProviderPublishResult:
        if self.publish_failures_remaining > 0:
            type(self).publish_failures_remaining -= 1
            raise RuntimeError("Transient provider publish failure.")
        self.published_product_ids.add(provider_product_id)
        return ProviderPublishResult(
            provider_product_id=provider_product_id,
            external_listing_id=f"etsy-{provider_product_id}",
            provider_status="published",
            raw_provider_payload_json={"id": provider_product_id, "external": {"id": f"etsy-{provider_product_id}"}},
        )

    async def fetch_provider_product_status(self, *, provider_product_id: str) -> ProviderProductStatus:
        return ProviderProductStatus(
            provider_product_id=provider_product_id,
            external_listing_id=(
                f"etsy-{provider_product_id}"
                if provider_product_id in self.published_product_ids
                else None
            ),
            provider_status=(
                "published" if provider_product_id in self.published_product_ids else "created"
            ),
            raw_provider_payload_json={"id": provider_product_id},
        )

    async def reconcile_provider_product(
        self,
        *,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult | None:
        provider_product_id = f"pf-{payload.product_id}"
        if provider_product_id not in self.created_products:
            return None
        return ProviderProductCreateResult(
            provider_product_id=provider_product_id,
            provider_status="created",
            raw_provider_payload_json={"id": provider_product_id, "title": payload.title},
        )


class FakeGelatoAdapter:
    def __init__(self, credentials: dict[str, object]) -> None:
        self.credentials = credentials

    async def discover_store_connections(self) -> list[ProviderStoreRecord]:
        raw_seeds = self.credentials.get("manual_store_seeds") or []
        return [
            ProviderStoreRecord(
                provider_store_id=str(seed["provider_store_id"]),
                storefront_type=str(seed.get("storefront_type", "unknown")),
                storefront_display_name=str(seed["storefront_display_name"]),
                label=str(seed.get("label") or seed["storefront_display_name"]),
                etsy_shop_id=str(seed.get("etsy_shop_id") or "").strip() or None,
                discovery_source="manual",
            )
            for seed in raw_seeds
        ]

    async def validate_reference(self, *, reference_type: str, reference_value: str) -> ReferenceValidationResult:
        return ReferenceValidationResult(
            reference_type="gelato_template_id",
            normalized_reference_value=reference_value.strip(),
            provider_resource_id=reference_value.strip(),
            provider_display_name="Gelato Poster Template",
        )

    async def fetch_reference_snapshot(
        self,
        *,
        reference_type: str,
        reference_value: str,
        provider_resource_id: str,
    ) -> ReferenceSnapshotResult:
        return ReferenceSnapshotResult(
            provider_resource_id=provider_resource_id,
            provider_display_name="Gelato Poster Template",
            provider_snapshot_json={"id": provider_resource_id, "templateName": "Gelato Poster Template"},
            product_type="Framed Poster",
            configuration_summary="1 variants, placeholders: ImageFront, Printable Material",
            variant_count=1,
            placement_config_json={"design_placeholder_name": "ImageFront", "design_placeholder_names": ["ImageFront"]},
            base_title="Gelato Poster Template",
        )

    async def create_provider_product(self, payload: ProviderProductCreateInput) -> ProviderProductCreateResult:
        provider_product_id = f"gel-{payload.product_id}"
        return ProviderProductCreateResult(
            provider_product_id=provider_product_id,
            external_listing_id=f"gelato-ext-{payload.product_id}",
            provider_status="created",
            raw_provider_payload_json={"id": provider_product_id},
        )

    async def publish_provider_product(self, *, provider_product_id: str) -> ProviderPublishResult:
        return ProviderPublishResult(
            provider_product_id=provider_product_id,
            external_listing_id=f"gelato-ext-{provider_product_id}",
            provider_status="published",
            raw_provider_payload_json={"id": provider_product_id, "status": "published"},
        )

    async def fetch_provider_product_status(self, *, provider_product_id: str) -> ProviderProductStatus:
        return ProviderProductStatus(
            provider_product_id=provider_product_id,
            external_listing_id=f"gelato-ext-{provider_product_id}",
            provider_status="published",
            raw_provider_payload_json={"id": provider_product_id},
        )


def _seed_minimal_etsy_connection(TestingSessionLocal) -> None:
    synced_at = datetime.now(timezone.utc).isoformat()
    with TestingSessionLocal() as db:
        db.add_all(
            [
                ProviderCredential(
                    organization_id="default-org",
                    provider="etsy",
                    key_name="oauth_refresh_token",
                    encrypted_value=encrypt_value("fixture-etsy-refresh-token"),
                ),
                ProviderCredential(
                    organization_id="default-org",
                    provider="etsy",
                    key_name="oauth_seller_user_id",
                    encrypted_value=encrypt_value("fixture-seller-user"),
                ),
                ProviderCredential(
                    organization_id="default-org",
                    provider="etsy",
                    key_name="oauth_shops_json",
                    encrypted_value=encrypt_value(json.dumps([], separators=(",", ":"))),
                ),
                ProviderCredential(
                    organization_id="default-org",
                    provider="etsy",
                    key_name="oauth_last_sync_at",
                    encrypted_value=encrypt_value(synced_at),
                ),
            ]
        )
        db.commit()


@contextmanager
def _build_test_client(tmp_path, monkeypatch, *, seed_etsy_connection: bool) -> Generator[TestClient, None, None]:
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = build_engine(database_url)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, class_=Session)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "clerk_jwks_url", None)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_local = TestingSessionLocal

    fake_storage = FakeStorageService()
    app.state.fake_storage = fake_storage
    FakePrintifyAdapter.created_products = {}
    FakePrintifyAdapter.updated_products = {}
    FakePrintifyAdapter.published_product_ids = set()
    FakePrintifyAdapter.publish_failures_remaining = 0
    app.state.fake_printify_adapter_class = FakePrintifyAdapter

    def fake_get_provider_adapter(provider: str, credentials: dict[str, object]):
        if provider == "printify":
            return FakePrintifyAdapter(credentials)
        if provider == "gelato":
            return FakeGelatoAdapter(credentials)
        raise ValueError(provider)

    monkeypatch.setattr(publishing_service, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(publishing_jobs, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        publishing_jobs.publish_product,
        "send",
        lambda publishing_job_id: publishing_jobs.run_publishing_job(publishing_job_id),
    )
    monkeypatch.setattr(publishing_service, "get_storage_service", lambda: fake_storage)
    monkeypatch.setattr(product_service, "get_storage_service", lambda: fake_storage)
    monkeypatch.setattr(storage_backfill, "get_storage_service", lambda: fake_storage)
    monkeypatch.setattr(storage_orphans, "get_storage_service", lambda: fake_storage)
    monkeypatch.setattr(commerce, "get_provider_adapter", fake_get_provider_adapter)
    monkeypatch.setattr(publishing_service, "get_provider_adapter", fake_get_provider_adapter)
    etsy_image_sync_calls: list[dict[str, object]] = []
    app.state.etsy_image_sync_attempts = 0
    app.state.etsy_image_sync_failures_remaining = 0

    def fake_sync_product_listing_images_to_etsy(**kwargs: object) -> int:
        app.state.etsy_image_sync_attempts += 1
        if app.state.etsy_image_sync_failures_remaining > 0:
            app.state.etsy_image_sync_failures_remaining -= 1
            raise RuntimeError("Etsy image 2 'detail.jpg' upload failed with HTTP 409: request conflict")
        images = list(kwargs.pop("images"))  # type: ignore[arg-type]
        etsy_image_sync_calls.append({**kwargs, "images": images})
        return len(images)

    app.state.etsy_image_sync_calls = etsy_image_sync_calls
    monkeypatch.setattr(
        publishing_service,
        "sync_product_listing_images_to_etsy",
        fake_sync_product_listing_images_to_etsy,
    )
    etsy_listing_sync_calls: list[dict[str, object]] = []
    app.state.etsy_listing_sync_attempts = 0
    app.state.etsy_listing_sync_failures_remaining = 0

    def fake_sync_product_listing_to_etsy(**kwargs: object) -> None:
        app.state.etsy_listing_sync_attempts += 1
        if app.state.etsy_listing_sync_failures_remaining > 0:
            app.state.etsy_listing_sync_failures_remaining -= 1
            raise RuntimeError("Etsy listing update failed with HTTP 409: request conflict")
        etsy_listing_sync_calls.append(kwargs)

    app.state.etsy_listing_sync_calls = etsy_listing_sync_calls
    monkeypatch.setattr(
        publishing_service,
        "sync_product_listing_to_etsy",
        fake_sync_product_listing_to_etsy,
    )

    if seed_etsy_connection:
        _seed_minimal_etsy_connection(TestingSessionLocal)

    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    with _build_test_client(tmp_path, monkeypatch, seed_etsy_connection=True) as test_client:
        yield test_client


@pytest.fixture()
def client_without_etsy(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    with _build_test_client(tmp_path, monkeypatch, seed_etsy_connection=False) as test_client:
        yield test_client
