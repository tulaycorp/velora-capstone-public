from __future__ import annotations

import app.jobs.etsy_sales as etsy_sales_jobs
from app.db.models import SyncJob
from app.services.etsy_sales import EtsySalesSyncResult
from app.services.sync_job_lifecycle import enqueue_sync_job


def test_etsy_sales_worker_persists_blocked_outcome_without_retry(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        etsy_sales_jobs,
        "SessionLocal",
        client.app.state.testing_session_local,
    )
    monkeypatch.setattr(
        etsy_sales_jobs,
        "assert_configured_worker_database_role",
        lambda: None,
    )
    monkeypatch.setattr(
        etsy_sales_jobs,
        "sync_etsy_marketplace_sales",
        lambda *_args, **_kwargs: EtsySalesSyncResult(
            outcome="blocked",
            blocker="Map a connected Velora store to an Etsy shop.",
            skipped_shops=1,
        ),
    )

    with client.app.state.testing_session_local() as db:
        result = enqueue_sync_job(
            db,
            organization_id="default-org",
            job_type=etsy_sales_jobs.ETSY_SALES_JOB_TYPE,
            scope_key=etsy_sales_jobs.ETSY_SALES_SCOPE_KEY,
            provider="etsy",
        )
        job_id = result.job.id

    etsy_sales_jobs.run_etsy_sales_sync(job_id, "default-org")

    with client.app.state.testing_session_local() as db:
        job = db.get(SyncJob, job_id)

    assert job is not None
    assert job.status == "failed"
    assert job.attempt_count == 1
    assert job.result_json["outcome"] == "blocked"
    assert job.error_message == "Map a connected Velora store to an Etsy shop."
