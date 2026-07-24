from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import SyncJob
from app.services.sync_job_lifecycle import (
    claim_sync_job,
    enqueue_sync_job,
    finish_sync_job,
    heartbeat_sync_job,
    mark_sync_job_running,
    reap_expired_sync_jobs,
)


def test_enqueue_reuses_one_active_job_per_scope(client) -> None:
    with client.app.state.testing_session_local() as db:
        first = enqueue_sync_job(db, organization_id="default-org", job_type="order_sync")
        second = enqueue_sync_job(db, organization_id="default-org", job_type="order_sync")
        forced = enqueue_sync_job(
            db,
            organization_id="default-org",
            job_type="order_sync",
            force=True,
        )

    assert first.created is True
    assert second.created is False
    assert second.job.id == first.job.id
    assert second.job.status == "queued"
    assert forced.created is False
    assert forced.job.id == first.job.id


def test_enqueue_reuses_recent_terminal_job_until_minimum_interval(client) -> None:
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_local() as db:
        recent_job = SyncJob(
            id="sync-recent-terminal",
            organization_id="default-org",
            job_type="order_sync",
            status="completed",
            completed_at=now - timedelta(hours=4, minutes=59),
        )
        db.add(recent_job)
        db.commit()

        result = enqueue_sync_job(
            db,
            organization_id="default-org",
            job_type="order_sync",
            now=now,
            minimum_interval=timedelta(hours=5),
        )

    assert result.created is False
    assert result.job.id == "sync-recent-terminal"


def test_enqueue_creates_when_interval_is_due_or_forced(client) -> None:
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_local() as db:
        db.add(
            SyncJob(
                id="sync-old-terminal",
                organization_id="default-org",
                job_type="order_sync",
                status="failed",
                completed_at=now - timedelta(hours=5),
            )
        )
        db.commit()

        due = enqueue_sync_job(
            db,
            organization_id="default-org",
            job_type="order_sync",
            now=now,
            minimum_interval=timedelta(hours=5),
        )

    assert due.created is True

    with client.app.state.testing_session_local() as db:
        due.job.status = "completed"
        due.job.completed_at = now
        db.merge(due.job)
        db.commit()
        forced = enqueue_sync_job(
            db,
            organization_id="default-org",
            job_type="order_sync",
            now=now + timedelta(minutes=1),
            minimum_interval=timedelta(hours=5),
            force=True,
        )

    assert forced.created is True


def test_claim_heartbeat_completion_and_terminal_reclaim_protection(client) -> None:
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_local() as db:
        result = enqueue_sync_job(
            db,
            organization_id="default-org",
            job_type="order_sync",
            now=now,
        )
        job_id = result.job.id
        claimed = claim_sync_job(db, job_id=job_id, lease_owner="worker-a", now=now)
        assert claimed is not None
        assert claimed.status == "leased"
        assert claimed.attempt_count == 1
        assert mark_sync_job_running(db, job_id=job_id, lease_owner="worker-a") is not None
        assert heartbeat_sync_job(
            db,
            job_id=job_id,
            lease_owner="worker-a",
            now=now + timedelta(minutes=1),
        )
        completed = finish_sync_job(
            db,
            job_id=job_id,
            lease_owner="worker-a",
            status="completed",
            result_json={"connections": {"total": 1, "processed": 1}},
            now=now + timedelta(minutes=2),
        )
        reclaimed = claim_sync_job(
            db,
            job_id=job_id,
            lease_owner="worker-b",
            now=now + timedelta(minutes=3),
        )
        db.expire_all()
        completed = db.get(SyncJob, job_id)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.lease_owner is None
    assert reclaimed is None


def test_reaper_requeues_retryable_jobs_and_fails_exhausted_jobs(client) -> None:
    now = datetime.now(timezone.utc)
    expired_at = now - timedelta(minutes=1)
    with client.app.state.testing_session_local() as db:
        retryable = SyncJob(
            id="sync-retryable",
            organization_id="org-retryable",
            job_type="order_sync",
            status="running",
            scope_key="organization",
            lease_owner="dead-worker-a",
            lease_expires_at=expired_at,
            heartbeat_at=expired_at,
            attempt_count=1,
            max_attempts=3,
            available_at=expired_at,
        )
        exhausted = SyncJob(
            id="sync-exhausted",
            organization_id="org-exhausted",
            job_type="order_sync",
            status="leased",
            scope_key="organization",
            lease_owner="dead-worker-b",
            lease_expires_at=expired_at,
            heartbeat_at=expired_at,
            attempt_count=3,
            max_attempts=3,
            available_at=expired_at,
        )
        db.add_all([retryable, exhausted])
        db.commit()

        result = reap_expired_sync_jobs(db, now=now)
        db.expire_all()
        retryable = db.get(SyncJob, "sync-retryable")
        exhausted = db.get(SyncJob, "sync-exhausted")

    assert result.requeued == (("sync-retryable", "org-retryable"),)
    assert result.failed == ("sync-exhausted",)
    assert retryable is not None
    assert retryable.status == "queued"
    assert retryable.lease_owner is None
    assert exhausted is not None
    assert exhausted.status == "failed"
    assert exhausted.completed_at is not None


def test_expired_lease_cannot_be_renewed_by_stale_worker(client) -> None:
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_local() as db:
        job = SyncJob(
            id="sync-expired-heartbeat",
            organization_id="org-expired-heartbeat",
            job_type="order_sync",
            status="running",
            scope_key="organization",
            lease_owner="stale-worker",
            lease_expires_at=now - timedelta(seconds=1),
            heartbeat_at=now - timedelta(minutes=5),
            attempt_count=1,
            max_attempts=3,
            available_at=now - timedelta(minutes=5),
        )
        db.add(job)
        db.commit()

        renewed = heartbeat_sync_job(
            db,
            job_id=job.id,
            lease_owner="stale-worker",
            now=now,
        )

    assert renewed is False
