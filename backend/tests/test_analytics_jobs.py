from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import select

import app.jobs.analytics as analytics_jobs
import app.services.provider_connections as commerce
from app.db.encryption import encrypt_value
from app.db.models import AnalyticsSnapshot, ProviderCredential, ProviderStoreConnection, SyncJob
from app.services.sync_job_lifecycle import enqueue_sync_job


def _seed_refreshable_etsy_shop(client) -> None:
    with client.app.state.testing_session_local() as db:
        shops_row = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.organization_id == "default-org",
                ProviderCredential.provider == "etsy",
                ProviderCredential.key_name == "oauth_shops_json",
            )
        )
        assert shops_row is not None
        shops_row.encrypted_value = encrypt_value(
            json.dumps(
                [
                    {
                        "shop_id": "etsy-worker-shop",
                        "shop_name": "Worker Shop",
                        "shop_url": "https://www.etsy.com/shop/WorkerShop",
                    }
                ],
                separators=(",", ":"),
            )
        )
        db.add(
            ProviderStoreConnection(
                id="analytics-worker-store",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="analytics-worker-store",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Worker Shop",
                etsy_shop_id="etsy-worker-shop",
                status="connected",
            )
        )
        db.commit()


def test_analytics_worker_uses_leased_lifecycle_and_persists_snapshot(client, monkeypatch) -> None:
    _seed_refreshable_etsy_shop(client)
    monkeypatch.setattr(analytics_jobs, "SessionLocal", client.app.state.testing_session_local)
    monkeypatch.setattr(analytics_jobs, "assert_configured_worker_database_role", lambda: None)
    monkeypatch.setattr(commerce, "_refresh_access_token", lambda refresh_token_override=None: "access-token")
    monkeypatch.setattr(
        commerce,
        "fetch_etsy_shop",
        lambda *, access_token, shop_id: {
            "shop_id": shop_id,
            "shop_name": "Worker Shop",
            "listing_active_count": 7,
            "transaction_sold_count": 11,
            "updated_timestamp": int(datetime.now(timezone.utc).timestamp()),
        },
    )
    with client.app.state.testing_session_local() as db:
        result = enqueue_sync_job(
            db,
            organization_id="default-org",
            job_type=analytics_jobs.ANALYTICS_JOB_TYPE,
            scope_key=analytics_jobs.ANALYTICS_SCOPE_KEY,
            provider="etsy",
        )
        job_id = result.job.id

    analytics_jobs.run_analytics_refresh(job_id, "default-org")

    with client.app.state.testing_session_local() as db:
        job = db.get(SyncJob, job_id)
        snapshot = db.scalar(select(AnalyticsSnapshot))
        assert job is not None
        assert job.status == "completed"
        assert job.attempt_count == 1
        assert snapshot is not None
        assert snapshot.status == "succeeded"
        assert snapshot.payload_json["rows"][0]["active_listing_count"] == 7


def test_analytics_scheduler_reuses_one_active_refresh_job(client, monkeypatch) -> None:
    _seed_refreshable_etsy_shop(client)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(analytics_jobs, "SessionLocal", client.app.state.testing_session_local)
    monkeypatch.setattr(analytics_jobs, "assert_configured_worker_database_role", lambda: None)
    monkeypatch.setattr(
        analytics_jobs.refresh_etsy_analytics,
        "send",
        lambda job_id, organization_id: sent.append((job_id, organization_id)),
    )

    analytics_jobs.enqueue_due_analytics_refreshes.fn()
    analytics_jobs.enqueue_due_analytics_refreshes.fn()

    with client.app.state.testing_session_local() as db:
        jobs = db.scalars(
            select(SyncJob).where(SyncJob.job_type == analytics_jobs.ANALYTICS_JOB_TYPE)
        ).all()
    assert len(jobs) == 1
    assert jobs[0].status == "queued"
    assert sent == [(jobs[0].id, "default-org"), (jobs[0].id, "default-org")]
