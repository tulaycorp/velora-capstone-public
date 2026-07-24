from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.models import SyncJob

ACTIVE_SYNC_JOB_STATUSES = ("queued", "leased", "running")
TERMINAL_SYNC_JOB_STATUSES = ("completed", "partial", "failed", "cancelled")
DEFAULT_SCOPE_KEY = "organization"

lifecycle_logger = get_logger("sync_job_lifecycle")


@dataclass(frozen=True)
class EnqueueResult:
    job: SyncJob
    created: bool


@dataclass(frozen=True)
class ReapedSyncJobs:
    requeued: tuple[tuple[str, str], ...]
    failed: tuple[str, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _active_job_statement(*, organization_id: str, job_type: str, scope_key: str):
    return (
        select(SyncJob)
        .where(
            SyncJob.organization_id == organization_id,
            SyncJob.job_type == job_type,
            SyncJob.scope_key == scope_key,
            SyncJob.status.in_(ACTIVE_SYNC_JOB_STATUSES),
        )
        .order_by(SyncJob.created_at.desc())
    )


def _latest_terminal_job_statement(*, organization_id: str, job_type: str, scope_key: str):
    return (
        select(SyncJob)
        .where(
            SyncJob.organization_id == organization_id,
            SyncJob.job_type == job_type,
            SyncJob.scope_key == scope_key,
            SyncJob.status.in_(TERMINAL_SYNC_JOB_STATUSES),
        )
        .order_by(SyncJob.created_at.desc(), SyncJob.updated_at.desc())
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def enqueue_sync_job(
    db: Session,
    *,
    organization_id: str,
    job_type: str,
    scope_key: str = DEFAULT_SCOPE_KEY,
    provider: str | None = None,
    max_attempts: int | None = None,
    now: datetime | None = None,
    minimum_interval: timedelta | None = None,
    force: bool = False,
) -> EnqueueResult:
    normalized_organization_id = organization_id.strip()
    normalized_job_type = job_type.strip()
    normalized_scope_key = scope_key.strip()
    effective_max_attempts = settings.sync_job_max_attempts if max_attempts is None else max_attempts
    if not normalized_organization_id or not normalized_job_type or not normalized_scope_key:
        raise ValueError("Sync job organization, type, and scope must not be blank.")
    if not 1 <= effective_max_attempts <= 10:
        raise ValueError("Sync job max attempts must be between one and ten.")
    if minimum_interval is not None and minimum_interval < timedelta(0):
        raise ValueError("Sync job minimum interval must not be negative.")

    existing = db.execute(
        _active_job_statement(
            organization_id=normalized_organization_id,
            job_type=normalized_job_type,
            scope_key=normalized_scope_key,
        )
    ).scalars().first()
    if existing is not None:
        return EnqueueResult(job=existing, created=False)

    queued_at = now or _utc_now()
    if minimum_interval is not None and not force:
        latest_terminal = db.execute(
            _latest_terminal_job_statement(
                organization_id=normalized_organization_id,
                job_type=normalized_job_type,
                scope_key=normalized_scope_key,
            )
        ).scalars().first()
        if latest_terminal is not None:
            latest_activity_at = (
                latest_terminal.completed_at
                or latest_terminal.updated_at
                or latest_terminal.started_at
                or latest_terminal.created_at
            )
            if (
                latest_activity_at is not None
                and _as_utc(queued_at) - _as_utc(latest_activity_at) < minimum_interval
            ):
                return EnqueueResult(job=latest_terminal, created=False)

    job = SyncJob(
        organization_id=normalized_organization_id,
        provider=provider,
        job_type=normalized_job_type,
        scope_key=normalized_scope_key,
        status="queued",
        max_attempts=effective_max_attempts,
        available_at=queued_at,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            _active_job_statement(
                organization_id=normalized_organization_id,
                job_type=normalized_job_type,
                scope_key=normalized_scope_key,
            )
        ).scalars().first()
        if existing is None:
            raise
        return EnqueueResult(job=existing, created=False)

    db.refresh(job)
    log_event(
        lifecycle_logger,
        "sync_job.transition",
        job_id=job.id,
        organization_id=normalized_organization_id,
        job_type=normalized_job_type,
        from_status=None,
        to_status="queued",
        attempt_count=0,
    )
    return EnqueueResult(job=job, created=True)


def claim_sync_job(
    db: Session,
    *,
    job_id: str,
    lease_owner: str,
    now: datetime | None = None,
) -> SyncJob | None:
    claimed_at = now or _utc_now()
    job = db.execute(
        select(SyncJob)
        .where(
            SyncJob.id == job_id,
            SyncJob.status == "queued",
            SyncJob.available_at <= claimed_at,
            SyncJob.attempt_count < SyncJob.max_attempts,
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        db.rollback()
        return None

    job.status = "leased"
    job.lease_owner = lease_owner
    job.lease_expires_at = claimed_at + timedelta(seconds=settings.sync_job_lease_seconds)
    job.heartbeat_at = claimed_at
    job.attempt_count += 1
    job.started_at = job.started_at or claimed_at
    db.commit()
    db.refresh(job)
    _log_transition(job, from_status="queued", to_status="leased")
    return job


def mark_sync_job_running(db: Session, *, job_id: str, lease_owner: str) -> SyncJob | None:
    job = _owned_active_job(
        db,
        job_id=job_id,
        lease_owner=lease_owner,
        statuses=("leased",),
        active_at=_utc_now(),
    )
    if job is None:
        return None
    job.status = "running"
    db.commit()
    db.refresh(job)
    _log_transition(job, from_status="leased", to_status="running")
    return job


def heartbeat_sync_job(
    db: Session,
    *,
    job_id: str,
    lease_owner: str,
    now: datetime | None = None,
) -> bool:
    heartbeat_at = now or _utc_now()
    job = _owned_active_job(
        db,
        job_id=job_id,
        lease_owner=lease_owner,
        statuses=("leased", "running"),
        active_at=heartbeat_at,
    )
    if job is None:
        return False
    job.heartbeat_at = heartbeat_at
    job.lease_expires_at = heartbeat_at + timedelta(seconds=settings.sync_job_lease_seconds)
    db.commit()
    return True


def finish_sync_job(
    db: Session,
    *,
    job_id: str,
    lease_owner: str,
    status: str,
    result_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    now: datetime | None = None,
) -> SyncJob | None:
    if status not in TERMINAL_SYNC_JOB_STATUSES:
        raise ValueError(f"Unsupported terminal sync job status: {status}")
    finished_at = now or _utc_now()
    job = _owned_active_job(
        db,
        job_id=job_id,
        lease_owner=lease_owner,
        statuses=("leased", "running"),
        active_at=finished_at,
    )
    if job is None:
        return None
    previous_status = job.status
    job.status = status
    job.completed_at = finished_at
    job.result_json = result_json
    job.error_message = _error_summary(error_message)
    job.lease_owner = None
    job.lease_expires_at = None
    db.commit()
    db.refresh(job)
    _log_transition(job, from_status=previous_status, to_status=status)
    return job


def retry_sync_job(
    db: Session,
    *,
    job_id: str,
    lease_owner: str,
    error_message: str,
    now: datetime | None = None,
) -> SyncJob | None:
    retried_at = now or _utc_now()
    job = _owned_active_job(
        db,
        job_id=job_id,
        lease_owner=lease_owner,
        statuses=("leased", "running"),
        active_at=retried_at,
    )
    if job is None:
        return None
    previous_status = job.status
    job.error_message = _error_summary(error_message)
    job.lease_owner = None
    job.lease_expires_at = None
    if job.attempt_count < job.max_attempts:
        job.status = "queued"
        job.available_at = retried_at
        job.heartbeat_at = None
    else:
        job.status = "failed"
        job.completed_at = retried_at
    db.commit()
    db.refresh(job)
    _log_transition(
        job,
        from_status=previous_status,
        to_status=job.status,
        reason="worker_error",
    )
    return job


def reap_expired_sync_jobs(
    db: Session,
    *,
    job_type: str | None = None,
    now: datetime | None = None,
) -> ReapedSyncJobs:
    reaped_at = now or _utc_now()
    statement = (
        select(SyncJob)
        .where(
            SyncJob.status.in_(("leased", "running")),
            SyncJob.lease_expires_at.is_not(None),
            SyncJob.lease_expires_at <= reaped_at,
        )
        .order_by(SyncJob.lease_expires_at.asc())
        .limit(settings.sync_job_reaper_batch_size)
        .with_for_update(skip_locked=True)
    )
    if job_type is not None:
        statement = statement.where(SyncJob.job_type == job_type)
    jobs = db.execute(statement).scalars().all()

    requeued: list[tuple[str, str]] = []
    failed: list[str] = []
    transitions: list[tuple[SyncJob, str, str]] = []
    for job in jobs:
        previous_status = job.status
        if job.attempt_count < job.max_attempts:
            job.status = "queued"
            job.available_at = reaped_at
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.error_message = "Worker lease expired; job queued for retry."
            requeued.append((job.id, job.organization_id))
            transitions.append((job, previous_status, "queued"))
        else:
            job.status = "failed"
            job.completed_at = reaped_at
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_message = "Worker lease expired and retry attempts were exhausted."
            failed.append(job.id)
            transitions.append((job, previous_status, "failed"))

    db.commit()
    for job, previous_status, status in transitions:
        _log_transition(job, from_status=previous_status, to_status=status, reason="lease_expired")
    return ReapedSyncJobs(requeued=tuple(requeued), failed=tuple(failed))


def _owned_active_job(
    db: Session,
    *,
    job_id: str,
    lease_owner: str,
    statuses: tuple[str, ...],
    active_at: datetime,
) -> SyncJob | None:
    job = db.execute(
        select(SyncJob)
        .where(
            SyncJob.id == job_id,
            SyncJob.status.in_(statuses),
            SyncJob.lease_owner == lease_owner,
            SyncJob.lease_expires_at.is_not(None),
            SyncJob.lease_expires_at > active_at,
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        db.rollback()
    return job


def _error_summary(message: str | None) -> str | None:
    normalized = " ".join(str(message or "").split()).strip()
    return normalized[:1000] or None


def _log_transition(
    job: SyncJob,
    *,
    from_status: str,
    to_status: str,
    reason: str | None = None,
) -> None:
    log_event(
        lifecycle_logger,
        "sync_job.transition",
        job_id=job.id,
        organization_id=job.organization_id,
        job_type=job.job_type,
        from_status=from_status,
        to_status=to_status,
        attempt_count=job.attempt_count,
        reason=reason,
    )
