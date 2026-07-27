from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

import app.api.etsy_sales_sync as etsy_sales_dispatch
from app.db.models import SyncJob


def test_etsy_sales_run_route_reuses_active_job(client, monkeypatch) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        etsy_sales_dispatch.sync_etsy_sales,
        "send",
        lambda job_id, organization_id: sent.append((job_id, organization_id)),
    )

    first = client.post("/sync-jobs/etsy-sales/run")
    second = client.post("/sync-jobs/etsy-sales/run")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["provider"] == "etsy"
    with client.app.state.testing_session_local() as db:
        assert db.scalar(
            select(func.count(SyncJob.id)).where(
                SyncJob.job_type == "marketplace_sales_sync"
            )
        ) == 1
    assert sent == [
        (first.json()["id"], "default-org"),
        (first.json()["id"], "default-org"),
    ]


def test_etsy_sales_status_exposes_latest_attempt_and_prior_success(client) -> None:
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_local() as db:
        db.add_all(
            [
                SyncJob(
                    id="etsy-sales-success",
                    organization_id="default-org",
                    provider="etsy",
                    job_type="marketplace_sales_sync",
                    scope_key="etsy:organization",
                    status="completed",
                    result_json={"outcome": "completed", "records_imported": 4},
                    completed_at=now - timedelta(hours=2),
                ),
                SyncJob(
                    id="etsy-sales-blocked",
                    organization_id="default-org",
                    provider="etsy",
                    job_type="marketplace_sales_sync",
                    scope_key="etsy:organization",
                    status="failed",
                    result_json={"outcome": "blocked", "records_imported": 0},
                    error_message="Grant Etsy analytics access.",
                    completed_at=now - timedelta(hours=1),
                ),
            ]
        )
        db.commit()

    response = client.get("/sync-jobs/etsy-sales/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_job"]["id"] == "etsy-sales-blocked"
    assert payload["latest_job"]["result_json"]["outcome"] == "blocked"
    assert payload["last_successful_at"] is not None
