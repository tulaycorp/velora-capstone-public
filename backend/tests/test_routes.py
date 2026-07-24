from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
import httpx
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.deps import get_default_actor_context
from app.api.routes import health as health_routes
from app.core.config import settings
from app.db.encryption import decrypt_value, encrypt_value
from app.db.models import (
    AnalyticsSnapshot,
    DesignAsset,
    Expense,
    Mockup,
    Order,
    OrderLineItem,
    ProductBlueprint,
    ProviderCredential,
    ProviderProductDraft,
    ProviderStoreConnection,
    PublishingJob,
    SyncJob as DBSyncJob,
)
from app.providers.base import ProviderProductCreateInput, ProviderStoreRecord
from app.providers.gelato import GelatoAdapter
from app.providers.printify import PrintifyAdapter
from app.services import etsy
import app.services.provider_connections as commerce
from app.services import publishing as publishing_service
import app.services.products as product_service
from app.services.analytics import refresh_etsy_analytics_snapshot
from app.storage.s3 import S3StorageService
from app.api.routes import sync_jobs as sync_jobs_routes
from tests.media_fixtures import VALID_JPEG_BYTES, VALID_PNG_BYTES


def _attach_publishable_mockup(client, product_id: str) -> None:
    response = client.post(
        f"/products/{product_id}/mockups",
        files={"file": ("listing.png", VALID_PNG_BYTES, "image/png")},
    )
    assert response.status_code == 201


def test_health_route(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_route_requires_database_and_redis(client, monkeypatch) -> None:
    monkeypatch.setattr(health_routes, "_database_is_ready", lambda: True)
    monkeypatch.setattr(health_routes, "_redis_is_ready", lambda: True)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_route_fails_closed_when_a_dependency_is_unavailable(client, monkeypatch) -> None:
    monkeypatch.setattr(health_routes, "_database_is_ready", lambda: False)
    monkeypatch.setattr(health_routes, "_redis_is_ready", lambda: True)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Required runtime dependencies are unavailable."


def test_run_order_sync_route_falls_back_when_redis_is_unavailable(client, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fail_send(_job_id: str, _organization_id: str) -> None:
        raise RedisConnectionError("redis offline")

    def fake_background_run(job_id: str, organization_id: str) -> None:
        captured["job_id"] = job_id
        captured["organization_id"] = organization_id

    monkeypatch.setattr(
        sync_jobs_routes,
        "sync_org_orders",
        SimpleNamespace(send=fail_send),
    )
    monkeypatch.setattr(sync_jobs_routes, "run_order_sync_background", fake_background_run)

    response = client.post("/sync-jobs/orders/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "order_sync"
    assert payload["status"] == "queued"
    assert captured == {
        "job_id": payload["id"],
        "organization_id": "default-org",
    }


def test_run_order_sync_route_creates_new_job_when_no_active_job_exists(client, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_send(job_id: str, organization_id: str) -> None:
        captured["job_id"] = job_id
        captured["organization_id"] = organization_id

    monkeypatch.setattr(
        sync_jobs_routes,
        "sync_org_orders",
        SimpleNamespace(send=fake_send),
    )

    response = client.post("/sync-jobs/orders/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "order_sync"
    assert payload["status"] == "queued"
    assert captured == {
        "job_id": payload["id"],
        "organization_id": "default-org",
    }


def test_run_order_sync_route_reuses_existing_active_job(client, monkeypatch) -> None:
    existing_job_id = "job-existing-running"

    def fail_send(_job_id: str, _organization_id: str) -> None:
        raise AssertionError("Redis send should not be called when an active job already exists.")

    monkeypatch.setattr(
        sync_jobs_routes,
        "sync_org_orders",
        SimpleNamespace(send=fail_send),
    )

    with client.app.state.testing_session_local() as db:
        db.add(
            DBSyncJob(
                id=existing_job_id,
                organization_id="default-org",
                job_type="order_sync",
                status="running",
                started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
                lease_owner="test-worker",
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                heartbeat_at=datetime.now(timezone.utc),
                attempt_count=1,
            )
        )
        db.commit()

    response = client.post("/sync-jobs/orders/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == existing_job_id
    assert payload["status"] == "running"

    with client.app.state.testing_session_local() as db:
        running_jobs = db.scalars(
            select(DBSyncJob).where(
                DBSyncJob.organization_id == "default-org",
                DBSyncJob.job_type == "order_sync",
            )
        ).all()
    assert len(running_jobs) == 1


def test_run_order_sync_route_reuses_recent_terminal_job_unless_forced(client, monkeypatch) -> None:
    captured: list[str] = []

    def fake_send(job_id: str, _organization_id: str) -> None:
        captured.append(job_id)

    monkeypatch.setattr(sync_jobs_routes, "sync_org_orders", SimpleNamespace(send=fake_send))
    with client.app.state.testing_session_local() as db:
        db.add(
            DBSyncJob(
                id="job-recent-completed",
                organization_id="default-org",
                job_type="order_sync",
                status="completed",
                completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        db.commit()

    automatic_response = client.post("/sync-jobs/orders/run")
    forced_response = client.post("/sync-jobs/orders/run?force=true")

    assert automatic_response.status_code == 200
    assert automatic_response.json()["id"] == "job-recent-completed"
    assert forced_response.status_code == 200
    assert forced_response.json()["status"] == "queued"
    assert captured == [forced_response.json()["id"]]


def test_run_order_sync_route_redispatches_an_existing_queued_job(client, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_send(job_id: str, organization_id: str) -> None:
        captured["job_id"] = job_id
        captured["organization_id"] = organization_id

    monkeypatch.setattr(sync_jobs_routes, "sync_org_orders", SimpleNamespace(send=fake_send))
    with client.app.state.testing_session_local() as db:
        db.add(
            DBSyncJob(
                id="job-existing-queued",
                organization_id="default-org",
                job_type="order_sync",
                status="queued",
            )
        )
        db.commit()

    response = client.post("/sync-jobs/orders/run")

    assert response.status_code == 200
    assert response.json()["id"] == "job-existing-queued"
    assert captured == {
        "job_id": "job-existing-queued",
        "organization_id": "default-org",
    }


def test_list_orders_redacts_card_like_values_from_public_response(client) -> None:
    card_like_value = "4280323450522"
    destination_country = "Philippines"
    destination_city = "Manila"
    tracking_url = f"https://carrier.example.test/track/{card_like_value}"
    customer_name = "Public Customer"

    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="order-redaction-store",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="shop-redaction",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Redaction Test Shop",
                status="connected",
            )
        )
        db.add(
            Order(
                id="order-redaction",
                organization_id="default-org",
                provider_store_connection_id="order-redaction-store",
                provider="printify",
                external_order_id="external-redaction",
                display_order_id="#2001",
                customer_name=customer_name,
                product_summary="Canvas",
                fulfillment_status="processing",
                currency="USD",
                total_amount=Decimal("42.00"),
                tracking_code=card_like_value,
                tracking_url=tracking_url,
                destination_city=destination_city,
                destination_country=destination_country,
                raw_payload_json={
                    "provider_internal_note": card_like_value,
                    "nested": {"raw_card_like_value": card_like_value},
                },
            )
        )
        db.commit()

    response = client.get("/orders")

    assert response.status_code == 200
    response_text = response.text
    response_body = response.json()
    payload = response_body["items"]
    assert len(payload) == 1
    assert response_body["page"] == 1
    assert response_body["page_size"] == 15
    assert response_body["total"] == 1
    assert "raw_payload_json" not in payload[0]
    assert card_like_value not in response_text
    assert customer_name not in response_text
    assert destination_city not in response_text
    assert destination_country not in response_text
    assert tracking_url not in response_text
    assert "customer_name" not in payload[0]
    assert "tracking_code" not in payload[0]
    assert "tracking_url" not in payload[0]
    assert "destination_city" not in payload[0]
    assert "destination_country" not in payload[0]
    assert payload[0]["product_summary"] == "Canvas"
    assert payload[0]["provider_order_url"] is None


def test_list_orders_redacts_card_like_substrings_inside_tracking_fields(client) -> None:
    embedded_card_like_value = "4280323450522"
    tracking_code = f"1ZV0H{embedded_card_like_value}"
    tracking_url = f"https://wwwapps.ups.com/WebTracking/track?track=yes&trackNums={tracking_code}"

    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="order-redaction-store-embedded",
                organization_id="default-org",
                provider="gelato",
                credential_key="default",
                provider_store_id="shop-redaction-embedded",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Embedded Redaction Test Shop",
                status="connected",
            )
        )
        db.add(
            Order(
                id="order-redaction-embedded",
                organization_id="default-org",
                provider_store_connection_id="order-redaction-store-embedded",
                provider="gelato",
                external_order_id="external-redaction-embedded",
                display_order_id="#2002",
                customer_name="Public Customer",
                product_summary="Poster",
                fulfillment_status="processing",
                currency="USD",
                total_amount=Decimal("42.00"),
                tracking_code=tracking_code,
                tracking_url=tracking_url,
            )
        )
        db.commit()

    response = client.get("/orders")

    assert response.status_code == 200
    response_text = response.text
    payload = response.json()["items"]
    assert len(payload) == 1
    assert embedded_card_like_value not in response_text
    assert tracking_code not in response_text
    assert tracking_url not in response_text
    assert "tracking_code" not in payload[0]
    assert "tracking_url" not in payload[0]


def test_list_orders_projects_filters_and_paginates_public_rows(client) -> None:
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                ProviderStoreConnection(
                    id="orders-page-printify-store",
                    organization_id="default-org",
                    provider="printify",
                    credential_key="default",
                    provider_store_id="orders-page-printify-shop",
                    storefront_type="etsy",
                    storefront_display_name="Etsy",
                    label="Printify Orders",
                    status="connected",
                ),
                ProviderStoreConnection(
                    id="orders-page-gelato-store",
                    organization_id="default-org",
                    provider="gelato",
                    credential_key="default",
                    provider_store_id="orders-page-gelato-shop",
                    storefront_type="etsy",
                    storefront_display_name="Etsy",
                    label="Gelato Orders",
                    status="connected",
                ),
                ProviderStoreConnection(
                    id="orders-page-other-org-store",
                    organization_id="other-org",
                    provider="printify",
                    credential_key="default",
                    provider_store_id="orders-page-other-org-shop",
                    storefront_type="etsy",
                    storefront_display_name="Etsy",
                    label="Other Organization Orders",
                    status="connected",
                ),
            ]
        )
        for index in range(18):
            provider = "printify" if index < 12 else "gelato"
            store_id = (
                "orders-page-printify-store"
                if provider == "printify"
                else "orders-page-gelato-store"
            )
            db.add(
                Order(
                    id=f"orders-page-{index:02d}",
                    organization_id="default-org",
                    provider_store_connection_id=store_id,
                    provider=provider,
                    external_order_id=f"orders-page-external-{index:02d}",
                    display_order_id=f"#{index:04d}",
                    product_summary=f"Product {index}",
                    fulfillment_status="fulfilled" if index % 2 == 0 else "pending",
                    currency="USD",
                    total_amount=Decimal("25.00"),
                    order_created_at=now - timedelta(minutes=index),
                    raw_payload_json={"private": "provider-payload" * 100},
                )
            )
        db.add(
            Order(
                id="orders-page-other-org-order",
                organization_id="other-org",
                provider_store_connection_id="orders-page-other-org-store",
                provider="printify",
                external_order_id="orders-page-other-org-external",
                display_order_id="#private",
                product_summary="Other organization product",
                fulfillment_status="fulfilled",
                currency="USD",
                total_amount=Decimal("99.00"),
                order_created_at=now + timedelta(minutes=1),
            )
        )
        engine = db.get_bind()
        db.commit()

    statements: list[str] = []

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        first_page = client.get("/orders?page=1&page_size=5")
        filtered_page = client.get(
            "/orders?page=2&page_size=3&provider=printify&fulfillment_status=fulfilled"
        )
        store_page = client.get(
            "/orders?store_connection_id=orders-page-gelato-store"
        )
        out_of_range_page = client.get("/orders?page=99&page_size=5")
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["page"] == 1
    assert first_payload["page_size"] == 5
    assert first_payload["total"] == 18
    assert first_payload["total_pages"] == 4
    assert [item["id"] for item in first_payload["items"]] == [
        "orders-page-00",
        "orders-page-01",
        "orders-page-02",
        "orders-page-03",
        "orders-page-04",
    ]
    assert first_payload["filters"]["providers"] == ["gelato", "printify"]
    assert first_payload["filters"]["fulfillment_statuses"] == [
        "fulfilled",
        "pending",
    ]
    assert [store["id"] for store in first_payload["filters"]["stores"]] == [
        "orders-page-gelato-store",
        "orders-page-printify-store",
    ]

    assert filtered_page.status_code == 200
    filtered_payload = filtered_page.json()
    assert filtered_payload["total"] == 6
    assert filtered_payload["total_pages"] == 2
    assert [item["id"] for item in filtered_payload["items"]] == [
        "orders-page-06",
        "orders-page-08",
        "orders-page-10",
    ]

    assert store_page.status_code == 200
    store_payload = store_page.json()
    assert store_payload["total"] == 6
    assert store_payload["filters"]["providers"] == ["gelato", "printify"]
    assert [store["id"] for store in store_payload["filters"]["stores"]] == [
        "orders-page-gelato-store",
        "orders-page-printify-store",
    ]

    assert out_of_range_page.status_code == 200
    assert out_of_range_page.json()["items"] == []
    assert out_of_range_page.json()["total"] == 18

    order_page_statements = [
        " ".join(statement.split())
        for statement in statements
        if statement.lstrip().lower().startswith("select") and "orders." in statement.lower()
    ]
    assert order_page_statements
    for statement in order_page_statements:
        assert "raw_payload_json" not in statement
        assert "customer_name" not in statement
        assert "tracking_code" not in statement
        assert "tracking_url" not in statement
        assert "destination_city" not in statement
        assert "destination_country" not in statement


def test_list_orders_validates_page_bounds(client) -> None:
    assert client.get("/orders?page=0").status_code == 422
    assert client.get("/orders?page_size=0").status_code == 422
    assert client.get("/orders?page_size=101").status_code == 422


def test_get_latest_order_sync_job_route_returns_latest_org_scoped_job(client) -> None:
    expected_latest_id = "job-latest-order-sync"
    now = datetime.now(timezone.utc)

    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                DBSyncJob(
                    id="job-old-order-sync",
                    organization_id="default-org",
                    job_type="order_sync",
                    status="completed",
                    started_at=now - timedelta(minutes=15),
                    completed_at=now - timedelta(minutes=14),
                    error_message=None,
                ),
                DBSyncJob(
                    id=expected_latest_id,
                    organization_id="default-org",
                    job_type="order_sync",
                    status="failed",
                    started_at=now - timedelta(minutes=2),
                    completed_at=now - timedelta(minutes=1),
                    error_message="Provider timeout",
                ),
                DBSyncJob(
                    id="job-other-type",
                    organization_id="default-org",
                    job_type="inventory_sync",
                    status="completed",
                    started_at=now - timedelta(minutes=1),
                    completed_at=now - timedelta(minutes=1),
                ),
                DBSyncJob(
                    id="job-other-org",
                    organization_id="other-org",
                    job_type="order_sync",
                    status="running",
                    started_at=now,
                    lease_owner="other-worker",
                    lease_expires_at=now + timedelta(minutes=5),
                    heartbeat_at=now,
                    attempt_count=1,
                ),
            ]
        )
        db.commit()

    response = client.get("/sync-jobs/orders/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload is not None
    assert payload["id"] == expected_latest_id
    assert payload["status"] == "failed"
    assert payload["error_message"] == "Provider timeout"


def test_get_latest_order_sync_job_route_returns_null_when_missing(client) -> None:
    response = client.get("/sync-jobs/orders/latest")

    assert response.status_code == 200
    assert response.json() is None


def test_local_session_context_route(client) -> None:
    response = client.get("/session-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["onboarding_status"] == "approved"
    assert payload["membership"]["role"] == "admin"
    assert payload["organization"]["name"] == "Default Organization"


def _seed_workspace_analytics_fixture(
    client,
    *,
    now: datetime,
    include_etsy_connection: bool,
) -> dict[str, object]:
    connection_ids = {
        "north_printify": "conn-north-printify",
        "north_gelato": "conn-north-gelato",
        "south_printify": "conn-south-printify",
        "shopify": "conn-shopify-main",
    }
    blueprint_ids = {
        "north_printify": "bp-north-printify",
        "north_gelato": "bp-north-gelato",
        "south_printify": "bp-south-printify",
        "shopify": "bp-shopify-main",
    }
    draft_ids = {
        "needs_work": "draft-needs-work",
        "retry": "draft-retry",
        "north_live": "draft-north-live",
        "south_live": "draft-south-live",
    }

    with client.app.state.testing_session_local() as db:
        if include_etsy_connection:
            scoped_rows = db.scalars(
                select(ProviderCredential).where(
                    ProviderCredential.organization_id == "default-org",
                    ProviderCredential.provider == "etsy",
                )
            ).all()
            rows_by_key = {row.key_name: row for row in scoped_rows}
            rows_by_key["oauth_seller_user_id"].encrypted_value = encrypt_value("12345678")
            rows_by_key["oauth_last_sync_at"].encrypted_value = encrypt_value(now.isoformat())
            rows_by_key["oauth_shops_json"].encrypted_value = encrypt_value(
                json.dumps(
                    [
                        {
                            "shop_id": "etsy-shop-north",
                            "shop_name": "North Shop",
                            "shop_url": "https://www.etsy.com/shop/NorthShop",
                        },
                        {
                            "shop_id": "etsy-shop-south",
                            "shop_name": "South Shop",
                            "shop_url": "https://www.etsy.com/shop/SouthShop",
                        },
                    ],
                    separators=(",", ":"),
                )
            )

            if "oauth_scopes_json" not in rows_by_key:
                db.add(
                    ProviderCredential(
                        organization_id="default-org",
                        provider="etsy",
                        key_name="oauth_scopes_json",
                        encrypted_value="",
                    )
                )
                db.flush()
                scoped_rows = db.scalars(
                    select(ProviderCredential).where(
                        ProviderCredential.organization_id == "default-org",
                        ProviderCredential.provider == "etsy",
                    )
                ).all()
                rows_by_key = {row.key_name: row for row in scoped_rows}
            rows_by_key["oauth_scopes_json"].encrypted_value = encrypt_value(
                json.dumps(["shops_r", "listings_r", "transactions_r"], separators=(",", ":"))
            )

        connections = [
            ProviderStoreConnection(
                id=connection_ids["north_printify"],
                organization_id="default-org",
                provider="printify",
                credential_key="printify-default",
                provider_store_id="printify-north",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="North Printify",
                etsy_shop_id="etsy-shop-north",
                status="connected",
                raw_data_json={"sales_channel": "etsy"},
                last_synced_at=now - timedelta(hours=6),
            ),
            ProviderStoreConnection(
                id=connection_ids["north_gelato"],
                organization_id="default-org",
                provider="gelato",
                credential_key="gelato-default",
                provider_store_id="gelato-north",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="North Gelato",
                etsy_shop_id="etsy-shop-north",
                status="connected",
                raw_data_json={"sales_channel": "etsy"},
                last_synced_at=now - timedelta(hours=5),
            ),
            ProviderStoreConnection(
                id=connection_ids["south_printify"],
                organization_id="default-org",
                provider="printify",
                credential_key="printify-default",
                provider_store_id="printify-south",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="South Printify",
                etsy_shop_id="etsy-shop-south",
                status="connected",
                raw_data_json={"sales_channel": "etsy"},
                last_synced_at=now - timedelta(hours=4),
            ),
            ProviderStoreConnection(
                id=connection_ids["shopify"],
                organization_id="default-org",
                provider="printify",
                credential_key="printify-default",
                provider_store_id="printify-shopify",
                storefront_type="shopify",
                storefront_display_name="Shopify",
                label="Main Shopify",
                status="connected",
                raw_data_json={"sales_channel": "shopify"},
                last_synced_at=now - timedelta(hours=3),
            ),
        ]
        db.add_all(connections)

        design_asset = DesignAsset(
            id="asset-analytics",
            organization_id="default-org",
            file_name="analytics.png",
            content_type="image/png",
            size_bytes=1024,
            storage_key="organizations/default-org/design-assets/asset-analytics/source.png",
            public_url="https://storage.test/asset-analytics.png",
        )
        db.add(design_asset)

        blueprints = [
            ProductBlueprint(
                id=blueprint_ids["north_printify"],
                organization_id="default-org",
                provider="printify",
                provider_store_connection_id=connection_ids["north_printify"],
                name="North Poster",
                category="Wall Art",
                status="active",
                reference_type="printify_product_url",
                reference_value="north-template",
            ),
            ProductBlueprint(
                id=blueprint_ids["north_gelato"],
                organization_id="default-org",
                provider="gelato",
                provider_store_connection_id=connection_ids["north_gelato"],
                name="North Gelato Poster",
                category="Wall Art",
                status="active",
                reference_type="gelato_template_id",
                reference_value="north-gelato-template",
            ),
            ProductBlueprint(
                id=blueprint_ids["south_printify"],
                organization_id="default-org",
                provider="printify",
                provider_store_connection_id=connection_ids["south_printify"],
                name="South Poster",
                category="Wall Art",
                status="active",
                reference_type="printify_product_url",
                reference_value="south-template",
            ),
            ProductBlueprint(
                id=blueprint_ids["shopify"],
                organization_id="default-org",
                provider="printify",
                provider_store_connection_id=connection_ids["shopify"],
                name="Shopify Poster",
                category="Wall Art",
                status="active",
                reference_type="printify_product_url",
                reference_value="shopify-template",
            ),
        ]
        db.add_all(blueprints)

        drafts = [
            ProviderProductDraft(
                id=draft_ids["needs_work"],
                organization_id="default-org",
                blueprint_id=blueprint_ids["north_printify"],
                provider="printify",
                provider_store_connection_id=connection_ids["north_printify"],
                design_asset_id=design_asset.id,
                status="draft",
                validation_status="pending",
                publishing_status="not_started",
                title="North draft",
                description=None,
                tags_json=["one", "two"],
                retail_price=None,
                currency="USD",
                sku=None,
                created_at=now - timedelta(days=10),
                updated_at=now - timedelta(days=10),
            ),
            ProviderProductDraft(
                id=draft_ids["retry"],
                organization_id="default-org",
                blueprint_id=blueprint_ids["shopify"],
                provider="printify",
                provider_store_connection_id=connection_ids["shopify"],
                design_asset_id=design_asset.id,
                status="ready",
                validation_status="validated",
                publishing_status="failed",
                title="Shopify retry",
                description="Ready to resend",
                tags_json=["poster", "wall", "decor", "gift", "art", "color"],
                retail_price=Decimal("25.00"),
                currency="USD",
                sku="SHOP-RETRY-1",
                created_at=now - timedelta(days=4),
                updated_at=now - timedelta(days=1),
            ),
            ProviderProductDraft(
                id=draft_ids["north_live"],
                organization_id="default-org",
                blueprint_id=blueprint_ids["north_gelato"],
                provider="gelato",
                provider_store_connection_id=connection_ids["north_gelato"],
                design_asset_id=design_asset.id,
                status="published",
                validation_status="validated",
                publishing_status="succeeded",
                title="North live",
                description="Live listing",
                tags_json=["poster", "wall", "decor", "gift", "art"],
                retail_price=Decimal("30.00"),
                currency="USD",
                sku="NORTH-LIVE-1",
                external_listing_id="etsy-listing-north",
                created_at=now - timedelta(days=20),
                updated_at=now - timedelta(days=2),
            ),
            ProviderProductDraft(
                id=draft_ids["south_live"],
                organization_id="default-org",
                blueprint_id=blueprint_ids["south_printify"],
                provider="printify",
                provider_store_connection_id=connection_ids["south_printify"],
                design_asset_id=design_asset.id,
                status="published",
                validation_status="validated",
                publishing_status="succeeded",
                title="South live",
                description="Published listing",
                tags_json=["poster", "gift", "decor", "art"],
                retail_price=Decimal("28.00"),
                currency="USD",
                sku="SOUTH-LIVE-1",
                external_listing_id="etsy-listing-south",
                created_at=now - timedelta(days=40),
                updated_at=now - timedelta(days=6),
            ),
        ]
        db.add_all(drafts)

        db.add_all(
            [
                Mockup(
                    id="mockup-retry",
                    organization_id="default-org",
                    provider_product_draft_id=draft_ids["retry"],
                    file_name="retry.jpg",
                    content_type="image/jpeg",
                    size_bytes=128,
                    storage_key="organizations/default-org/draft-mockups/draft-retry/mockup-retry/source.jpg",
                    public_url="https://storage.test/retry.jpg",
                    position=0,
                ),
                Mockup(
                    id="mockup-north",
                    organization_id="default-org",
                    provider_product_draft_id=draft_ids["north_live"],
                    file_name="north.jpg",
                    content_type="image/jpeg",
                    size_bytes=128,
                    storage_key="organizations/default-org/draft-mockups/draft-north-live/mockup-north/source.jpg",
                    public_url="https://storage.test/north.jpg",
                    position=0,
                ),
                Mockup(
                    id="mockup-south",
                    organization_id="default-org",
                    provider_product_draft_id=draft_ids["south_live"],
                    file_name="south.jpg",
                    content_type="image/jpeg",
                    size_bytes=128,
                    storage_key="organizations/default-org/draft-mockups/draft-south-live/mockup-south/source.jpg",
                    public_url="https://storage.test/south.jpg",
                    position=0,
                ),
            ]
        )

        db.add_all(
            [
                Order(
                    id="order-north-1",
                    organization_id="default-org",
                    provider_store_connection_id=connection_ids["north_printify"],
                    provider="printify",
                    external_order_id="north-1",
                    display_order_id="#1001",
                    fulfillment_status="processing",
                    currency="USD",
                    total_amount=Decimal("36.00"),
                    retail_amount=Decimal("40.00"),
                    order_created_at=now - timedelta(days=5),
                ),
                Order(
                    id="order-north-2",
                    organization_id="default-org",
                    provider_store_connection_id=connection_ids["north_gelato"],
                    provider="gelato",
                    external_order_id="north-2",
                    display_order_id="#1002",
                    fulfillment_status="processing",
                    currency="USD",
                    total_amount=Decimal("18.00"),
                    retail_amount=None,
                    order_created_at=now - timedelta(days=20),
                ),
                Order(
                    id="order-shopify-1",
                    organization_id="default-org",
                    provider_store_connection_id=connection_ids["shopify"],
                    provider="printify",
                    external_order_id="shopify-1",
                    display_order_id="#1003",
                    fulfillment_status="processing",
                    currency="USD",
                    total_amount=Decimal("47.00"),
                    retail_amount=Decimal("50.00"),
                    order_created_at=now - timedelta(days=2),
                ),
                Order(
                    id="order-south-older",
                    organization_id="default-org",
                    provider_store_connection_id=connection_ids["south_printify"],
                    provider="printify",
                    external_order_id="south-older",
                    display_order_id="#0999",
                    fulfillment_status="delivered",
                    currency="USD",
                    total_amount=Decimal("15.00"),
                    retail_amount=Decimal("18.00"),
                    order_created_at=now - timedelta(days=40),
                ),
            ]
        )

        db.add_all(
            [
                DBSyncJob(
                    id="sync-job-pending",
                    organization_id="default-org",
                    provider="printify",
                    job_type="product_publish",
                    scope_key="analytics-pending",
                    status="queued",
                    attempt_count=0,
                    max_attempts=3,
                    available_at=now - timedelta(hours=2),
                ),
                DBSyncJob(
                    id="sync-job-running",
                    organization_id="default-org",
                    provider="printify",
                    job_type="product_publish",
                    scope_key="analytics-running",
                    status="running",
                    lease_owner="analytics-worker",
                    lease_expires_at=now + timedelta(minutes=5),
                    heartbeat_at=now,
                    attempt_count=1,
                    max_attempts=3,
                    available_at=now - timedelta(minutes=30),
                    started_at=now - timedelta(minutes=25),
                ),
                DBSyncJob(
                    id="sync-job-success",
                    organization_id="default-org",
                    provider="gelato",
                    job_type="product_publish",
                    scope_key="analytics-success",
                    status="completed",
                    attempt_count=1,
                    max_attempts=3,
                    available_at=now - timedelta(days=3, minutes=25),
                    started_at=now - timedelta(days=3, minutes=20),
                    completed_at=now - timedelta(days=3),
                ),
                DBSyncJob(
                    id="sync-job-failed",
                    organization_id="default-org",
                    provider="printify",
                    job_type="product_publish",
                    scope_key="analytics-failed",
                    status="failed",
                    attempt_count=2,
                    max_attempts=3,
                    available_at=now - timedelta(days=1, minutes=10),
                    started_at=now - timedelta(days=1, minutes=5),
                    completed_at=now - timedelta(days=1),
                ),
            ]
        )

        db.add_all(
            [
                PublishingJob(
                    id="job-pending",
                    organization_id="default-org",
                    blueprint_id=blueprint_ids["north_printify"],
                    provider_product_draft_id=draft_ids["needs_work"],
                    provider="printify",
                    provider_store_connection_id=connection_ids["north_printify"],
                    sync_job_id="sync-job-pending",
                    operation="create",
                    product_revision=1,
                    idempotency_key="analytics-pending",
                    submitted_snapshot_json={"provider_input": {}},
                    status="queued",
                    retry_count=0,
                    created_at=now - timedelta(hours=2),
                    updated_at=now - timedelta(hours=2),
                ),
                PublishingJob(
                    id="job-running",
                    organization_id="default-org",
                    blueprint_id=blueprint_ids["south_printify"],
                    provider_product_draft_id=draft_ids["south_live"],
                    provider="printify",
                    provider_store_connection_id=connection_ids["south_printify"],
                    sync_job_id="sync-job-running",
                    operation="update",
                    product_revision=1,
                    idempotency_key="analytics-running",
                    submitted_snapshot_json={"provider_input": {}},
                    status="running",
                    retry_count=0,
                    started_at=now - timedelta(minutes=25),
                    created_at=now - timedelta(minutes=30),
                    updated_at=now - timedelta(minutes=25),
                ),
                PublishingJob(
                    id="job-success",
                    organization_id="default-org",
                    blueprint_id=blueprint_ids["north_gelato"],
                    provider_product_draft_id=draft_ids["north_live"],
                    provider="gelato",
                    provider_store_connection_id=connection_ids["north_gelato"],
                    sync_job_id="sync-job-success",
                    operation="create",
                    product_revision=1,
                    idempotency_key="analytics-success",
                    submitted_snapshot_json={"provider_input": {}},
                    status="succeeded",
                    retry_count=0,
                    started_at=now - timedelta(days=3, minutes=20),
                    completed_at=now - timedelta(days=3),
                    created_at=now - timedelta(days=3, minutes=25),
                    updated_at=now - timedelta(days=3),
                ),
                PublishingJob(
                    id="job-failed",
                    organization_id="default-org",
                    blueprint_id=blueprint_ids["shopify"],
                    provider_product_draft_id=draft_ids["retry"],
                    provider="printify",
                    provider_store_connection_id=connection_ids["shopify"],
                    sync_job_id="sync-job-failed",
                    operation="create",
                    product_revision=1,
                    idempotency_key="analytics-failed",
                    submitted_snapshot_json={"provider_input": {}},
                    status="failed",
                    retry_count=1,
                    error_message=(
                        "Provider rejected the payload because the storefront variant mapping "
                        "was stale and needs a fresh sync before retrying."
                    ),
                    started_at=now - timedelta(days=1, minutes=5),
                    completed_at=now - timedelta(days=1),
                    created_at=now - timedelta(days=1, minutes=10),
                    updated_at=now - timedelta(days=1),
                ),
            ]
        )

        db.commit()

    return {
        "connection_ids": connection_ids,
        "draft_ids": draft_ids,
        "now": now,
    }


def _refresh_workspace_analytics_snapshot(client, *, now: datetime) -> None:
    with client.app.state.testing_session_local() as db:
        result = refresh_etsy_analytics_snapshot(
            db,
            organization_id="default-org",
            now=now,
        )
    assert result.outcome == "completed"


def test_business_analytics_route_and_admin_ledger_mapping_actions(client) -> None:
    now = datetime.now(timezone.utc)
    fixture = _seed_workspace_analytics_fixture(
        client,
        now=now,
        include_etsy_connection=True,
    )
    with client.app.state.testing_session_local() as db:
        db.add(
            OrderLineItem(
                id="line-unmatched-analytics",
                organization_id="default-org",
                order_id="order-north-1",
                external_line_id="provider-line-1",
                external_listing_id="etsy-listing-north",
                sku="NORTH-LIVE-1",
                title="North live poster",
                quantity=1,
                currency="USD",
                revenue_amount=Decimal("40.00"),
                production_cost_amount=Decimal("18.00"),
                mapping_status="unmatched",
            )
        )
        db.commit()

    response = client.get(
        "/analytics/business",
        params={
            "preset": "30d",
            "currency": "USD",
            "timezone": "Asia/Manila",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["currency"] == "USD"
    assert payload["timezone"] == "Asia/Manila"
    assert payload["trend_granularity"] == "day"
    assert payload["summary"]["order_count"] == 3
    assert payload["summary"]["revenue"]["amount"] == 108.0
    assert payload["summary"]["unmatched_line_count"] == 1
    assert payload["capabilities"]["detailed_marketplace_finance"] is True
    assert payload["products"]
    assert payload["seo"]
    assert payload["stores"]
    assert payload["unmatched_lines"][0]["id"] == "line-unmatched-analytics"

    weekly_response = client.get(
        "/analytics/business",
        params={"preset": "90d", "currency": "USD", "timezone": "Asia/Manila"},
    )
    assert weekly_response.status_code == 200
    assert weekly_response.json()["trend_granularity"] == "week"

    expense_response = client.post(
        "/analytics/expenses",
        json={
            "incurred_on": now.isoformat(),
            "category": "Advertising",
            "amount": 25.5,
            "currency": "USD",
            "provider_store_connection_id": fixture["connection_ids"]["north_printify"],
            "note": "Campaign",
        },
    )
    assert expense_response.status_code == 201
    expense_id = expense_response.json()["id"]

    mapping_response = client.post(
        "/analytics/unmatched/line-unmatched-analytics/map",
        json={"product_id": fixture["draft_ids"]["north_live"]},
    )
    assert mapping_response.status_code == 204

    with client.app.state.testing_session_local() as db:
        expense = db.get(Expense, expense_id)
        line = db.get(OrderLineItem, "line-unmatched-analytics")
        assert expense is not None
        assert expense.category == "advertising"
        assert line is not None
        assert line.product_id == fixture["draft_ids"]["north_live"]
        assert line.mapping_status == "manual"

    delete_response = client.delete(f"/analytics/expenses/{expense_id}")
    assert delete_response.status_code == 204


def test_business_analytics_details_are_server_paginated(client) -> None:
    now = datetime.now(timezone.utc)
    _seed_workspace_analytics_fixture(
        client,
        now=now,
        include_etsy_connection=True,
    )
    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                Expense(
                    id=f"paged-expense-{index:02d}",
                    organization_id="default-org",
                    incurred_on=now - timedelta(minutes=index),
                    category="operating",
                    amount=Decimal("1.00"),
                    currency="USD",
                    source="manual",
                    note=f"Paged expense {index:02d}",
                )
                for index in range(26)
            ]
        )
        db.commit()

    summary_response = client.get(
        "/analytics/business",
        params={
            "preset": "30d",
            "currency": "USD",
            "timezone": "Asia/Manila",
            "include_details": "false",
        },
    )
    assert summary_response.status_code == 200
    assert summary_response.json()["expenses"] == []
    assert summary_response.json()["seo"] == []
    assert summary_response.json()["unmatched_lines"] == []

    first_page = client.get(
        "/analytics/business/details",
        params={
            "resource": "expenses",
            "preset": "30d",
            "currency": "USD",
            "timezone": "Asia/Manila",
            "page": 1,
            "page_size": 10,
        },
    )
    second_page = client.get(
        "/analytics/business/details",
        params={
            "resource": "expenses",
            "preset": "30d",
            "currency": "USD",
            "timezone": "Asia/Manila",
            "page": 2,
            "page_size": 10,
        },
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["page"] == 1
    assert first_page.json()["page_size"] == 10
    assert first_page.json()["total"] >= 26
    assert len(first_page.json()["items"]) == 10
    assert len(second_page.json()["items"]) == 10
    assert {
        item["id"] for item in first_page.json()["items"]
    }.isdisjoint({item["id"] for item in second_page.json()["items"]})


def test_analytics_route_returns_workspace_sections_without_etsy_connection(client_without_etsy) -> None:
    now = datetime.now(timezone.utc)
    fixture = _seed_workspace_analytics_fixture(
        client_without_etsy,
        now=now,
        include_etsy_connection=False,
    )

    response = client_without_etsy.get("/analytics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == {
        "store_connection_id": None,
        "label": "All stores",
        "provider": None,
        "storefront_type": None,
        "is_all_stores": True,
    }
    assert payload["overview"] == {
        "published_product_count": 2,
        "active_etsy_listing_count": 0,
        "orders_last_30_days": 3,
        "publish_success_rate_last_30_days": 50.0,
        "publish_success_count_last_30_days": 1,
        "publish_settled_count_last_30_days": 2,
        "listings_needing_attention_count": 3,
    }
    assert payload["catalog_health"]["status_counts"] == {
        "draft_count": 1,
        "ready_count": 1,
        "published_count": 2,
        "failed_publish_count": 1,
    }
    assert payload["catalog_health"]["issue_counts"] == {
        "missing_description_count": 1,
        "low_tag_count_count": 2,
        "missing_retail_price_count": 1,
        "missing_sku_count": 1,
        "zero_mockups_count": 1,
    }
    assert payload["catalog_health"]["needs_attention"][0] == {
        "product_id": fixture["draft_ids"]["needs_work"],
        "title": "North draft",
        "provider_store_label": "North Printify",
        "status": "draft",
        "publishing_status": "not_started",
        "issue_count": 5,
        "issues": [
            "Missing description",
            "Fewer than 5 tags",
            "Missing retail price",
            "Missing SKU",
            "No mockups",
        ],
        "updated_at": payload["catalog_health"]["needs_attention"][0]["updated_at"],
    }
    assert payload["recent_activity"] == {
        "orders_last_7_days": 2,
        "orders_last_30_days": 3,
        "revenue_last_30_days": 108.0,
        "revenue_currency": "USD",
        "revenue_is_mixed_currency": False,
        "new_drafts_last_30_days": 3,
        "successful_publishes_last_30_days": 1,
    }
    assert payload["workflow_health"]["queued_job_count"] == 1
    assert payload["workflow_health"]["in_progress_job_count"] == 1
    assert payload["workflow_health"]["failed_job_count_last_30_days"] == 1
    assert payload["workflow_health"]["average_publish_duration_seconds"] == 750.0
    assert payload["workflow_health"]["latest_failure"]["product_id"] == fixture["draft_ids"]["retry"]
    assert payload["workflow_health"]["latest_failure"]["provider_store_label"] == "Main Shopify"
    assert payload["etsy_snapshot"] == {
        "available": False,
        "unavailable_reason": "Connect Etsy in Settings to unlock market analytics.",
        "is_connected": False,
        "connected_account_count": 0,
        "supports_detailed_receipts": False,
        "connected_shop_count": 0,
        "mapped_store_count": 0,
        "lifetime_sales_count": 0,
        "active_listing_count": 0,
        "digital_listing_count": 0,
        "favorite_count": 0,
        "review_count": 0,
        "review_average": None,
        "vacation_shop_count": 0,
        "payments_onboarding_issue_count": 0,
        "freshness": "missing",
        "refresh_status": "missing",
        "fetched_at": None,
        "expires_at": None,
        "last_refresh_attempted_at": None,
    }
    assert payload["store_rollup"] == []
    assert payload["warnings"] == []
    assert payload["generated_at"]


def test_analytics_route_returns_all_store_workspace_metrics(client, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    _seed_workspace_analytics_fixture(client, now=now, include_etsy_connection=True)

    monkeypatch.setattr(commerce, "_refresh_access_token", lambda refresh_token_override=None: "fixture-access-token")

    def fake_fetch_etsy_shop(*, access_token: str, shop_id: str) -> dict[str, object]:
        assert access_token == "fixture-access-token"
        if shop_id == "etsy-shop-north":
            return {
                "shop_id": "etsy-shop-north",
                "shop_name": "North Shop",
                "shop_url": "https://www.etsy.com/shop/NorthShop",
                "currency_code": "USD",
                "listing_active_count": 46,
                "digital_listing_count": 6,
                "num_favorers": 912,
                "transaction_sold_count": 284,
                "review_count": 128,
                "review_average": 4.8,
                "is_vacation": False,
                "is_etsy_payments_onboarded": True,
                "updated_timestamp": int((now - timedelta(hours=1)).timestamp()),
            }
        if shop_id == "etsy-shop-south":
            return {
                "shop_id": "etsy-shop-south",
                "shop_name": "South Shop",
                "shop_url": "https://www.etsy.com/shop/SouthShop",
                "currency_code": "USD",
                "listing_active_count": 12,
                "digital_listing_count": 2,
                "num_favorers": 120,
                "transaction_sold_count": 44,
                "review_count": 20,
                "review_average": 4.5,
                "is_vacation": True,
                "is_etsy_payments_onboarded": False,
                "updated_timestamp": int((now - timedelta(hours=2)).timestamp()),
            }
        raise AssertionError(shop_id)

    monkeypatch.setattr(commerce, "fetch_etsy_shop", fake_fetch_etsy_shop)
    _refresh_workspace_analytics_snapshot(client, now=now)
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda **_kwargs: pytest.fail("Analytics GET must not call Etsy."),
    )

    response = client.get("/analytics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overview"] == {
        "published_product_count": 2,
        "active_etsy_listing_count": 58,
        "orders_last_30_days": 3,
        "publish_success_rate_last_30_days": 50.0,
        "publish_success_count_last_30_days": 1,
        "publish_settled_count_last_30_days": 2,
        "listings_needing_attention_count": 3,
    }
    assert payload["recent_activity"]["revenue_last_30_days"] == 108.0
    assert payload["catalog_health"]["issue_counts"]["low_tag_count_count"] == 2
    assert payload["workflow_health"]["latest_etsy_fetch_at"]
    assert payload["etsy_snapshot"] == {
        "available": True,
        "unavailable_reason": None,
        "is_connected": True,
        "connected_account_count": 1,
        "supports_detailed_receipts": True,
        "connected_shop_count": 2,
        "mapped_store_count": 3,
        "lifetime_sales_count": 328,
        "active_listing_count": 58,
        "digital_listing_count": 8,
        "favorite_count": 1032,
        "review_count": 148,
        "review_average": 4.76,
        "vacation_shop_count": 1,
        "payments_onboarding_issue_count": 1,
        "freshness": "fresh",
        "refresh_status": "succeeded",
        "fetched_at": payload["etsy_snapshot"]["fetched_at"],
        "expires_at": payload["etsy_snapshot"]["expires_at"],
        "last_refresh_attempted_at": payload["etsy_snapshot"]["last_refresh_attempted_at"],
    }
    assert payload["warnings"] == []
    assert payload["store_rollup"] == [
        {
            "shop_id": "etsy-shop-north",
            "shop_name": "North Shop",
            "shop_url": "https://www.etsy.com/shop/NorthShop",
            "currency_code": "USD",
            "lifetime_sales_count": 284,
            "active_listing_count": 46,
            "digital_listing_count": 6,
            "favorite_count": 912,
            "review_count": 128,
                "review_average": 4.8,
                "is_vacation": False,
                "has_payments_onboarding_issue": False,
                "updated_at": payload["store_rollup"][0]["updated_at"],
                "last_synced_at": payload["store_rollup"][0]["last_synced_at"],
                "matched_connection_ids": ["conn-north-gelato", "conn-north-printify"],
                "matched_connection_labels": ["North Gelato", "North Printify"],
            },
        {
            "shop_id": "etsy-shop-south",
            "shop_name": "South Shop",
            "shop_url": "https://www.etsy.com/shop/SouthShop",
            "currency_code": "USD",
            "lifetime_sales_count": 44,
            "active_listing_count": 12,
            "digital_listing_count": 2,
            "favorite_count": 120,
            "review_count": 20,
            "review_average": 4.5,
            "is_vacation": True,
            "has_payments_onboarding_issue": True,
            "updated_at": payload["store_rollup"][1]["updated_at"],
            "last_synced_at": payload["store_rollup"][1]["last_synced_at"],
            "matched_connection_ids": ["conn-south-printify"],
            "matched_connection_labels": ["South Printify"],
        }
    ]
    assert payload["generated_at"]


def test_analytics_route_scopes_to_one_etsy_store(client, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fixture = _seed_workspace_analytics_fixture(client, now=now, include_etsy_connection=True)

    monkeypatch.setattr(commerce, "_refresh_access_token", lambda refresh_token_override=None: "fixture-access-token")
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda *, access_token, shop_id: {
            "shop_id": shop_id,
            "shop_name": "North Shop" if shop_id == "etsy-shop-north" else "South Shop",
            "shop_url": f"https://www.etsy.com/shop/{'NorthShop' if shop_id == 'etsy-shop-north' else 'SouthShop'}",
            "currency_code": "USD",
            "listing_active_count": 46 if shop_id == "etsy-shop-north" else 12,
            "digital_listing_count": 6 if shop_id == "etsy-shop-north" else 2,
            "num_favorers": 912 if shop_id == "etsy-shop-north" else 120,
            "transaction_sold_count": 284 if shop_id == "etsy-shop-north" else 44,
            "review_count": 128 if shop_id == "etsy-shop-north" else 20,
            "review_average": 4.8 if shop_id == "etsy-shop-north" else 4.5,
            "is_vacation": False if shop_id == "etsy-shop-north" else True,
            "is_etsy_payments_onboarded": True if shop_id == "etsy-shop-north" else False,
            "updated_timestamp": int(now.timestamp()),
        },
    )
    _refresh_workspace_analytics_snapshot(client, now=now)
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda **_kwargs: pytest.fail("Analytics GET must not call Etsy."),
    )

    response = client.get(
        f"/analytics?store_connection_id={fixture['connection_ids']['north_printify']}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == {
        "store_connection_id": fixture["connection_ids"]["north_printify"],
        "label": "North Printify",
        "provider": "printify",
        "storefront_type": "etsy",
        "is_all_stores": False,
    }
    assert payload["overview"] == {
        "published_product_count": 0,
        "active_etsy_listing_count": 46,
        "orders_last_30_days": 1,
        "publish_success_rate_last_30_days": None,
        "publish_success_count_last_30_days": 0,
        "publish_settled_count_last_30_days": 0,
        "listings_needing_attention_count": 1,
    }
    assert payload["catalog_health"]["status_counts"] == {
        "draft_count": 1,
        "ready_count": 0,
        "published_count": 0,
        "failed_publish_count": 0,
    }
    assert payload["recent_activity"] == {
        "orders_last_7_days": 1,
        "orders_last_30_days": 1,
        "revenue_last_30_days": 40.0,
        "revenue_currency": "USD",
        "revenue_is_mixed_currency": False,
        "new_drafts_last_30_days": 1,
        "successful_publishes_last_30_days": 0,
    }
    assert payload["etsy_snapshot"]["available"] is True
    assert payload["etsy_snapshot"]["connected_shop_count"] == 1
    assert len(payload["store_rollup"]) == 1
    assert payload["store_rollup"][0]["shop_id"] == "etsy-shop-north"


def test_analytics_route_keeps_internal_panels_for_non_etsy_store_scope(client, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fixture = _seed_workspace_analytics_fixture(client, now=now, include_etsy_connection=True)

    monkeypatch.setattr(commerce, "_refresh_access_token", lambda refresh_token_override=None: "fixture-access-token")
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda *, access_token, shop_id: {
            "shop_id": shop_id,
            "shop_name": "North Shop" if shop_id == "etsy-shop-north" else "South Shop",
            "shop_url": f"https://www.etsy.com/shop/{'NorthShop' if shop_id == 'etsy-shop-north' else 'SouthShop'}",
            "currency_code": "USD",
            "listing_active_count": 46 if shop_id == "etsy-shop-north" else 12,
            "digital_listing_count": 6 if shop_id == "etsy-shop-north" else 2,
            "num_favorers": 912 if shop_id == "etsy-shop-north" else 120,
            "transaction_sold_count": 284 if shop_id == "etsy-shop-north" else 44,
            "review_count": 128 if shop_id == "etsy-shop-north" else 20,
            "review_average": 4.8 if shop_id == "etsy-shop-north" else 4.5,
            "is_vacation": False if shop_id == "etsy-shop-north" else True,
            "is_etsy_payments_onboarded": True if shop_id == "etsy-shop-north" else False,
            "updated_timestamp": int(now.timestamp()),
        },
    )
    _refresh_workspace_analytics_snapshot(client, now=now)

    response = client.get(f"/analytics?store_connection_id={fixture['connection_ids']['shopify']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overview"] == {
        "published_product_count": 0,
        "active_etsy_listing_count": 0,
        "orders_last_30_days": 1,
        "publish_success_rate_last_30_days": 0.0,
        "publish_success_count_last_30_days": 0,
        "publish_settled_count_last_30_days": 1,
        "listings_needing_attention_count": 1,
    }
    assert payload["catalog_health"]["status_counts"] == {
        "draft_count": 0,
        "ready_count": 1,
        "published_count": 0,
        "failed_publish_count": 1,
    }
    assert payload["etsy_snapshot"] == {
        "available": False,
        "unavailable_reason": "Main Shopify is not mapped to a discovered Etsy shop.",
        "is_connected": True,
        "connected_account_count": 1,
        "supports_detailed_receipts": True,
        "connected_shop_count": 0,
        "mapped_store_count": 0,
        "lifetime_sales_count": 0,
        "active_listing_count": 0,
        "digital_listing_count": 0,
        "favorite_count": 0,
        "review_count": 0,
        "review_average": None,
        "vacation_shop_count": 0,
        "payments_onboarding_issue_count": 0,
        "freshness": "fresh",
        "refresh_status": "succeeded",
        "fetched_at": payload["etsy_snapshot"]["fetched_at"],
        "expires_at": payload["etsy_snapshot"]["expires_at"],
        "last_refresh_attempted_at": payload["etsy_snapshot"]["last_refresh_attempted_at"],
    }
    assert payload["store_rollup"] == []


def test_analytics_route_keeps_partial_etsy_warnings_without_failing(client, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    _seed_workspace_analytics_fixture(client, now=now, include_etsy_connection=True)

    monkeypatch.setattr(commerce, "_refresh_access_token", lambda refresh_token_override=None: "fixture-access-token")
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda *, access_token, shop_id: {
            "shop_id": shop_id,
            "shop_name": "North Shop" if shop_id == "etsy-shop-north" else "South Shop",
            "shop_url": f"https://www.etsy.com/shop/{shop_id}",
            "currency_code": "USD",
            "listing_active_count": 46 if shop_id == "etsy-shop-north" else 12,
            "digital_listing_count": 6 if shop_id == "etsy-shop-north" else 2,
            "num_favorers": 912 if shop_id == "etsy-shop-north" else 120,
            "transaction_sold_count": 284 if shop_id == "etsy-shop-north" else 44,
            "review_count": 128 if shop_id == "etsy-shop-north" else 20,
            "review_average": 4.8 if shop_id == "etsy-shop-north" else 4.5,
            "is_vacation": False,
            "is_etsy_payments_onboarded": True,
            "updated_timestamp": int(now.timestamp()),
        },
    )
    _refresh_workspace_analytics_snapshot(client, now=now - timedelta(minutes=10))

    with client.app.state.testing_session_local() as db:
        scoped_rows = db.scalars(
            select(ProviderCredential).where(
                ProviderCredential.organization_id == "default-org",
                ProviderCredential.provider == "etsy",
                ProviderCredential.key_name == "oauth_shops_json",
            )
        ).all()
        scoped_rows[0].encrypted_value = encrypt_value(
            json.dumps(
                [
                    {
                        "shop_id": "etsy-shop-north",
                        "shop_name": "North Shop",
                        "shop_url": "https://www.etsy.com/shop/NorthShop",
                    },
                    {
                        "shop_id": "etsy-shop-missing",
                        "shop_name": "Missing Shop",
                        "shop_url": "https://www.etsy.com/shop/MissingShop",
                    },
                ],
                separators=(",", ":"),
            )
        )
        db.commit()

    def fake_fetch_with_warning(*, access_token: str, shop_id: str) -> dict[str, object]:
        if shop_id == "etsy-shop-missing":
            raise commerce.HTTPException(status_code=502, detail="Etsy returned malformed shop metrics.")
        return {
            "shop_id": "etsy-shop-north",
            "shop_name": "North Shop",
            "shop_url": "https://www.etsy.com/shop/NorthShop",
            "currency_code": "USD",
            "listing_active_count": 46,
            "digital_listing_count": 6,
            "num_favorers": 912,
            "transaction_sold_count": 284,
            "review_count": 128,
            "review_average": 4.8,
            "is_vacation": False,
            "is_etsy_payments_onboarded": True,
            "updated_timestamp": int(now.timestamp()),
        }

    monkeypatch.setattr(commerce, "fetch_etsy_shop", fake_fetch_with_warning)

    with client.app.state.testing_session_local() as db:
        result = refresh_etsy_analytics_snapshot(
            db,
            organization_id="default-org",
            now=now,
        )
    assert result.outcome == "partial"
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda **_kwargs: pytest.fail("Analytics GET must not call Etsy."),
    )

    response = client.get("/analytics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["warnings"] == [
        "Etsy analytics refresh failed for 1 shop; serving the last successful snapshot."
    ]
    assert len(payload["store_rollup"]) == 2
    assert payload["etsy_snapshot"]["connected_shop_count"] == 2
    assert payload["etsy_snapshot"]["refresh_status"] == "failed"
    assert payload["etsy_snapshot"]["freshness"] == "fresh"


def test_analytics_route_query_count_and_latency_do_not_grow_with_order_history(client, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    fixture = _seed_workspace_analytics_fixture(client, now=now, include_etsy_connection=True)
    monkeypatch.setattr(commerce, "_refresh_access_token", lambda refresh_token_override=None: "fixture-access-token")
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda *, access_token, shop_id: {
            "shop_id": shop_id,
            "shop_name": shop_id,
            "listing_active_count": 1,
            "transaction_sold_count": 1,
            "updated_timestamp": int(now.timestamp()),
        },
    )
    _refresh_workspace_analytics_snapshot(client, now=now)
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda **_kwargs: pytest.fail("Analytics GET must not call Etsy."),
    )

    with client.app.state.testing_session_local() as db:
        engine = db.get_bind()

    warmup_response = client.get("/analytics")
    assert warmup_response.status_code == 200

    def measured_request() -> tuple[int, float]:
        statement_count = 0

        def count_statement(*_args) -> None:
            nonlocal statement_count
            statement_count += 1

        event.listen(engine, "before_cursor_execute", count_statement)
        started_at = perf_counter()
        try:
            response = client.get("/analytics")
        finally:
            elapsed = perf_counter() - started_at
            event.remove(engine, "before_cursor_execute", count_statement)
        assert response.status_code == 200
        return statement_count, elapsed

    baseline_query_count, baseline_elapsed = measured_request()
    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                Order(
                    id=f"historical-order-{index}",
                    organization_id="default-org",
                    provider_store_connection_id=fixture["connection_ids"]["north_printify"],
                    provider="printify",
                    external_order_id=f"historical-{index}",
                    display_order_id=f"#H{index}",
                    fulfillment_status="delivered",
                    currency="USD",
                    total_amount=Decimal("10.00"),
                    order_created_at=now - timedelta(days=90),
                )
                for index in range(250)
            ]
        )
        db.commit()

    expanded_query_count, expanded_elapsed = measured_request()

    assert baseline_query_count == expanded_query_count
    assert expanded_query_count <= 15
    assert baseline_elapsed < 2
    assert expanded_elapsed < 2


def test_analytics_route_serves_stale_snapshot_with_freshness_warning(client, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    _seed_workspace_analytics_fixture(client, now=now, include_etsy_connection=True)
    monkeypatch.setattr(commerce, "_refresh_access_token", lambda refresh_token_override=None: "fixture-access-token")
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda *, access_token, shop_id: {
            "shop_id": shop_id,
            "shop_name": shop_id,
            "listing_active_count": 5,
            "transaction_sold_count": 9,
            "updated_timestamp": int(now.timestamp()),
        },
    )
    _refresh_workspace_analytics_snapshot(client, now=now - timedelta(hours=2))
    with client.app.state.testing_session_local() as db:
        snapshot = db.scalar(select(AnalyticsSnapshot))
        assert snapshot is not None
        snapshot.expires_at = now - timedelta(hours=1)
        db.commit()
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda **_kwargs: pytest.fail("Analytics GET must not call Etsy."),
    )

    response = client.get("/analytics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["etsy_snapshot"]["available"] is True
    assert payload["etsy_snapshot"]["freshness"] == "stale"
    assert payload["warnings"] == [
        "Etsy market metrics are stale while a background refresh is pending."
    ]


def test_provider_credentials_require_etsy_connection_first(client_without_etsy) -> None:
    response = client_without_etsy.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert response.status_code == 409
    assert "Connect Etsy first" in response.json()["detail"]


def test_provider_store_sync_requires_etsy_connection_first(client_without_etsy) -> None:
    response = client_without_etsy.post("/provider-store-connections/sync/printify")
    assert response.status_code == 409
    assert "Connect Etsy first" in response.json()["detail"]


def test_start_etsy_oauth_route_returns_authorization_url(client, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_build_etsy_oauth_authorization(
        *,
        actor_id: str,
        organization_id: str,
        expected_seller_user_id: str | None = None,
    ) -> dict[str, object]:
        captured["actor_id"] = actor_id
        captured["organization_id"] = organization_id
        captured["expected_seller_user_id"] = expected_seller_user_id
        return {
            "authorization_url": "https://www.etsy.com/oauth/connect?state=test-state",
            "state": "test-state",
            "redirect_uri": "https://velora.test/settings/etsy/callback",
            "expires_at": datetime(2026, 6, 13, 10, 30, tzinfo=timezone.utc),
            "scopes": ["shops_r", "listings_r", "listings_w", "transactions_r"],
        }

    monkeypatch.setattr(commerce, "build_etsy_oauth_authorization", fake_build_etsy_oauth_authorization)

    response = client.post("/etsy/oauth/start")
    assert response.status_code == 200
    payload = response.json()
    assert payload["authorization_url"].startswith("https://www.etsy.com/oauth/connect")
    assert payload["state"] == "test-state"
    assert payload["redirect_uri"] == "https://velora.test/settings/etsy/callback"
    assert payload["scopes"] == ["shops_r", "listings_r", "listings_w", "transactions_r"]
    assert captured == {
        "actor_id": "default-user",
        "organization_id": "default-org",
        "expected_seller_user_id": None,
    }


def test_complete_etsy_oauth_connection_route_rejects_reused_start_state(client, monkeypatch) -> None:
    monkeypatch.setattr(etsy.settings, "etsy_api_keystring", "etsy-key")
    monkeypatch.setattr(etsy.settings, "etsy_shared_secret", "etsy-secret")
    monkeypatch.setattr(
        etsy.settings,
        "etsy_oauth_redirect_uri",
        "https://velora.test/settings/etsy/callback",
    )

    token_calls: list[tuple[dict[str, str], str]] = []

    def fake_request_oauth_token(*, data: dict[str, str], action: str) -> dict[str, object]:
        token_calls.append((data, action))
        return {
            "access_token": "12345678.access-token",
            "refresh_token": "oauth-refresh-123",
            "expires_in": 3600,
        }

    monkeypatch.setattr(etsy, "_request_oauth_token", fake_request_oauth_token)
    monkeypatch.setattr(etsy, "fetch_etsy_authenticated_user_id", lambda *, access_token: "12345678")
    monkeypatch.setattr(
        etsy,
        "fetch_etsy_shops",
        lambda *, access_token, user_id: [
            {
                "shop_id": "etsy-shop-445566",
                "shop_name": "Sunset Paper Co",
                "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
            }
        ],
    )

    start_response = client.post("/etsy/oauth/start")
    assert start_response.status_code == 200
    state = start_response.json()["state"]

    first_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-123", "state": state},
    )
    assert first_response.status_code == 200

    reused_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-456", "state": state},
    )
    assert reused_response.status_code == 400
    assert "already used" in reused_response.json()["detail"]
    assert len(token_calls) == 1


def test_complete_etsy_oauth_connection_route_stores_connection_and_auto_maps_shop_ids(
    client,
    monkeypatch,
) -> None:
    credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key-123"},
            "credential_display_name": "Poster partner",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-etsy",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Sunset Paper Co",
                }
            ],
        },
    )
    assert credentials_response.status_code == 200
    credential_key = credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")
    assert sync_response.status_code == 200
    synced_connection = sync_response.json()["connections"][0]
    assert synced_connection["etsy_shop_id"] is None

    def fake_exchange_etsy_authorization_code(**kwargs: object) -> dict[str, object]:
        assert kwargs["code"] == "oauth-code-123"
        assert kwargs["state"] == "oauth-state-123"
        return {
            "refresh_token": "oauth-refresh-123",
            "seller_user_id": "12345678",
            "scopes": ["shops_r", "listings_r", "listings_w"],
            "shops": [
                {
                    "shop_id": "etsy-shop-445566",
                    "shop_name": "Sunset Paper Co",
                    "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
                }
            ],
        }

    monkeypatch.setattr(commerce, "exchange_etsy_authorization_code", fake_exchange_etsy_authorization_code)

    response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-123", "state": "oauth-state-123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_connected"] is True
    assert payload["seller_user_id"] == "12345678"
    assert payload["connected_account_count"] == 1
    assert payload["connected_accounts"] == [
        {
            "credential_key": "12345678",
            "seller_user_id": "12345678",
            "shop_id": "etsy-shop-445566",
            "shop_name": "Sunset Paper Co",
            "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
            "last_synced_at": payload["connected_accounts"][0]["last_synced_at"],
            "scopes": ["shops_r", "listings_r", "listings_w"],
        }
    ]
    assert payload["matched_connection_count"] == 1
    assert payload["unmapped_connection_count"] == 0
    assert payload["connected_shops"] == [
        {
            "shop_id": "etsy-shop-445566",
            "shop_name": "Sunset Paper Co",
            "shop_url": "https://www.etsy.com/shop/SunsetPaperCo",
            "matched_connection_id": synced_connection["id"],
            "matched_connection_label": "Sunset Paper Co",
            "matched_connection_ids": [synced_connection["id"]],
            "matched_connection_labels": ["Sunset Paper Co"],
        }
    ]

    etsy_status_response = client.get("/etsy/connection")
    assert etsy_status_response.status_code == 200
    assert etsy_status_response.json()["connected_shops"][0]["matched_connection_id"] == synced_connection["id"]

    store_connections_response = client.get("/provider-store-connections")
    assert store_connections_response.status_code == 200
    stored_connection = next(
        item for item in store_connections_response.json() if item["id"] == synced_connection["id"]
    )
    assert stored_connection["etsy_shop_id"] == "etsy-shop-445566"


def test_complete_etsy_oauth_connection_route_accumulates_multiple_accounts(
    client,
    monkeypatch,
) -> None:
    responses = iter(
        [
            {
                "refresh_token": "oauth-refresh-111",
                "seller_user_id": "11111111",
                "scopes": ["shops_r", "listings_r", "listings_w"],
                "shops": [
                    {
                        "shop_id": "etsy-shop-111",
                        "shop_name": "North Shop",
                        "shop_url": "https://www.etsy.com/shop/NorthShop",
                    }
                ],
            },
            {
                "refresh_token": "oauth-refresh-222",
                "seller_user_id": "22222222",
                "scopes": ["shops_r", "listings_r", "listings_w"],
                "shops": [
                    {
                        "shop_id": "etsy-shop-222",
                        "shop_name": "South Shop",
                        "shop_url": "https://www.etsy.com/shop/SouthShop",
                    }
                ],
            },
        ]
    )

    monkeypatch.setattr(
        commerce,
        "exchange_etsy_authorization_code",
        lambda **_kwargs: next(responses),
    )

    first_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-111", "state": "oauth-state-111"},
    )
    assert first_response.status_code == 200
    assert first_response.json()["connected_account_count"] == 1

    second_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-222", "state": "oauth-state-222"},
    )
    assert second_response.status_code == 200
    payload = second_response.json()
    assert payload["connected_account_count"] == 2
    assert payload["connected_shops"] == [
        {
            "shop_id": "etsy-shop-111",
            "shop_name": "North Shop",
            "shop_url": "https://www.etsy.com/shop/NorthShop",
            "matched_connection_id": None,
            "matched_connection_label": None,
            "matched_connection_ids": [],
            "matched_connection_labels": [],
        },
        {
            "shop_id": "etsy-shop-222",
            "shop_name": "South Shop",
            "shop_url": "https://www.etsy.com/shop/SouthShop",
            "matched_connection_id": None,
            "matched_connection_label": None,
            "matched_connection_ids": [],
            "matched_connection_labels": [],
        },
    ]
    assert [
        {
            "credential_key": account["credential_key"],
            "seller_user_id": account["seller_user_id"],
            "shop_id": account["shop_id"],
            "shop_name": account["shop_name"],
            "shop_url": account["shop_url"],
            "scopes": account["scopes"],
        }
        for account in payload["connected_accounts"]
    ] == [
        {
            "credential_key": "11111111",
            "seller_user_id": "11111111",
            "shop_id": "etsy-shop-111",
            "shop_name": "North Shop",
            "shop_url": "https://www.etsy.com/shop/NorthShop",
            "scopes": ["shops_r", "listings_r", "listings_w"],
        },
        {
            "credential_key": "22222222",
            "seller_user_id": "22222222",
            "shop_id": "etsy-shop-222",
            "shop_name": "South Shop",
            "shop_url": "https://www.etsy.com/shop/SouthShop",
            "scopes": ["shops_r", "listings_r", "listings_w"],
        },
    ]


def test_complete_etsy_oauth_connection_route_does_not_cap_account_count_at_five(
    client_without_etsy,
    monkeypatch,
) -> None:
    responses = iter(
        [
            {
                "refresh_token": f"oauth-refresh-{index}",
                "seller_user_id": str(index) * 8,
                "scopes": ["shops_r", "listings_r", "listings_w"],
                "shops": [
                    {
                        "shop_id": f"etsy-shop-{index}",
                        "shop_name": f"Shop {index}",
                        "shop_url": f"https://www.etsy.com/shop/Shop{index}",
                    }
                ],
            }
            for index in range(1, 7)
        ]
    )

    monkeypatch.setattr(
        commerce,
        "exchange_etsy_authorization_code",
        lambda **_kwargs: next(responses),
    )

    final_response = None
    for index in range(1, 7):
        response = client_without_etsy.post(
            "/etsy/oauth/callback",
            json={"code": f"oauth-code-{index}", "state": f"oauth-state-{index}"},
        )
        assert response.status_code == 200
        final_response = response

    assert final_response is not None
    payload = final_response.json()
    assert payload["connected_account_count"] == 6
    assert len(payload["connected_accounts"]) == 6


def test_sync_etsy_connection_shops_route_uses_stored_refresh_token(client, monkeypatch) -> None:
    def fake_exchange_etsy_authorization_code(**_kwargs: object) -> dict[str, object]:
        return {
            "refresh_token": "oauth-refresh-initial",
            "seller_user_id": "12345678",
            "scopes": ["shops_r", "listings_r", "listings_w"],
            "shops": [
                {
                    "shop_id": "etsy-shop-initial",
                    "shop_name": "Initial Shop",
                    "shop_url": "https://www.etsy.com/shop/InitialShop",
                }
            ],
        }

    monkeypatch.setattr(commerce, "exchange_etsy_authorization_code", fake_exchange_etsy_authorization_code)
    callback_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-seed", "state": "oauth-state-seed"},
    )
    assert callback_response.status_code == 200

    captured: dict[str, object] = {}

    def fake_refresh_access_token(refresh_token_override: str | None = None) -> str:
        captured["refresh_token_override"] = refresh_token_override
        return "access-token-123"

    def fake_get_cached_etsy_refresh_token(refresh_token_override: str | None = None) -> str:
        captured["cached_refresh_token_override"] = refresh_token_override
        return "oauth-refresh-rotated"

    def fake_fetch_etsy_shops(*, access_token: str, user_id: str) -> list[dict[str, str]]:
        captured["access_token"] = access_token
        captured["user_id"] = user_id
        return [
            {
                "shop_id": "etsy-shop-updated",
                "shop_name": "Updated Shop",
                "shop_url": "https://www.etsy.com/shop/UpdatedShop",
            }
        ]

    monkeypatch.setattr(commerce, "_refresh_access_token", fake_refresh_access_token)
    monkeypatch.setattr(commerce, "get_cached_etsy_refresh_token", fake_get_cached_etsy_refresh_token)
    monkeypatch.setattr(commerce, "fetch_etsy_shops", fake_fetch_etsy_shops)

    response = client.post("/etsy/connection/sync")
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected_account_count"] == 1
    assert payload["connected_shops"] == [
        {
            "shop_id": "etsy-shop-updated",
            "shop_name": "Updated Shop",
            "shop_url": "https://www.etsy.com/shop/UpdatedShop",
            "matched_connection_id": None,
            "matched_connection_label": None,
            "matched_connection_ids": [],
            "matched_connection_labels": [],
        }
    ]
    assert captured == {
        "refresh_token_override": "oauth-refresh-initial",
        "cached_refresh_token_override": "oauth-refresh-initial",
        "access_token": "access-token-123",
        "user_id": "12345678",
    }

    with client.app.state.testing_session_local() as db:
        encrypted_refresh_token = db.execute(
            text(
                """
                select encrypted_value
                from provider_credentials
                where organization_id = :organization_id
                  and provider = 'etsy'
                  and key_name = '12345678::oauth_refresh_token'
                """
            ),
            {"organization_id": "default-org"},
        ).scalar_one()

    assert decrypt_value(encrypted_refresh_token) == "oauth-refresh-rotated"


def test_sync_etsy_connection_shops_route_refreshes_all_connected_accounts(client, monkeypatch) -> None:
    responses = iter(
        [
            {
                "refresh_token": "oauth-refresh-111",
                "seller_user_id": "11111111",
                "scopes": ["shops_r", "listings_r", "listings_w"],
                "shops": [
                    {
                        "shop_id": "etsy-shop-111",
                        "shop_name": "North Shop",
                        "shop_url": "https://www.etsy.com/shop/NorthShop",
                    }
                ],
            },
            {
                "refresh_token": "oauth-refresh-222",
                "seller_user_id": "22222222",
                "scopes": ["shops_r", "listings_r", "listings_w"],
                "shops": [
                    {
                        "shop_id": "etsy-shop-222",
                        "shop_name": "South Shop",
                        "shop_url": "https://www.etsy.com/shop/SouthShop",
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(
        commerce,
        "exchange_etsy_authorization_code",
        lambda **_kwargs: next(responses),
    )

    assert client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-111", "state": "oauth-state-111"},
    ).status_code == 200
    assert client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-222", "state": "oauth-state-222"},
    ).status_code == 200

    refresh_calls: list[str] = []
    cached_refresh_calls: list[str] = []
    user_calls: list[tuple[str, str]] = []

    def fake_refresh_access_token(refresh_token_override: str | None = None) -> str:
        refresh_calls.append(str(refresh_token_override))
        return f"access-{refresh_token_override}"

    def fake_get_cached_etsy_refresh_token(refresh_token_override: str | None = None) -> str:
        cached_refresh_calls.append(str(refresh_token_override))
        return f"rotated-{refresh_token_override}"

    def fake_fetch_etsy_shops(*, access_token: str, user_id: str) -> list[dict[str, str]]:
        user_calls.append((access_token, user_id))
        return [
            {
                "shop_id": f"shop-for-{user_id}",
                "shop_name": f"Shop {user_id}",
                "shop_url": f"https://www.etsy.com/shop/{user_id}",
            }
        ]

    monkeypatch.setattr(commerce, "_refresh_access_token", fake_refresh_access_token)
    monkeypatch.setattr(commerce, "get_cached_etsy_refresh_token", fake_get_cached_etsy_refresh_token)
    monkeypatch.setattr(commerce, "fetch_etsy_shops", fake_fetch_etsy_shops)

    response = client.post("/etsy/connection/sync")
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected_account_count"] == 2
    assert refresh_calls == ["oauth-refresh-111", "oauth-refresh-222"]
    assert cached_refresh_calls == ["oauth-refresh-111", "oauth-refresh-222"]
    assert user_calls == [
        ("access-oauth-refresh-111", "11111111"),
        ("access-oauth-refresh-222", "22222222"),
    ]

    with client.app.state.testing_session_local() as db:
        refresh_token_rows = db.execute(
            text(
                """
                select key_name, encrypted_value
                from provider_credentials
                where organization_id = :organization_id
                  and provider = 'etsy'
                  and key_name like :refresh_key
                order by key_name asc
                """
            ),
            {
                "organization_id": "default-org",
                "refresh_key": "%oauth_refresh_token",
            },
        ).all()

    assert [
        (key_name, decrypt_value(encrypted_value))
        for key_name, encrypted_value in refresh_token_rows
        if key_name != "oauth_refresh_token"
    ] == [
        ("11111111::oauth_refresh_token", "rotated-oauth-refresh-111"),
        ("22222222::oauth_refresh_token", "rotated-oauth-refresh-222"),
    ]


def test_provider_store_sync_auto_maps_when_etsy_was_connected_first(client, monkeypatch) -> None:
    class PrintifyWithoutShopIdAdapter:
        def __init__(self, credentials: dict[str, object]) -> None:
            self.credentials = credentials

        async def discover_store_connections(self) -> list[ProviderStoreRecord]:
            return [
                ProviderStoreRecord(
                    provider_store_id="shop-etsy",
                    storefront_type="etsy",
                    storefront_display_name="Etsy",
                    label="Printify Test Shop -> Etsy",
                    discovery_source="provider_api",
                )
            ]

    def fake_exchange_etsy_authorization_code(**_kwargs: object) -> dict[str, object]:
        return {
            "refresh_token": "oauth-refresh-123",
            "seller_user_id": "12345678",
            "scopes": ["shops_r", "listings_r", "listings_w"],
            "shops": [
                {
                    "shop_id": "etsy-shop-445566",
                    "shop_name": "Printify Test Shop",
                    "shop_url": "https://www.etsy.com/shop/PrintifyTestShop",
                }
            ],
        }

    monkeypatch.setattr(commerce, "exchange_etsy_authorization_code", fake_exchange_etsy_authorization_code)
    monkeypatch.setattr(
        commerce,
        "get_provider_adapter",
        lambda provider, credentials: PrintifyWithoutShopIdAdapter(credentials),
    )

    callback_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-preconnect", "state": "oauth-state-preconnect"},
    )
    assert callback_response.status_code == 200
    assert callback_response.json()["matched_connection_count"] == 0

    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    etsy_connection = next(
        item for item in sync_response.json()["connections"] if item["storefront_type"] == "etsy"
    )
    assert etsy_connection["label"] == "Printify Test Shop -> Etsy"
    assert etsy_connection["etsy_shop_id"] == "etsy-shop-445566"


def test_complete_etsy_oauth_connection_route_maps_same_shop_to_multiple_provider_connections(
    client,
    monkeypatch,
) -> None:
    class PrintifyPeddlexAdapter:
        def __init__(self, credentials: dict[str, object]) -> None:
            self.credentials = credentials

        async def discover_store_connections(self) -> list[ProviderStoreRecord]:
            return [
                ProviderStoreRecord(
                    provider_store_id="printify-peddlex",
                    storefront_type="etsy",
                    storefront_display_name="Etsy",
                    label="Peddlex -> Etsy",
                    discovery_source="provider_api",
                )
            ]

    original_get_provider_adapter = commerce.get_provider_adapter

    monkeypatch.setattr(
        commerce,
        "get_provider_adapter",
        lambda provider, credentials: (
            PrintifyPeddlexAdapter(credentials)
            if provider == "printify"
            else original_get_provider_adapter(provider, credentials)
        ),
    )

    gelato_credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key-123"},
            "credential_display_name": "Poster partner",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-peddlex",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Peddlex",
                }
            ],
        },
    )
    assert gelato_credentials_response.status_code == 200
    gelato_credential_key = gelato_credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    gelato_sync_response = client.post(f"/provider-store-connections/sync/gelato/{gelato_credential_key}")
    assert gelato_sync_response.status_code == 200

    printify_credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert printify_credentials_response.status_code == 200

    printify_sync_response = client.post("/provider-store-connections/sync/printify")
    assert printify_sync_response.status_code == 200

    def fake_exchange_etsy_authorization_code(**_kwargs: object) -> dict[str, object]:
        return {
            "refresh_token": "oauth-refresh-123",
            "seller_user_id": "12345678",
            "scopes": ["shops_r", "listings_r", "listings_w"],
            "shops": [
                {
                    "shop_id": "etsy-shop-445566",
                    "shop_name": "Peddlex",
                    "shop_url": "https://www.etsy.com/shop/Peddlex",
                }
            ],
        }

    monkeypatch.setattr(commerce, "exchange_etsy_authorization_code", fake_exchange_etsy_authorization_code)

    callback_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-peddlex", "state": "oauth-state-peddlex"},
    )
    assert callback_response.status_code == 200
    payload = callback_response.json()
    assert payload["matched_connection_count"] == 2
    assert payload["connected_shops"] == [
        {
            "shop_id": "etsy-shop-445566",
            "shop_name": "Peddlex",
            "shop_url": "https://www.etsy.com/shop/Peddlex",
            "matched_connection_id": payload["connected_shops"][0]["matched_connection_ids"][0],
            "matched_connection_label": "Peddlex",
            "matched_connection_ids": payload["connected_shops"][0]["matched_connection_ids"],
            "matched_connection_labels": ["Peddlex", "Peddlex -> Etsy"],
        }
    ]
    assert len(payload["connected_shops"][0]["matched_connection_ids"]) == 2

    store_connections_response = client.get("/provider-store-connections")
    assert store_connections_response.status_code == 200
    peddlex_connections = [
        item
        for item in store_connections_response.json()
        if item["storefront_type"] == "etsy" and item["label"] in {"Peddlex", "Peddlex -> Etsy"}
    ]
    assert len(peddlex_connections) == 2
    assert {item["etsy_shop_id"] for item in peddlex_connections} == {"etsy-shop-445566"}


def test_provider_store_sync_auto_maps_additional_connection_to_existing_etsy_shop_id(
    client,
    monkeypatch,
) -> None:
    class PrintifyPeddlexAdapter:
        def __init__(self, credentials: dict[str, object]) -> None:
            self.credentials = credentials

        async def discover_store_connections(self) -> list[ProviderStoreRecord]:
            return [
                ProviderStoreRecord(
                    provider_store_id="printify-peddlex",
                    storefront_type="etsy",
                    storefront_display_name="Etsy",
                    label="Peddlex -> Etsy",
                    discovery_source="provider_api",
                )
            ]

    def fake_exchange_etsy_authorization_code(**_kwargs: object) -> dict[str, object]:
        return {
            "refresh_token": "oauth-refresh-123",
            "seller_user_id": "12345678",
            "scopes": ["shops_r", "listings_r", "listings_w"],
            "shops": [
                {
                    "shop_id": "etsy-shop-445566",
                    "shop_name": "Peddlex",
                    "shop_url": "https://www.etsy.com/shop/Peddlex",
                }
            ],
        }

    original_get_provider_adapter = commerce.get_provider_adapter
    monkeypatch.setattr(commerce, "exchange_etsy_authorization_code", fake_exchange_etsy_authorization_code)

    callback_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-peddlex", "state": "oauth-state-peddlex"},
    )
    assert callback_response.status_code == 200

    gelato_credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key-123"},
            "credential_display_name": "Poster partner",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-peddlex",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Peddlex",
                }
            ],
        },
    )
    assert gelato_credentials_response.status_code == 200
    gelato_credential_key = gelato_credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    gelato_sync_response = client.post(f"/provider-store-connections/sync/gelato/{gelato_credential_key}")
    assert gelato_sync_response.status_code == 200
    assert gelato_sync_response.json()["connections"][0]["etsy_shop_id"] == "etsy-shop-445566"

    monkeypatch.setattr(
        commerce,
        "get_provider_adapter",
        lambda provider, credentials: (
            PrintifyPeddlexAdapter(credentials)
            if provider == "printify"
            else original_get_provider_adapter(provider, credentials)
        ),
    )

    printify_credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert printify_credentials_response.status_code == 200

    printify_sync_response = client.post("/provider-store-connections/sync/printify")
    assert printify_sync_response.status_code == 200
    assert printify_sync_response.json()["connections"][0]["etsy_shop_id"] == "etsy-shop-445566"


def test_commerce_flow_routes(client) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200
    assert credentials_response.json()["credential_status"]["is_configured"] is True

    credential_status_response = client.get("/pod-providers/printify/credentials/status")
    assert credential_status_response.status_code == 200
    assert credential_status_response.json()["credentials"][0]["missing_keys"] == []

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    synced_connections = sync_response.json()["connections"]
    assert len(synced_connections) == 2
    provider_store_connection_id = synced_connections[0]["id"]

    list_providers_response = client.get("/pod-providers")
    assert list_providers_response.status_code == 200
    assert any(item["id"] == "printify" and item["connected_stores"] == 2 for item in list_providers_response.json())

    asset_upload_response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_upload_response.status_code == 201
    design_asset_id = asset_upload_response.json()["id"]
    assert (
        asset_upload_response.json()["storage_key"]
        == f"organizations/default-org/design-assets/{design_asset_id}/source.png"
    )
    assert asset_upload_response.json()["public_url"].startswith("https://storage.test/")

    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Minimalist Canvas",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-123",
            "product_code": "SKU-100",
            "base_tags": ["modern art"],
        },
    )
    assert blueprint_response.status_code == 201
    blueprint = blueprint_response.json()
    assert blueprint["provider_resource_id"] == "template-123"
    assert blueprint["status"] == "active"

    validate_response = client.post(f"/blueprints/{blueprint['id']}/validate-reference")
    assert validate_response.status_code == 200
    assert validate_response.json()["validation_status"] == "validated"

    list_blueprints_response = client.get("/blueprints")
    assert list_blueprints_response.status_code == 200
    assert len(list_blueprints_response.json()) == 1

    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint["id"],
            "design_asset_id": design_asset_id,
            "title": "Minimalist Canvas Listing",
            "description": "Clean neutral wall art.",
            "tags": ["neutral decor", "canvas art"],
            "retail_price": 39.99,
            "currency": "USD",
            "sku": "MC-001",
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()
    assert product["status"] == "draft"
    assert product["margin"] == pytest.approx(25.0, rel=1e-4)

    replacement_asset_response = client.post(
        "/design-assets",
        files={"file": ("replacement.png", VALID_PNG_BYTES, "image/png")},
    )
    assert replacement_asset_response.status_code == 201
    replacement_asset_id = replacement_asset_response.json()["id"]

    update_response = client.patch(
        f"/products/{product['id']}",
        json={
            "title": "Minimalist Canvas Listing Updated",
            "design_asset_id": replacement_asset_id,
        },
    )
    assert update_response.status_code == 200
    updated_product = update_response.json()
    assert updated_product["title"] == "Minimalist Canvas Listing Updated"
    assert updated_product["design_asset_id"] == replacement_asset_id
    assert updated_product["design_asset"]["id"] == replacement_asset_id

    mockup_response = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("mockup.png", VALID_PNG_BYTES, "image/png")},
        data={"position": "0"},
    )
    assert mockup_response.status_code == 201
    first_mockup = mockup_response.json()
    assert first_mockup["position"] == 0
    assert (
        first_mockup["storage_key"]
            == f"organizations/default-org/draft-mockups/{product['id']}/{first_mockup['id']}/source.png"
    )

    second_mockup_response = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("mockup-2.png", VALID_PNG_BYTES, "image/png")},
        data={"position": "1"},
    )
    assert second_mockup_response.status_code == 201
    second_mockup = second_mockup_response.json()

    reorder_response = client.patch(
        f"/products/{product['id']}/mockups/order",
        json={"mockup_ids": [second_mockup["id"], first_mockup["id"]]},
    )
    assert reorder_response.status_code == 200
    reordered_mockups = reorder_response.json()["mockups"]
    assert [item["id"] for item in reordered_mockups] == [second_mockup["id"], first_mockup["id"]]
    assert [item["position"] for item in reordered_mockups] == [0, 1]

    assert first_mockup["storage_key"] in client.app.state.fake_storage.objects
    delete_mockup_response = client.delete(
        f"/products/{product['id']}/mockups/{first_mockup['id']}"
    )
    assert delete_mockup_response.status_code == 200
    remaining_mockups = delete_mockup_response.json()["mockups"]
    assert [item["id"] for item in remaining_mockups] == [second_mockup["id"]]
    assert remaining_mockups[0]["position"] == 0
    assert first_mockup["storage_key"] not in client.app.state.fake_storage.objects

    publish_response = client.post(f"/products/{product['id']}/publish")
    assert publish_response.status_code == 200
    job = publish_response.json()["job"]
    assert job["status"] == "queued"

    job_response = client.get(f"/publishing-jobs/{job['id']}")
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "succeeded"

    published_product_response = client.get(f"/products/{product['id']}")
    assert published_product_response.status_code == 200
    published_product = published_product_response.json()
    assert published_product["publishing_status"] == "succeeded"
    assert published_product["status"] == "published"
    assert published_product["provider_product_id"].startswith("pf-")
    assert published_product["external_listing_id"].startswith("etsy-pf-")

    list_routes = {
        "/products": 1,
        "/publishing-jobs": 1,
        "/provider-store-connections": 2,
    }
    for path, expected_len in list_routes.items():
        response = client.get(path)
        assert response.status_code == 200
        assert len(response.json()) == expected_len

    studio_response = client.get("/product-studio")
    assert studio_response.status_code == 200
    assert studio_response.json()["blueprint_count"] == 1
    assert studio_response.json()["draft_count"] == 1
    assert "supports_mock_ai_generation" not in studio_response.json()


def test_create_blueprint_returns_validation_error_for_invalid_printify_reference(client, monkeypatch) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    class InvalidReferenceAdapter:
        async def validate_reference(self, *, reference_type: str, reference_value: str) -> ReferenceValidationResult:
            raise ValueError("Printify references must be a product-details URL or product id.")

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: InvalidReferenceAdapter())

    response = client.post(
        "/blueprints",
        json={
            "name": "Broken Printify Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "not-a-printify-reference",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Printify references must be a product-details URL or product id."


@pytest.mark.parametrize(
    ("field_name", "blank_value"),
    [
        ("name", "   "),
        ("category", "\t"),
        ("provider_store_connection_id", " "),
        ("reference_type", "\n"),
        ("reference_value", ""),
    ],
)
def test_create_blueprint_rejects_blank_required_fields(client, field_name: str, blank_value: str) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    payload = {
        "name": "Blank Field Blueprint",
        "category": "Wall Art",
        "provider_store_connection_id": provider_store_connection_id,
        "reference_type": "printify_product_url",
        "reference_value": "https://printify.com/app/product-details/template-123",
    }
    payload[field_name] = blank_value

    response = client.post("/blueprints", json=payload)

    assert response.status_code == 422
    response_body = response.json()
    assert "detail" in response_body


def test_provider_action_error_maps_missing_gelato_template_to_422() -> None:
    with pytest.raises(HTTPException) as exc_info:
        commerce._raise_provider_action_error(
            provider="gelato",
            action="validating this blueprint reference",
            exc=RuntimeError("Failed to fetch Gelato template 'missing-template': 404 {'message': 'not found'}"),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Gelato template id was not found. Enter a real Gelato template id and try again."


def test_provider_store_sync_returns_clear_error_when_printify_credentials_are_rejected(client, monkeypatch) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    class ForbiddenShopsAdapter:
        async def discover_store_connections(self) -> list[ProviderStoreRecord]:
            raise RuntimeError("Failed to fetch Printify shops: 403 {'message': 'forbidden'}")

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: ForbiddenShopsAdapter())

    response = client.post("/provider-store-connections/sync/printify")

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Printify rejected the saved credentials while syncing stores. Reconnect Printify in Settings and try again."
    )


def test_design_asset_upload_returns_clear_error_when_storage_is_unconfigured(client, monkeypatch) -> None:
    class UnconfiguredStorage:
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
            raise RuntimeError("S3-compatible storage is not configured.")

    monkeypatch.setattr(product_service, "get_storage_service", lambda: UnconfiguredStorage())

    response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "Asset storage is not configured in this environment. Add the storage settings before uploading files."
    )


def test_publish_background_job_uses_draft_organization_scope(client, monkeypatch) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    asset_upload_response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_upload_response.status_code == 201
    design_asset_id = asset_upload_response.json()["id"]

    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Scoped Publish Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-456",
        },
    )
    assert blueprint_response.status_code == 201
    blueprint_id = blueprint_response.json()["id"]

    validate_response = client.post(f"/blueprints/{blueprint_id}/validate-reference")
    assert validate_response.status_code == 200

    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint_id,
            "design_asset_id": design_asset_id,
            "title": "Scoped Publish Listing",
            "description": "Uses the draft org instead of the seeded default org.",
            "tags": ["scoped publish"],
            "retail_price": 39.99,
            "currency": "USD",
            "sku": "SP-001",
        },
    )
    assert product_response.status_code == 201
    product_id = product_response.json()["id"]

    second_mockup_response = client.post(
        f"/products/{product_id}/mockups",
        files={"file": ("second.jpg", VALID_JPEG_BYTES, "image/jpeg")},
        data={"position": "1"},
    )
    assert second_mockup_response.status_code == 201
    hero_mockup_response = client.post(
        f"/products/{product_id}/mockups",
        files={"file": ("hero.png", VALID_PNG_BYTES, "image/png")},
        data={"position": "0"},
    )
    assert hero_mockup_response.status_code == 201

    with client.app.state.testing_session_local() as db:
        job = publishing_service.enqueue_publishing_job(
            db,
            actor=get_default_actor_context(),
            product_id=product_id,
        )
        job_id = job.id

    monkeypatch.setattr(settings, "default_organization_id", "wrong-org")
    publishing_service.run_publishing_job_background(job_id)
    monkeypatch.setattr(settings, "default_organization_id", "default-org")

    job_response = client.get(f"/publishing-jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "succeeded"

    product_status_response = client.get(f"/products/{product_id}")
    assert product_status_response.status_code == 200
    assert product_status_response.json()["publishing_status"] == "succeeded"
    assert product_status_response.json()["status"] == "published"
    assert product_status_response.json()["provider_product_url"].endswith(
        f"/listing-editor/edit/etsy-pf-{product_id}"
    )
    assert len(client.app.state.etsy_listing_sync_calls) == 1
    listing_sync = client.app.state.etsy_listing_sync_calls[0]
    assert listing_sync["listing_id"] == f"etsy-pf-{product_id}"
    assert listing_sync["title"] == "Scoped Publish Listing"
    assert listing_sync["description"] == "Uses the draft org instead of the seeded default org."
    assert listing_sync["tags"] == ["scoped publish"]
    assert len(client.app.state.etsy_image_sync_calls) == 1
    image_sync = client.app.state.etsy_image_sync_calls[0]
    assert image_sync["listing_id"] == f"etsy-pf-{product_id}"
    assert [image.file_name for image in image_sync["images"]] == ["hero.png", "second.jpg"]
    assert [image.content for image in image_sync["images"]] == [VALID_PNG_BYTES, VALID_JPEG_BYTES]


def test_delete_product_removes_velora_record_and_attached_mockups(client) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    asset_upload_response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_upload_response.status_code == 201
    design_asset = asset_upload_response.json()

    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Delete Product Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-delete-product",
        },
    )
    assert blueprint_response.status_code == 201
    blueprint = blueprint_response.json()

    validate_response = client.post(f"/blueprints/{blueprint['id']}/validate-reference")
    assert validate_response.status_code == 200

    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint["id"],
            "design_asset_id": design_asset["id"],
            "title": "Delete Me",
            "retail_price": 24.99,
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()

    mockup_response = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("mockup.png", VALID_PNG_BYTES, "image/png")},
        data={"position": "0"},
    )
    assert mockup_response.status_code == 201
    mockup = mockup_response.json()
    assert mockup["storage_key"] in client.app.state.fake_storage.objects
    assert design_asset["storage_key"] in client.app.state.fake_storage.objects

    publish_response = client.post(f"/products/{product['id']}/publish")
    assert publish_response.status_code == 200

    delete_response = client.delete(f"/products/{product['id']}")
    assert delete_response.status_code == 204
    assert delete_response.text == ""

    fetch_response = client.get(f"/products/{product['id']}")
    assert fetch_response.status_code == 404

    list_response = client.get("/products")
    assert list_response.status_code == 200
    assert list_response.json() == []

    assert mockup["storage_key"] not in client.app.state.fake_storage.objects
    assert design_asset["storage_key"] not in client.app.state.fake_storage.objects

    with client.app.state.testing_session_local() as db:
        publishing_jobs = db.execute(
            text("select count(*) from publishing_jobs where provider_product_draft_id = :product_id"),
            {"product_id": product["id"]},
        ).scalar_one()
        pod_products = db.execute(
            text("select count(*) from pod_products where provider_product_draft_id = :product_id"),
            {"product_id": product["id"]},
        ).scalar_one()
        mockups = db.execute(
            text("select count(*) from mockups where provider_product_draft_id = :product_id"),
            {"product_id": product["id"]},
        ).scalar_one()
        design_assets = db.execute(
            text("select count(*) from design_assets where id = :design_asset_id"),
            {"design_asset_id": design_asset["id"]},
        ).scalar_one()

    assert publishing_jobs == 0
    assert pod_products == 0
    assert mockups == 0
    assert design_assets == 0


def test_delete_product_keeps_shared_design_asset_object_when_another_product_still_uses_it(client) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    asset_upload_response = client.post(
        "/design-assets",
        files={"file": ("shared-design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_upload_response.status_code == 201
    design_asset = asset_upload_response.json()

    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Shared Design Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-shared-design",
        },
    )
    assert blueprint_response.status_code == 201
    blueprint = blueprint_response.json()

    validate_response = client.post(f"/blueprints/{blueprint['id']}/validate-reference")
    assert validate_response.status_code == 200

    first_product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint["id"],
            "design_asset_id": design_asset["id"],
            "title": "First Shared Product",
        },
    )
    assert first_product_response.status_code == 201
    first_product = first_product_response.json()

    second_product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint["id"],
            "design_asset_id": design_asset["id"],
            "title": "Second Shared Product",
        },
    )
    assert second_product_response.status_code == 201
    second_product = second_product_response.json()

    delete_response = client.delete(f"/products/{first_product['id']}")
    assert delete_response.status_code == 204

    second_fetch_response = client.get(f"/products/{second_product['id']}")
    assert second_fetch_response.status_code == 200
    assert second_fetch_response.json()["design_asset_id"] == design_asset["id"]

    assert design_asset["storage_key"] in client.app.state.fake_storage.objects

    with client.app.state.testing_session_local() as db:
        remaining_design_assets = db.execute(
            text("select count(*) from design_assets where id = :design_asset_id"),
            {"design_asset_id": design_asset["id"]},
        ).scalar_one()

    assert remaining_design_assets == 1


def test_existing_etsy_listing_send_bypasses_printify_and_syncs_etsy_directly(client) -> None:
    fake_adapter_class = client.app.state.fake_printify_adapter_class

    try:
        credentials_response = client.put(
            "/pod-providers/printify/credentials",
            json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
        )
        assert credentials_response.status_code == 200

        sync_response = client.post("/provider-store-connections/sync/printify")
        assert sync_response.status_code == 200
        provider_store_connection_id = sync_response.json()["connections"][0]["id"]

        asset_upload_response = client.post(
            "/design-assets",
            files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
        )
        assert asset_upload_response.status_code == 201
        design_asset_id = asset_upload_response.json()["id"]

        blueprint_response = client.post(
            "/blueprints",
            json={
                "name": "Republish Blueprint",
                "category": "Wall Art",
                "provider_store_connection_id": provider_store_connection_id,
                "reference_type": "printify_product_url",
                "reference_value": "https://printify.com/app/product-details/template-republish",
            },
        )
        assert blueprint_response.status_code == 201
        blueprint = blueprint_response.json()

        validate_response = client.post(f"/blueprints/{blueprint['id']}/validate-reference")
        assert validate_response.status_code == 200

        product_response = client.post(
            "/products",
            json={
                "blueprint_id": blueprint["id"],
                "design_asset_id": design_asset_id,
                "title": "Original Listing",
                "description": "Original description",
                "tags": ["original"],
                "retail_price": 39.99,
                "currency": "USD",
                "sku": "REP-001",
            },
        )
        assert product_response.status_code == 201
        product = product_response.json()
        _attach_publishable_mockup(client, product["id"])

        first_publish_response = client.post(f"/products/{product['id']}/publish")
        assert first_publish_response.status_code == 200

        first_job = first_publish_response.json()["job"]
        first_job_response = client.get(f"/publishing-jobs/{first_job['id']}")
        assert first_job_response.status_code == 200
        assert first_job_response.json()["status"] == "succeeded"

        first_product_response = client.get(f"/products/{product['id']}")
        assert first_product_response.status_code == 200
        first_published_product = first_product_response.json()
        provider_product_id = first_published_product["provider_product_id"]
        assert provider_product_id.startswith("pf-")
        assert list(fake_adapter_class.created_products.keys()) == [provider_product_id]
        assert fake_adapter_class.updated_products == {}

        update_response = client.patch(
            f"/products/{product['id']}",
            json={
                "title": "Updated Listing Title",
                "description": "Updated description",
                "tags": ["updated", "listing"],
            },
        )
        assert update_response.status_code == 200

        second_publish_response = client.post(f"/products/{product['id']}/publish")
        assert second_publish_response.status_code == 200

        second_job = second_publish_response.json()["job"]
        second_job_response = client.get(f"/publishing-jobs/{second_job['id']}")
        assert second_job_response.status_code == 200
        assert second_job_response.json()["status"] == "succeeded"

        republished_product_response = client.get(f"/products/{product['id']}")
        assert republished_product_response.status_code == 200
        republished_product = republished_product_response.json()
        assert republished_product["provider_product_id"] == provider_product_id
        assert list(fake_adapter_class.created_products.keys()) == [provider_product_id]
        assert fake_adapter_class.updated_products == {}
        assert len(client.app.state.etsy_listing_sync_calls) == 2
        assert client.app.state.etsy_listing_sync_calls[-1]["listing_id"] == (
            first_published_product["external_listing_id"]
        )
        assert client.app.state.etsy_listing_sync_calls[-1]["title"] == "Updated Listing Title"
        assert len(client.app.state.etsy_image_sync_calls) == 2
    finally:
        pass


def test_saved_published_etsy_changes_wait_for_send_then_sync_directly(client, monkeypatch) -> None:
    oauth_responses = iter(
        [
            {
                "refresh_token": "oauth-refresh-123",
                "seller_user_id": "12345678",
                "scopes": ["shops_r", "listings_r", "listings_w"],
                "shops": [
                    {
                        "shop_id": "etsy-connected-shop",
                        "shop_name": "Connected Etsy Shop",
                        "shop_url": "https://www.etsy.com/shop/ConnectedEtsyShop",
                    }
                ],
            },
            {
                "refresh_token": "oauth-refresh-target",
                "seller_user_id": "87654321",
                "scopes": ["shops_r", "listings_r", "listings_w"],
                "shops": [
                    {
                        "shop_id": "etsy-shop-123456",
                        "shop_name": "Target Etsy Shop",
                        "shop_url": "https://www.etsy.com/shop/TargetEtsyShop",
                    }
                ],
            },
        ]
    )

    def fake_exchange_etsy_authorization_code(**_kwargs: object) -> dict[str, object]:
        return next(oauth_responses)

    monkeypatch.setattr(commerce, "exchange_etsy_authorization_code", fake_exchange_etsy_authorization_code)

    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    etsy_callback_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-etsy-direct", "state": "oauth-state-etsy-direct"},
    )
    assert etsy_callback_response.status_code == 200
    second_etsy_callback_response = client.post(
        "/etsy/oauth/callback",
        json={"code": "oauth-code-etsy-target", "state": "oauth-state-etsy-target"},
    )
    assert second_etsy_callback_response.status_code == 200

    store_update_response = client.patch(
        f"/provider-store-connections/{provider_store_connection_id}",
        json={"etsy_shop_id": "etsy-shop-123456"},
    )
    assert store_update_response.status_code == 200
    assert store_update_response.json()["etsy_shop_id"] == "etsy-shop-123456"

    asset_upload_response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_upload_response.status_code == 201
    design_asset_id = asset_upload_response.json()["id"]

    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Direct Etsy Edit Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-etsy-direct-edit",
        },
    )
    assert blueprint_response.status_code == 201
    blueprint = blueprint_response.json()

    validate_response = client.post(f"/blueprints/{blueprint['id']}/validate-reference")
    assert validate_response.status_code == 200

    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint["id"],
            "design_asset_id": design_asset_id,
            "title": "Original Etsy Title",
            "description": "Original Etsy description",
            "tags": ["original", "etsy"],
            "retail_price": 39.99,
            "currency": "USD",
            "sku": "ETSY-001",
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()
    _attach_publishable_mockup(client, product["id"])

    publish_response = client.post(f"/products/{product['id']}/publish")
    assert publish_response.status_code == 200
    job_id = publish_response.json()["job"]["id"]

    job_response = client.get(f"/publishing-jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "succeeded"

    update_response = client.patch(
        f"/products/{product['id']}",
        json={
            "title": "Updated Etsy Title",
            "description": "Updated Etsy description",
            "tags": ["updated", "listing"],
            "retail_price": 44.99,
            "currency": "USD",
            "sku": "ETSY-002",
        },
    )
    assert update_response.status_code == 200
    updated_product = update_response.json()
    assert updated_product["title"] == "Updated Etsy Title"
    assert updated_product["description"] == "Updated Etsy description"
    assert updated_product["tags"] == ["updated", "listing"]
    assert updated_product["retail_price"] == pytest.approx(44.99, rel=1e-4)
    assert updated_product["sku"] == "ETSY-002"
    assert len(client.app.state.etsy_listing_sync_calls) == 1

    second_publish_response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": updated_product["revision"]},
    )
    assert second_publish_response.status_code == 200
    second_job = client.get(
        f"/publishing-jobs/{second_publish_response.json()['job']['id']}"
    ).json()
    assert second_job["status"] == "succeeded"

    captured = client.app.state.etsy_listing_sync_calls[-1]
    assert captured["listing_id"] == updated_product["external_listing_id"]
    assert captured["etsy_shop_id"] == "etsy-shop-123456"
    assert captured["refresh_token"] == "oauth-refresh-target"
    assert captured["title"] == "Updated Etsy Title"
    assert captured["description"] == "Updated Etsy description"
    assert captured["tags"] == ["updated", "listing"]
    assert captured["retail_price"] == 44.99
    assert captured["sku"] == "ETSY-002"


def test_saving_published_product_design_does_not_sync_etsy_until_send(
    client,
) -> None:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    asset_upload_response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_upload_response.status_code == 201
    design_asset_id = asset_upload_response.json()["id"]

    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Direct Etsy Design Update Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-etsy-design-update",
        },
    )
    assert blueprint_response.status_code == 201
    blueprint = blueprint_response.json()

    validate_response = client.post(f"/blueprints/{blueprint['id']}/validate-reference")
    assert validate_response.status_code == 200

    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint["id"],
            "design_asset_id": design_asset_id,
            "title": "Stable Etsy Title",
            "description": "Stable Etsy description",
            "tags": ["stable", "etsy"],
            "retail_price": 39.99,
            "currency": "USD",
            "sku": "ETSY-STABLE",
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()
    _attach_publishable_mockup(client, product["id"])

    publish_response = client.post(f"/products/{product['id']}/publish")
    assert publish_response.status_code == 200
    job_id = publish_response.json()["job"]["id"]

    job_response = client.get(f"/publishing-jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "succeeded"

    replacement_asset_response = client.post(
        "/design-assets",
        files={"file": ("replacement.png", VALID_PNG_BYTES, "image/png")},
    )
    assert replacement_asset_response.status_code == 201
    replacement_asset_id = replacement_asset_response.json()["id"]

    update_response = client.patch(
        f"/products/{product['id']}",
        json={
            "title": product["title"],
            "description": product["description"],
            "tags": product["tags"],
            "retail_price": product["retail_price"],
            "currency": product["currency"],
            "sku": product["sku"],
            "design_asset_id": replacement_asset_id,
        },
    )
    assert update_response.status_code == 200
    updated_product = update_response.json()
    assert updated_product["design_asset_id"] == replacement_asset_id
    assert len(client.app.state.etsy_listing_sync_calls) == 1


def test_delete_store_connection_conflict(client) -> None:
    client.put("/pod-providers/printify/credentials", json={"credentials": {"api_token": "token-123"}})
    sync_response = client.post("/provider-store-connections/sync/printify")
    connection_id = sync_response.json()["connections"][0]["id"]
    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Conflict Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/conflict-123",
        },
    )
    assert blueprint_response.status_code == 201
    delete_response = client.delete(f"/provider-store-connections/{connection_id}")
    assert delete_response.status_code == 409


def test_blueprint_service_rejects_cross_organization_store_reference(client) -> None:
    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="other-org-store",
                organization_id="other-org",
                provider="printify",
                credential_key="default",
                provider_store_id="other-shop",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Other Organization Store",
                status="connected",
            )
        )
        db.commit()

    response = client.post(
        "/blueprints",
        json={
            "name": "Cross Organization Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": "other-org-store",
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/cross-org",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider store connection not found."


def test_delete_store_connection_preserves_order_history_and_sync_revives_it(client) -> None:
    client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}},
    )
    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    connection_id = sync_response.json()["connections"][0]["id"]

    session_local = client.app.state.testing_session_local
    with session_local() as db:
        db.add(
            Order(
                organization_id="default-org",
                provider_store_connection_id=connection_id,
                provider="printify",
                external_order_id="historical-order-1",
                display_order_id="#historical-order-1",
                fulfillment_status="delivered",
                total_amount=Decimal("19.99"),
                order_created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    delete_response = client.delete(f"/provider-store-connections/{connection_id}")
    assert delete_response.status_code == 204
    active_connections = client.get("/provider-store-connections")
    assert active_connections.status_code == 200
    assert connection_id not in {item["id"] for item in active_connections.json()}

    with session_local() as db:
        retained_connection = db.get(ProviderStoreConnection, connection_id)
        retained_order = db.scalar(
            select(Order).where(Order.external_order_id == "historical-order-1")
        )
        assert retained_connection is not None
        assert retained_connection.status == "disconnected"
        assert retained_connection.deleted_at is not None
        assert retained_order is not None
        assert retained_order.provider_store_connection_id == connection_id

    revived_response = client.post("/provider-store-connections/sync/printify")
    assert revived_response.status_code == 200
    assert connection_id in {item["id"] for item in revived_response.json()["connections"]}
    with session_local() as db:
        revived_connection = db.get(ProviderStoreConnection, connection_id)
        assert revived_connection is not None
        assert revived_connection.status == "connected"
        assert revived_connection.deleted_at is None
        assert db.scalar(
            select(Order).where(Order.external_order_id == "historical-order-1")
        ) is not None


def test_provider_status_supports_multiple_printify_credentials(client) -> None:
    first_response = client.put(
        "/pod-providers/printify/credentials",
        json={
            "credentials": {"api_token": "token-123"},
            "credential_display_name": "Primary printify token",
        },
    )
    assert first_response.status_code == 200

    second_response = client.put(
        "/pod-providers/printify/credentials",
        json={
            "credentials": {"api_token": "token-456"},
            "credential_display_name": "Backup printify token",
        },
    )
    assert second_response.status_code == 200

    payload = second_response.json()["credential_status"]
    assert payload["credential_count"] == 2
    assert len(payload["credentials"]) == 2
    assert {item["credential_display_name"] for item in payload["credentials"]} == {
        "Primary printify token",
        "Backup printify token",
    }
    assert {item["credential_masked_value"] for item in payload["credentials"]} == {"tok..."}
    assert all(item["configured_keys"] == ["api_token"] for item in payload["credentials"])


def test_provider_status_supports_multiple_gelato_credentials_with_seeds(client) -> None:
    response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Gelato Poster Shop -> Etsy",
                }
            ],
        },
    )
    assert response.status_code == 200

    status_response = client.get("/pod-providers/gelato/credentials/status")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["credential_count"] == 1
    assert payload["credentials"][0]["manual_store_seed_count"] == 1
    assert payload["credentials"][0]["manual_store_seeds"][0]["provider_store_id"] == "gel-store-1"
    assert payload["credentials"][0]["manual_store_seeds"][0]["label"] == "Gelato Poster Shop -> Etsy"
    assert payload["credentials"][0]["credential_display_name"] == "Poster store key"
    assert payload["credentials"][0]["credential_masked_value"] == "gel..."


def test_updating_gelato_manual_store_seeds_preserves_existing_key_label(client) -> None:
    create_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    assert create_response.status_code == 200
    credential_key = create_response.json()["credential_status"]["credentials"][0]["credential_key"]

    update_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credential_key": credential_key,
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Poster Shop -> Etsy",
                },
                {
                    "provider_store_id": "gel-store-2",
                    "storefront_type": "shopify",
                    "storefront_display_name": "Shopify",
                    "label": "Poster Shop -> Shopify",
                },
            ],
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()["credential_status"]
    assert payload["credential_count"] == 1
    assert payload["credentials"][0]["credential_key"] == credential_key
    assert payload["credentials"][0]["credential_display_name"] == "Poster store key"
    assert payload["credentials"][0]["credential_masked_value"] == "gel..."
    assert payload["credentials"][0]["manual_store_seed_count"] == 2


def test_gelato_manual_etsy_store_seeds_require_unique_names(client) -> None:
    create_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    assert create_response.status_code == 200
    credential_key = create_response.json()["credential_status"]["credentials"][0]["credential_key"]

    duplicate_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credential_key": credential_key,
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Sunset Paper Co",
                },
                {
                    "provider_store_id": "gel-store-2",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": " sunset paper co ",
                },
            ],
        },
    )
    assert duplicate_response.status_code == 409
    assert "must be unique" in duplicate_response.json()["detail"]


def test_gelato_manual_etsy_store_seeds_require_non_empty_name(client) -> None:
    create_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    assert create_response.status_code == 200
    credential_key = create_response.json()["credential_status"]["credentials"][0]["credential_key"]

    response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credential_key": credential_key,
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "",
                }
            ],
        },
    )
    assert response.status_code == 400
    assert "Add a store name" in response.json()["detail"]


def test_gelato_manual_etsy_store_seed_name_can_match_existing_printify_etsy_store(client) -> None:
    printify_credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert printify_credentials_response.status_code == 200
    printify_sync_response = client.post("/provider-store-connections/sync/printify")
    assert printify_sync_response.status_code == 200

    gelato_credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    assert gelato_credentials_response.status_code == 200
    credential_key = gelato_credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credential_key": credential_key,
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Printify Test Shop",
                }
            ],
        },
    )
    assert response.status_code == 200


def test_gelato_manual_etsy_store_seeds_cannot_exceed_five_reserved_etsy_rows(client) -> None:
    create_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    assert create_response.status_code == 200
    credential_key = create_response.json()["credential_status"]["credentials"][0]["credential_key"]

    response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credential_key": credential_key,
            "manual_store_seeds": [
                {
                    "provider_store_id": f"gel-store-{index}",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": f"Poster Shop {index}",
                }
                for index in range(1, 7)
            ],
        },
    )
    assert response.status_code == 409
    assert "5 Etsy stores" in response.json()["detail"]


def test_sync_gelato_store_connections_discovers_stores_from_orders(client, monkeypatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post_with_backoff(_self, _client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        assert endpoint == "/v4/orders:search"
        assert payload == {}
        assert timeout == 30.0
        assert action == "order search"
        request = httpx.Request("POST", f"https://order.gelatoapis.com{endpoint}")
        return httpx.Response(
            200,
            json={
                "orders": [
                    {
                        "id": "ord-1",
                        "channel": "etsy",
                        "storeId": "gel-store-1",
                        "createdAt": "2026-06-09T10:00:00+00:00",
                    },
                    {
                        "id": "ord-2",
                        "channel": "shopify",
                        "storeId": "gel-store-2",
                        "createdAt": "2026-06-09T11:00:00+00:00",
                    },
                ]
            },
            request=request,
        )

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: GelatoAdapter(credentials))
    monkeypatch.setattr(GelatoAdapter, "_get_orders_client", lambda self: DummyClient(), raising=False)
    monkeypatch.setattr(GelatoAdapter, "_post_with_backoff", fake_post_with_backoff)

    credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    assert credentials_response.status_code == 200
    credential_key = credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["created_count"] == 2
    assert {item["provider_store_id"] for item in payload["connections"]} == {"gel-store-1", "gel-store-2"}
    labels = {item["provider_store_id"]: item["label"] for item in payload["connections"]}
    assert labels == {
        "gel-store-1": "Etsy [gel-store-1]",
        "gel-store-2": "Shopify [gel-store-2]",
    }


def test_sync_gelato_store_connections_prefers_manual_seed_metadata_over_order_fallback(client, monkeypatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post_with_backoff(_self, _client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        request = httpx.Request("POST", f"https://order.gelatoapis.com{endpoint}")
        return httpx.Response(
            200,
            json={
                "orders": [
                    {
                        "id": "ord-1",
                        "channel": "etsy",
                        "storeId": "gel-store-1",
                        "createdAt": "2026-06-09T10:00:00+00:00",
                    },
                    {
                        "id": "ord-2",
                        "channel": "shopify",
                        "storeId": "gel-store-2",
                        "createdAt": "2026-06-09T11:00:00+00:00",
                    },
                ]
            },
            request=request,
        )

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: GelatoAdapter(credentials))
    monkeypatch.setattr(GelatoAdapter, "_get_orders_client", lambda self: DummyClient(), raising=False)
    monkeypatch.setattr(GelatoAdapter, "_post_with_backoff", fake_post_with_backoff)

    credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "unknown",
                    "storefront_display_name": "Unknown",
                    "label": "Custom Poster Shop",
                }
            ],
        },
    )
    assert credentials_response.status_code == 200
    credential_key = credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")
    assert sync_response.status_code == 200
    connections = {item["provider_store_id"]: item for item in sync_response.json()["connections"]}
    assert set(connections) == {"gel-store-1", "gel-store-2"}
    assert connections["gel-store-1"]["label"] == "Custom Poster Shop"
    assert connections["gel-store-1"]["storefront_type"] == "unknown"
    assert connections["gel-store-1"]["storefront_display_name"] == "Unknown"
    assert connections["gel-store-2"]["label"] == "Shopify [gel-store-2]"
    assert connections["gel-store-2"]["storefront_type"] == "shopify"


def test_sync_gelato_store_connections_maps_unknown_order_channels(client, monkeypatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post_with_backoff(_self, _client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        request = httpx.Request("POST", f"https://order.gelatoapis.com{endpoint}")
        return httpx.Response(
            200,
            json={
                "orders": [
                    {
                        "id": "ord-1",
                        "channel": None,
                        "storeId": "gel-store-1",
                        "createdAt": "2026-06-09T10:00:00+00:00",
                    }
                ]
            },
            request=request,
        )

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: GelatoAdapter(credentials))
    monkeypatch.setattr(GelatoAdapter, "_get_orders_client", lambda self: DummyClient(), raising=False)
    monkeypatch.setattr(GelatoAdapter, "_post_with_backoff", fake_post_with_backoff)

    credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    credential_key = credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")
    assert sync_response.status_code == 200
    payload = sync_response.json()["connections"]
    assert len(payload) == 1
    assert payload[0]["provider_store_id"] == "gel-store-1"
    assert payload[0]["storefront_type"] == "unknown"
    assert payload[0]["storefront_display_name"] == "Unknown"
    assert payload[0]["label"] == "Unknown [gel-store-1]"


def test_sync_gelato_store_connections_ignores_empty_order_results(client, monkeypatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post_with_backoff(_self, _client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        request = httpx.Request("POST", f"https://order.gelatoapis.com{endpoint}")
        return httpx.Response(200, json={"orders": []}, request=request)

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: GelatoAdapter(credentials))
    monkeypatch.setattr(GelatoAdapter, "_get_orders_client", lambda self: DummyClient(), raising=False)
    monkeypatch.setattr(GelatoAdapter, "_post_with_backoff", fake_post_with_backoff)

    credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    credential_key = credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")
    assert sync_response.status_code == 200
    payload = sync_response.json()
    assert payload["synced_count"] == 0
    assert payload["connections"] == []


def test_sync_gelato_store_connections_surfaces_auth_failure_without_manual_fallback(client, monkeypatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post_with_backoff(_self, _client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        request = httpx.Request("POST", f"https://order.gelatoapis.com{endpoint}")
        return httpx.Response(401, json={"message": "Unauthorized"}, request=request)

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: GelatoAdapter(credentials))
    monkeypatch.setattr(GelatoAdapter, "_get_orders_client", lambda self: DummyClient(), raising=False)
    monkeypatch.setattr(GelatoAdapter, "_post_with_backoff", fake_post_with_backoff)

    credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
        },
    )
    assert credentials_response.status_code == 200
    credential_key = credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")

    assert sync_response.status_code == 409
    assert (
        sync_response.json()["detail"]
        == "Gelato rejected the saved credentials while syncing stores. Reconnect Gelato in Settings and try again."
    )


def test_sync_gelato_store_connections_falls_back_to_manual_seeds_on_retryable_order_failure(client, monkeypatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post_with_backoff(_self, _client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        request = httpx.Request("POST", f"https://order.gelatoapis.com{endpoint}")
        return httpx.Response(504, json={"message": "Gateway timeout"}, request=request)

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: GelatoAdapter(credentials))
    monkeypatch.setattr(GelatoAdapter, "_get_orders_client", lambda self: DummyClient(), raising=False)
    monkeypatch.setattr(GelatoAdapter, "_post_with_backoff", fake_post_with_backoff)

    credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Poster Shop -> Etsy",
                }
            ],
        },
    )
    credential_key = credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")
    assert sync_response.status_code == 200
    payload = sync_response.json()["connections"]
    assert len(payload) == 1
    assert payload[0]["provider_store_id"] == "gel-store-1"
    assert payload[0]["label"] == "Poster Shop -> Etsy"


def test_sync_provider_store_connections_by_credential_key(client) -> None:
    first_response = client.put(
        "/pod-providers/printify/credentials",
        json={
            "credentials": {"api_token": "token-123"},
            "credential_display_name": "Primary printify token",
        },
    )
    second_response = client.put(
        "/pod-providers/printify/credentials",
        json={
            "credentials": {"api_token": "token-456"},
            "credential_display_name": "Backup printify token",
        },
    )
    first_key = first_response.json()["credential_status"]["credentials"][0]["credential_key"]
    second_key = next(
        item["credential_key"]
        for item in second_response.json()["credential_status"]["credentials"]
        if item["credential_display_name"] == "Backup printify token"
    )

    first_sync_response = client.post(f"/provider-store-connections/sync/printify/{first_key}")
    assert first_sync_response.status_code == 200
    assert len(first_sync_response.json()["connections"]) == 2
    assert all(item["credential_key"] == first_key for item in first_sync_response.json()["connections"])

    second_sync_response = client.post(f"/provider-store-connections/sync/printify/{second_key}")
    assert second_sync_response.status_code == 200
    assert len(second_sync_response.json()["connections"]) == 2
    assert all(item["credential_key"] == second_key for item in second_sync_response.json()["connections"])

    list_response = client.get("/provider-store-connections")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 4
    assert {item["credential_key"] for item in payload} == {first_key, second_key}


def test_sync_provider_store_connections_persists_etsy_shop_id(client, monkeypatch) -> None:
    class AutoMappedPrintifyAdapter:
        def __init__(self, credentials: dict[str, object]) -> None:
            self.credentials = credentials

        async def discover_store_connections(self) -> list[ProviderStoreRecord]:
            return [
                ProviderStoreRecord(
                    provider_store_id="shop-etsy",
                    storefront_type="etsy",
                    storefront_display_name="Etsy",
                    label="Auto-mapped Etsy Shop",
                    discovery_source="provider_api",
                    etsy_shop_id="etsy-shop-998877",
                )
            ]

    monkeypatch.setattr(commerce, "get_provider_adapter", lambda provider, credentials: AutoMappedPrintifyAdapter(credentials))

    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={
            "credentials": {"api_token": "token-123"},
            "credential_display_name": "Primary printify token",
        },
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    connection = sync_response.json()["connections"][0]
    assert connection["etsy_shop_id"] == "etsy-shop-998877"

    with client.app.state.testing_session_local() as db:
        stored_etsy_shop_id = db.execute(
            text("select etsy_shop_id from provider_store_connections where id = :connection_id"),
            {"connection_id": connection["id"]},
        ).scalar_one()

    assert stored_etsy_shop_id == "etsy-shop-998877"


def test_provider_store_sync_rejects_new_etsy_rows_above_five_store_limit(client) -> None:
    gelato_credentials_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key"},
            "credential_display_name": "Poster store key",
            "manual_store_seeds": [
                {
                    "provider_store_id": f"gel-store-{index}",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": f"Poster Shop {index}",
                }
                for index in range(1, 6)
            ],
        },
    )
    assert gelato_credentials_response.status_code == 200
    credential_key = gelato_credentials_response.json()["credential_status"]["credentials"][0]["credential_key"]

    gelato_sync_response = client.post(f"/provider-store-connections/sync/gelato/{credential_key}")
    assert gelato_sync_response.status_code == 200
    assert len(gelato_sync_response.json()["connections"]) == 5

    printify_credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert printify_credentials_response.status_code == 200

    printify_sync_response = client.post("/provider-store-connections/sync/printify")
    assert printify_sync_response.status_code == 409
    assert "5 Etsy stores" in printify_sync_response.json()["detail"]

    list_response = client.get("/provider-store-connections")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert sum(1 for item in payload if item["storefront_type"] == "etsy") == 5
    assert all(item["provider"] == "gelato" for item in payload if item["storefront_type"] == "etsy")


def test_delete_provider_credential_removes_only_targeted_key_and_stores(client) -> None:
    first_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key-1"},
            "credential_display_name": "Main gelato key",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-1",
                    "storefront_type": "etsy",
                    "storefront_display_name": "Etsy",
                    "label": "Gelato Poster Shop -> Etsy",
                }
            ],
        },
    )
    second_response = client.put(
        "/pod-providers/gelato/credentials",
        json={
            "credentials": {"api_key": "gelato-key-2"},
            "credential_display_name": "Backup gelato key",
            "manual_store_seeds": [
                {
                    "provider_store_id": "gel-store-2",
                    "storefront_type": "shopify",
                    "storefront_display_name": "Shopify",
                    "label": "Gelato Backup Shop -> Shopify",
                }
            ],
        },
    )
    first_key = first_response.json()["credential_status"]["credentials"][0]["credential_key"]
    second_key = next(
        item["credential_key"]
        for item in second_response.json()["credential_status"]["credentials"]
        if item["credential_display_name"] == "Backup gelato key"
    )

    assert client.post(f"/provider-store-connections/sync/gelato/{first_key}").status_code == 200
    assert client.post(f"/provider-store-connections/sync/gelato/{second_key}").status_code == 200

    delete_response = client.delete(f"/pod-providers/gelato/credentials/{second_key}")
    assert delete_response.status_code == 200
    delete_payload = delete_response.json()
    assert delete_payload["status"] == "deleted"
    assert delete_payload["credential_status"]["credential_count"] == 1
    assert delete_payload["credential_status"]["credentials"][0]["credential_key"] == first_key

    status_response = client.get("/pod-providers/gelato/credentials/status")
    assert status_response.status_code == 200
    remaining_keys = {item["credential_key"] for item in status_response.json()["credentials"]}
    assert remaining_keys == {first_key}

    connections_response = client.get("/provider-store-connections")
    assert connections_response.status_code == 200
    remaining_connection_keys = {item["credential_key"] for item in connections_response.json()}
    assert remaining_connection_keys == {first_key}


def test_printify_adapter_helpers() -> None:
    assert PrintifyAdapter._normalize_reference("https://printify.com/app/product-details/abc123") == "abc123"
    assert PrintifyAdapter._storefront_type("Shopify") == "shopify"
    assert PrintifyAdapter._extract_external_listing_id(
        {"sales_channel_properties": [{"url": "https://www.etsy.com/listing/123456789/example"}]}
    ) == "123456789"
    assert PrintifyAdapter._extract_external_listing_id(
        {"sales_channel_properties": [{"url": "https://store.example.com/products/canvas-listing"}]}
    ) == "https://store.example.com/products/canvas-listing"
    adapter = PrintifyAdapter({"api_token": "token", "shop_id": "shop-1"})
    source = {
        "blueprint_id": 12,
        "print_provider_id": 34,
        "variants": [
            {"id": 1, "price": 2500, "is_enabled": True, "sku": "SKU12345", "is_default": False},
            {"id": 2, "price": 2800, "is_enabled": False, "sku": "SKU54321", "is_default": True},
        ],
        "print_areas": [
            {
                "variant_ids": [1, 2],
                "placeholders": [{"position": "front", "images": [{"x": 0.4, "y": 0.6, "scale": 1.4, "angle": 0}]}],
                "background": "#fff",
            }
        ],
        "description": "Source description",
        "tags": ["hello, world"],
        "shipping_template_id": "ship-1",
        "sales_channel_properties": [{"listing_id": "stale-source-listing"}],
    }
    payload = adapter._build_create_payload(
        source=source,
        design_upload={"id": "design-upload-1", "width": 1200, "height": 1200},
        payload=ProviderProductCreateInput(
            product_id="draft-1",
            blueprint_id="bp-1",
            provider="printify",
            provider_store_id="shop-1",
            reference_type="printify_product_url",
            reference_value="abc123",
            provider_resource_id="abc123",
            design_asset_url="https://storage.test/design.png",
            title="Canvas Listing",
            sku="MC-",
        ),
    )
    assert payload["variants"][0]["sku"].startswith("MC-")
    assert payload["print_areas"][0]["placeholders"][0]["images"] == [
        {"id": "design-upload-1", "x": 0.4, "y": 0.6, "scale": 1.4, "angle": 0.0}
    ]
    assert payload["shipping_template_id"] == "ship-1"
    assert "sales_channel_properties" not in payload
    assert payload["variants"][0]["is_default"] is True
    assert payload["variants"][1]["is_default"] is False
    assert payload["blueprint_id"] == 12
    assert payload["print_provider_id"] == 34
    assert payload["visible"] is False


@pytest.mark.asyncio
async def test_printify_update_uploads_design_and_maps_it_to_print_areas(monkeypatch) -> None:
    adapter = PrintifyAdapter({"api_token": "token", "shop_id": "shop-1"})
    captured: dict[str, object] = {"requests": []}
    blueprint_source = {
        "blueprint_id": 241,
        "print_provider_id": 10,
        "variants": [
            {"id": 41686, "price": 4450, "is_enabled": True, "is_default": True, "sku": "SRC41686"},
            {"id": 41687, "price": 6348, "is_enabled": True, "is_default": False, "sku": "SRC41687"},
            {"id": 45130, "price": 9180, "is_enabled": True, "is_default": False, "sku": "SRC45130"},
            {"id": 61899, "price": 11590, "is_enabled": True, "is_default": False, "sku": "SRC61899"},
        ],
        "print_areas": [
            {
                "variant_ids": [41686],
                "background": "#ffffff",
                "placeholders": [{"position": "front", "images": [{"x": 0.5, "y": 0.5, "scale": 1.34, "angle": 0}]}],
            },
            {
                "variant_ids": [41687],
                "background": "#ffffff",
                "placeholders": [{"position": "front", "images": [{"x": 0.5, "y": 0.5, "scale": 1.17, "angle": 0}]}],
            },
            {
                "variant_ids": [45130],
                "background": "#ffffff",
                "placeholders": [{"position": "front", "images": [{"x": 0.5, "y": 0.5, "scale": 1.18, "angle": 0}]}],
            },
            {
                "variant_ids": [61899],
                "background": "#ffffff",
                "placeholders": [{"position": "front", "images": [{"x": 0.5, "y": 0.5, "scale": 1.19, "angle": 0}]}],
            },
        ],
        "description": "Source description",
        "tags": ["hello, world"],
    }

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_request_with_retry(_client, method: str, path: str, **kwargs):
        captured["requests"].append(
            {
                "method": method,
                "path": path,
                "json_payload": kwargs.get("json_payload"),
            }
        )
        request = httpx.Request(method, f"https://api.printify.test{path}")
        response_json = (
            {"id": "design-upload-1", "width": 1200, "height": 1200}
            if path == "/v1/uploads/images.json"
            else {"id": "product-1"}
        )
        return httpx.Response(200, json=response_json, request=request)

    async def fail_get_product(_client, _product_id: str):
        raise AssertionError("update_provider_product should use payload.provider_snapshot_json when it is present")

    monkeypatch.setattr(adapter, "_get_client", lambda: DummyClient())
    monkeypatch.setattr(adapter, "_request_with_retry", fake_request_with_retry)
    monkeypatch.setattr(adapter, "_get_product", fail_get_product)

    await adapter.update_provider_product(
        provider_product_id="product-1",
        payload=ProviderProductCreateInput(
            product_id="draft-1",
            blueprint_id="bp-1",
            provider="printify",
            provider_store_id="shop-1",
            reference_type="printify_product_url",
            reference_value="abc123",
            provider_resource_id="abc123",
            provider_snapshot_json=blueprint_source,
            design_asset_url="https://storage.test/design.jpg",
            title="Canvas Listing",
            sku="MC-",
        ),
    )

    first_update_request = next(
        request
        for request in captured["requests"]
        if request["method"] == "PUT" and request["path"] == "/v1/shops/shop-1/products/product-1.json"
    )
    product_payload = first_update_request["json_payload"]
    assert product_payload["print_areas"][0]["placeholders"][0]["images"][0]["id"] == "design-upload-1"
    assert "blueprint_id" not in product_payload
    assert "print_provider_id" not in product_payload
    assert "visible" not in product_payload
    upload_request = next(
        request for request in captured["requests"] if request["path"] == "/v1/uploads/images.json"
    )
    assert upload_request["json_payload"]["file_name"] == "velora-draft-1.jpg"
    assert upload_request["json_payload"]["url"].startswith("https://storage.test/design.jpg?cb=")
    assert product_payload["variants"][0]["is_default"] is True
    assert product_payload["variants"][0]["id"] == 41686


@pytest.mark.asyncio
async def test_printify_publish_does_not_send_storefront_images(monkeypatch) -> None:
    adapter = PrintifyAdapter({"api_token": "token", "shop_id": "shop-1"})
    captured: dict[str, object] = {"product_reads": 0}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_request_with_retry(_client, method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json_payload"] = kwargs.get("json_payload")
        request = httpx.Request(method, f"https://api.printify.test{path}")
        return httpx.Response(200, json={"id": "product-1"}, request=request)

    async def fake_get_product(_client, product_id: str):
        assert product_id == "product-1"
        captured["product_reads"] += 1
        if captured["product_reads"] == 1:
            return {"id": product_id, "is_locked": True}
        return {"id": product_id, "external": {"id": "etsy-listing-1"}}

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(adapter, "_get_client", lambda: DummyClient())
    monkeypatch.setattr(adapter, "_request_with_retry", fake_request_with_retry)
    monkeypatch.setattr(adapter, "_get_product", fake_get_product)
    monkeypatch.setattr("app.providers.printify.asyncio.sleep", fake_sleep)

    result = await adapter.publish_provider_product(provider_product_id="product-1")

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/shops/shop-1/products/product-1/publish.json"
    assert "images" not in captured["json_payload"]
    assert captured["product_reads"] == 2
    assert result.external_listing_id == "etsy-listing-1"


@pytest.mark.asyncio
async def test_gelato_adapter_description_and_polling(monkeypatch) -> None:
    adapter = GelatoAdapter({"api_key": "key", "store_id": "store-1"})
    rendered = adapter._format_description_for_gelato("Line one\n\nLine two")
    assert rendered == "<p>Line one</p>\n \n<p>Line two</p>"
    call_count = {"value": 0}

    async def fake_sleep(_seconds: int) -> None:
        return None

    async def fake_get_product_with_backoff(_client, *, product_id: str):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "status": "processing",
                "variants": [{"templateVariantId": "v1", "connectionStatus": "processing", "status": "processing"}],
            }
        return {
            "status": "ready",
            "variants": [{"templateVariantId": "v1", "connectionStatus": "connected", "status": "ready"}],
        }

    monkeypatch.setattr("app.providers.gelato.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(adapter, "_get_product_with_backoff", fake_get_product_with_backoff)
    success, error = await adapter._poll_product_until_expected_connected(
        client=None,
        product_id="product-1",
        expected_template_variant_ids={"v1"},
        expected_variant_count=1,
    )
    assert success is True
    assert error is None


@pytest.mark.asyncio
async def test_gelato_create_payload_normalizes_tags_and_keeps_draft_visibility(monkeypatch) -> None:
    adapter = GelatoAdapter({"api_key": "key", "store_id": "store-1"})
    captured: dict[str, object] = {}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fake_post_with_backoff(_client, *, endpoint: str, payload: dict[str, object], timeout: float, action: str):
        captured["endpoint"] = endpoint
        captured["payload"] = payload
        request = httpx.Request("POST", f"https://ecommerce.gelatoapis.com{endpoint}")
        return httpx.Response(200, json={"id": "product-1", "externalId": "ext-1"}, request=request)

    async def fake_poll_product_until_expected_connected(_client, *, product_id: str, expected_template_variant_ids: set[str], expected_variant_count: int):
        assert product_id == "product-1"
        assert expected_template_variant_ids == {"v1"}
        assert expected_variant_count == 1
        return True, None

    async def fake_get_product_with_backoff(_client, *, product_id: str):
        return {"id": product_id, "status": "created", "variants": []}

    monkeypatch.setattr(adapter, "_get_client", lambda: DummyClient())
    monkeypatch.setattr(adapter, "_post_with_backoff", fake_post_with_backoff)
    monkeypatch.setattr(adapter, "_poll_product_until_expected_connected", fake_poll_product_until_expected_connected)
    monkeypatch.setattr(adapter, "_get_product_with_backoff", fake_get_product_with_backoff)

    await adapter.create_provider_product(
        ProviderProductCreateInput(
            product_id="draft-1",
            blueprint_id="bp-1",
            provider="gelato",
            provider_store_id="store-1",
            reference_type="gelato_template_id",
            reference_value="template-1",
            provider_resource_id="template-1",
            provider_snapshot_json={
                "productType": "Framed Poster",
                "vendor": "Gelato",
                "variants": [{"id": "v1", "imagePlaceholders": [{"name": "ImageFront"}]}],
            },
            placement_config_json={"design_placeholder_names": ["ImageFront"]},
            design_asset_url="https://storage.test/design.png",
            title="Poster Listing",
            description="Poster description",
            tags=[
                "#neutral decor",
                "NEUTRAL decor",
                "abcdefghijklmnopqrstuvwxyz",
                "  wall   art  ",
                "wall art",
                "minimalist!!!",
            ],
        )
    )

    assert captured["endpoint"] == "/v1/stores/store-1/products:create-from-template"
    payload = captured["payload"]
    assert payload["isVisibleInTheOnlineStore"] is False
    assert payload["tags"] == [
        "neutral decor",
        "abcdefghijklmnopqrst",
        "wall art",
        "minimalist",
    ]


def test_storage_upload_uses_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def put_object(self, **kwargs):
            captured["put"] = kwargs

        def generate_presigned_url(self, _operation, *, Params, ExpiresIn):
            return f"https://signed.test/{Params['Key']}?ttl={ExpiresIn}"

    service = S3StorageService()
    monkeypatch.setattr(service, "is_configured", lambda: True)
    monkeypatch.setattr(service, "_client", lambda: FakeClient())
    service.bucket_name = "velora-assets"
    stored = service.upload_file(
        storage_key="design-assets/test.png",
        file=BytesIO(b"1234"),
        size_bytes=4,
        checksum="checksum",
        content_type="image/png",
        file_name='../../bad\r\nname".png',
    )
    assert captured["put"]["Bucket"] == "velora-assets"
    assert captured["put"]["ContentDisposition"] == 'inline; filename="bad_name_.png"'
    assert captured["put"]["CacheControl"] == "private, max-age=300, no-transform"
    assert "ACL" not in captured["put"]
    assert stored.public_url.startswith("https://signed.test/")


def test_alembic_upgrade_and_downgrade(tmp_path) -> None:
    db_path = tmp_path / "migration-test.db"
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "20260714_0010")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organizations "
                "(id, auth_provider, name, created_at, updated_at) VALUES "
                "('migration-org', 'local', 'Migration Organization', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO sync_jobs "
                "(id, organization_id, job_type, status, created_at, updated_at) VALUES "
                "('legacy-running', 'migration-org', 'order_sync', 'running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "('legacy-pending', 'migration-org', 'order_sync', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(alembic_cfg, "20260716_0012")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_store_connections "
                "(id, organization_id, provider, provider_store_id, storefront_type, "
                "storefront_display_name, label, status, credential_key, raw_data_json, "
                "created_at, updated_at) VALUES "
                "('legacy-store', 'migration-org', 'printify', 'store-1', 'etsy', "
                "'Migration Store', 'Migration Store', 'connected', 'default', "
                "'{\"marketplace\": {\"shopId\": \"safe-etsy-shop\"}, "
                "\"order\": {\"firstName\": \"Private\", "
                "\"customerReferenceId\": \"private-customer\"}}', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO product_blueprints "
                "(id, organization_id, provider, provider_store_connection_id, name, category, "
                "status, reference_type, reference_value, created_at, updated_at) VALUES "
                "('legacy-blueprint', 'migration-org', 'printify', 'legacy-store', 'Migration Shirt', "
                "'shirt', 'active', 'provider_product', 'blueprint-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO design_assets "
                "(id, organization_id, file_name, content_type, size_bytes, storage_key, created_at, updated_at) VALUES "
                "('legacy-asset', 'migration-org', 'design.png', 'image/png', 4, "
                "'migration/design.png', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO provider_product_drafts "
                "(id, organization_id, blueprint_id, provider, provider_store_connection_id, design_asset_id, "
                "status, validation_status, publishing_status, title, revision, created_at, updated_at) VALUES "
                "('legacy-draft', 'migration-org', 'legacy-blueprint', 'printify', 'legacy-store', "
                "'legacy-asset', 'ready', 'valid', 'running', 'Migration Product', 2, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO publishing_jobs "
                "(id, organization_id, blueprint_id, provider_product_draft_id, provider, "
                "provider_store_connection_id, status, retry_count, started_at, created_at, updated_at) VALUES "
                "('legacy-publish', 'migration-org', 'legacy-blueprint', 'legacy-draft', 'printify', "
                "'legacy-store', 'running', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    command.upgrade(alembic_cfg, "head")
    inspector = inspect(engine)
    assert "provider_store_connections" in inspector.get_table_names()
    assert "organization_join_requests" in inspector.get_table_names()
    assert "publishing_outbox" in inspector.get_table_names()
    sync_job_columns = {column["name"] for column in inspector.get_columns("sync_jobs")}
    assert {
        "scope_key",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "attempt_count",
        "max_attempts",
        "available_at",
        "result_json",
    } <= sync_job_columns
    sync_job_indexes = {index["name"] for index in inspector.get_indexes("sync_jobs")}
    assert "uq_sync_jobs_active_scope" in sync_job_indexes
    publishing_job_columns = {
        column["name"] for column in inspector.get_columns("publishing_jobs")
    }
    assert {
        "sync_job_id",
        "operation",
        "product_revision",
        "idempotency_key",
        "submitted_snapshot_json",
        "provider_product_id",
        "stage",
    } <= publishing_job_columns
    publishing_job_indexes = {
        index["name"] for index in inspector.get_indexes("publishing_jobs")
    }
    assert "uq_publishing_jobs_active_scope" in publishing_job_indexes
    connection_columns = {
        column["name"] for column in inspector.get_columns("provider_store_connections")
    }
    assert {
        "order_sync_cursor_json",
        "order_sync_watermark_at",
        "order_sync_last_success_at",
        "deleted_at",
    } <= connection_columns
    order_foreign_keys = {
        constraint["name"] for constraint in inspector.get_foreign_keys("orders")
    }
    assert "fk_orders_org_store" in order_foreign_keys
    draft_foreign_keys = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("provider_product_drafts")
    }
    assert {
        "fk_provider_product_drafts_org_blueprint",
        "fk_provider_product_drafts_org_store",
        "fk_provider_product_drafts_org_design_asset",
        "fk_provider_product_drafts_org_last_ai_generation",
    } <= draft_foreign_keys
    draft_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("provider_product_drafts")
    }
    assert {
        "ck_provider_product_drafts_status",
        "ck_provider_product_drafts_validation_status",
        "ck_provider_product_drafts_publishing_status",
        "ck_provider_product_drafts_revision_positive",
    } <= draft_checks
    with engine.connect() as connection:
        migrated_jobs = {
            row.id: row
            for row in connection.execute(
                text(
                    "SELECT id, status, scope_key, lease_owner, attempt_count, max_attempts "
                    "FROM sync_jobs WHERE id IN ('legacy-running', 'legacy-pending')"
                )
            ).mappings()
        }
    assert migrated_jobs["legacy-running"]["status"] == "leased"
    assert migrated_jobs["legacy-running"]["scope_key"] == "legacy:legacy-running"
    assert migrated_jobs["legacy-running"]["lease_owner"] == "legacy-migration"
    assert migrated_jobs["legacy-running"]["attempt_count"] == 1
    assert migrated_jobs["legacy-running"]["max_attempts"] == 1
    assert migrated_jobs["legacy-pending"]["status"] == "failed"
    with engine.connect() as connection:
        retired_publish = connection.execute(
            text(
                "SELECT status, sync_job_id, operation, product_revision, idempotency_key, "
                "submitted_snapshot_json, error_message FROM publishing_jobs "
                "WHERE id = 'legacy-publish'"
            )
        ).mappings().one()
        retired_sync = connection.execute(
            text(
                "SELECT status, job_type, scope_key, attempt_count, completed_at "
                "FROM sync_jobs WHERE id = :sync_job_id"
            ),
            {"sync_job_id": retired_publish["sync_job_id"]},
        ).mappings().one()
        outbox_count = connection.scalar(text("SELECT COUNT(*) FROM publishing_outbox"))
        normalized_draft = connection.execute(
            text(
                "SELECT validation_status, publishing_status "
                "FROM provider_product_drafts WHERE id = 'legacy-draft'"
            )
        ).mappings().one()
        scrubbed_store = connection.execute(
            text(
                "SELECT etsy_shop_id, raw_data_json "
                "FROM provider_store_connections WHERE id = 'legacy-store'"
            )
        ).mappings().one()
    assert retired_publish["status"] == "failed"
    assert retired_publish["operation"] == "create"
    assert retired_publish["product_revision"] == 2
    assert len(retired_publish["idempotency_key"]) == 64
    assert "retired_during_migration" in retired_publish["submitted_snapshot_json"]
    assert "retired" in retired_publish["error_message"].lower()
    assert retired_sync["status"] == "failed"
    assert retired_sync["job_type"] == "product_publish"
    assert retired_sync["scope_key"] == "legacy-publish:legacy-publish"
    assert retired_sync["attempt_count"] == 1
    assert retired_sync["completed_at"] is not None
    assert outbox_count == 0
    assert normalized_draft["validation_status"] == "validated"
    assert normalized_draft["publishing_status"] == "failed"
    assert scrubbed_store["etsy_shop_id"] == "safe-etsy-shop"
    assert scrubbed_store["raw_data_json"] is None
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = ON"))
        connection.execute(
            text(
                "INSERT INTO organizations "
                "(id, auth_provider, name, created_at, updated_at) VALUES "
                "('other-org', 'local', 'Other Organization', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO product_blueprints "
                    "(id, organization_id, provider, provider_store_connection_id, name, "
                    "category, status, reference_type, reference_value, variant_count, "
                    "created_at, updated_at) VALUES "
                    "('cross-org-blueprint', 'other-org', 'printify', 'legacy-store', "
                    "'Cross Org', 'shirt', 'draft', 'provider_product', 'cross-org', 0, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = ON"))
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, auth_provider, created_at, updated_at) VALUES "
                "('single-org-user', 'local', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO memberships "
                "(id, organization_id, user_id, role, created_at, updated_at) VALUES "
                "('membership-one', 'migration-org', 'single-org-user', 'member', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO memberships "
                    "(id, organization_id, user_id, role, created_at, updated_at) VALUES "
                    "('membership-two', 'other-org', 'single-org-user', 'member', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    command.downgrade(alembic_cfg, "base")
    with engine.connect() as connection:
        remaining_tables = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    user_tables = {row[0] for row in remaining_tables if not row[0].startswith("sqlite_")}
    assert user_tables <= {"alembic_version"}
