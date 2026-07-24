from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
import socket
import uuid

import dramatiq
from fastapi import HTTPException
from sqlalchemy import select

from app.core.logging import get_logger, log_event, reset_request_id, set_request_id
from app.db.database import (
    WorkerSessionLocal as SessionLocal,
    assert_configured_worker_database_role,
)
from app.db.models import ProviderProductDraft, PublishingJob, PublishingOutbox, SyncJob
from app.db.tenant_context import set_database_request_context
from app.services.publishing import execute_publishing_job
from app.services.publishing_outbox import (
    claim_publishing_outbox,
    mark_publishing_outbox_dispatched,
    release_publishing_outbox_claim,
)
from app.services.publishing_policy import PublishingStageError
from app.services.sync_job_lifecycle import (
    claim_sync_job,
    finish_sync_job,
    mark_sync_job_running,
    reap_expired_sync_jobs,
    retry_sync_job,
)
from app.jobs.broker import broker

publishing_job_logger = get_logger("publishing_jobs")
DISPATCH_RECOVERY_AGE = timedelta(minutes=5)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


def _publishing_error_summary(error: Exception) -> str:
    stage = error.stage if isinstance(error, PublishingStageError) else "publishing"
    cause = error.cause if isinstance(error, PublishingStageError) else error
    if isinstance(cause, HTTPException):
        detail = cause.detail
        message = detail if isinstance(detail, str) else json.dumps(detail, default=str)
    else:
        message = str(cause) or type(cause).__name__
    message = " ".join(message.split())
    message = re.sub(
        r"(?i)(authorization|api[-_]?key|api[-_]?token|access[-_]?token|refresh[-_]?token|secret|password)(\s*[:=]\s*)[^,}\s]+",
        r"\1\2[redacted]",
        message,
    )
    message = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~-]+", "Bearer [redacted]", message)
    return f"{stage}: {message}"[:1000]


def dispatch_publishing_outbox(*, publishing_job_id: str | None = None) -> int:
    with SessionLocal() as session:
        claims = claim_publishing_outbox(
            session,
            publishing_job_id=publishing_job_id,
        )
    dispatched_count = 0
    for claim in claims:
        try:
            publish_product.send(claim.publishing_job_id)
        except Exception as exc:
            with SessionLocal() as session:
                release_publishing_outbox_claim(
                    session,
                    claim=claim,
                    error_message=f"{type(exc).__name__}: broker dispatch failed",
                )
            log_event(
                publishing_job_logger,
                "publishing.outbox.dispatch_failed",
                level=logging.ERROR,
                publishing_job_id=claim.publishing_job_id,
                error_type=type(exc).__name__,
            )
            continue
        dispatched_count += 1
        with SessionLocal() as session:
            mark_publishing_outbox_dispatched(session, claim=claim)
    return dispatched_count


def _acknowledge_publishing_dispatch(*, publishing_job_id: str) -> None:
    """Let a fast worker close the outbox dispatch race before the sender marks it."""
    with SessionLocal() as session:
        outbox = session.scalar(
            select(PublishingOutbox)
            .where(PublishingOutbox.publishing_job_id == publishing_job_id)
            .with_for_update()
        )
        if outbox is None:
            session.rollback()
            return
        outbox.status = "dispatched"
        outbox.dispatched_at = outbox.dispatched_at or _utc_now()
        outbox.lease_owner = None
        outbox.lease_expires_at = None
        outbox.last_error = None
        session.commit()


def _set_publishing_running(*, publishing_job_id: str, status: str, attempt_count: int) -> None:
    with SessionLocal() as session:
        job = session.scalar(
            select(PublishingJob).where(PublishingJob.id == publishing_job_id).with_for_update()
        )
        if job is None:
            session.rollback()
            return
        job.status = status
        job.retry_count = max(attempt_count - 1, 0)
        job.started_at = job.started_at or _utc_now()
        job.error_message = None
        set_database_request_context(
            session,
            actor_id=None,
            organization_id=job.organization_id,
        )
        draft = session.scalar(
            select(ProviderProductDraft).where(
                ProviderProductDraft.id == job.provider_product_draft_id
            )
        )
        if draft is not None:
            draft.publishing_status = "publishing"
        session.commit()


def _record_publish_failure(
    *,
    publishing_job_id: str,
    sync_job: SyncJob | None,
    error_message: str,
) -> None:
    with SessionLocal() as session:
        job = session.scalar(
            select(PublishingJob).where(PublishingJob.id == publishing_job_id).with_for_update()
        )
        if job is None:
            session.rollback()
            return
        set_database_request_context(
            session,
            actor_id=None,
            organization_id=job.organization_id,
        )
        draft = session.scalar(
            select(ProviderProductDraft).where(
                ProviderProductDraft.id == job.provider_product_draft_id
            )
        )
        job.retry_count = sync_job.attempt_count if sync_job is not None else job.retry_count + 1
        job.error_message = error_message
        if sync_job is not None and sync_job.status == "queued":
            job.status = "queued"
            job.completed_at = None
            if draft is not None:
                draft.publishing_status = "queued"
            outbox = session.scalar(
                select(PublishingOutbox)
                .where(PublishingOutbox.publishing_job_id == publishing_job_id)
                .with_for_update()
            )
            if outbox is not None:
                outbox.status = "pending"
                outbox.available_at = _utc_now()
                outbox.lease_owner = None
                outbox.lease_expires_at = None
                outbox.dispatched_at = None
        else:
            job.status = "failed"
            job.completed_at = _utc_now()
            if draft is not None:
                draft.publishing_status = "failed"
                draft.status = "ready"
        session.commit()


def run_publishing_job(publishing_job_id: str) -> None:
    assert_configured_worker_database_role()
    token = set_request_id(f"publishing_job_{publishing_job_id}")
    lease_owner = _lease_owner()
    try:
        _acknowledge_publishing_dispatch(publishing_job_id=publishing_job_id)
        with SessionLocal() as session:
            publishing_job = session.scalar(
                select(PublishingJob).where(PublishingJob.id == publishing_job_id)
            )
            if publishing_job is None:
                return
            sync_job_id = publishing_job.sync_job_id
        with SessionLocal() as session:
            sync_job = claim_sync_job(
                session,
                job_id=sync_job_id,
                lease_owner=lease_owner,
            )
        if sync_job is None:
            log_event(
                publishing_job_logger,
                "publishing.job.claim_skipped",
                publishing_job_id=publishing_job_id,
            )
            return
        _set_publishing_running(
            publishing_job_id=publishing_job_id,
            status="leased",
            attempt_count=sync_job.attempt_count,
        )
        with SessionLocal() as session:
            running_job = mark_sync_job_running(
                session,
                job_id=sync_job_id,
                lease_owner=lease_owner,
            )
        if running_job is None:
            return
        _set_publishing_running(
            publishing_job_id=publishing_job_id,
            status="running",
            attempt_count=running_job.attempt_count,
        )
        try:
            result = asyncio.run(
                execute_publishing_job(
                    publishing_job_id,
                    lease_owner=lease_owner,
                )
            )
        except Exception as exc:
            error_summary = _publishing_error_summary(exc)
            with SessionLocal() as session:
                retried_job = retry_sync_job(
                    session,
                    job_id=sync_job_id,
                    lease_owner=lease_owner,
                    error_message=error_summary,
                )
            _record_publish_failure(
                publishing_job_id=publishing_job_id,
                sync_job=retried_job,
                error_message=error_summary,
            )
            log_event(
                publishing_job_logger,
                "publishing.job.failed",
                level=logging.ERROR,
                publishing_job_id=publishing_job_id,
                error_type=type(exc).__name__,
                error_message=error_summary,
                will_retry=bool(retried_job is not None and retried_job.status == "queued"),
            )
            if retried_job is not None and retried_job.status == "queued":
                dispatch_publishing_outbox(publishing_job_id=publishing_job_id)
            return

        with SessionLocal() as session:
            completed = finish_sync_job(
                session,
                job_id=sync_job_id,
                lease_owner=lease_owner,
                status="completed",
                result_json=result,
            )
        if completed is None:
            log_event(
                publishing_job_logger,
                "publishing.job.completion_lease_lost",
                level=logging.WARNING,
                publishing_job_id=publishing_job_id,
            )
    finally:
        reset_request_id(token)


def _recover_stale_dispatched_outbox() -> int:
    recovery_before = _utc_now() - DISPATCH_RECOVERY_AGE
    with SessionLocal() as session:
        rows = session.scalars(
            select(PublishingOutbox)
            .join(PublishingJob, PublishingJob.id == PublishingOutbox.publishing_job_id)
            .join(SyncJob, SyncJob.id == PublishingJob.sync_job_id)
            .where(
                PublishingOutbox.status == "dispatched",
                PublishingOutbox.dispatched_at.is_not(None),
                PublishingOutbox.dispatched_at <= recovery_before,
                PublishingJob.status == "queued",
                SyncJob.status == "queued",
            )
            .order_by(PublishingOutbox.dispatched_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.status = "pending"
            row.available_at = _utc_now()
            row.dispatched_at = None
        session.commit()
        return len(rows)


@dramatiq.actor
def publish_product(publishing_job_id: str) -> None:
    run_publishing_job(publishing_job_id)


@dramatiq.actor
def dispatch_pending_publishing_outbox() -> None:
    assert_configured_worker_database_role()
    recovered_count = _recover_stale_dispatched_outbox()
    dispatched_count = dispatch_publishing_outbox()
    log_event(
        publishing_job_logger,
        "publishing.outbox.sweep_completed",
        recovered_count=recovered_count,
        dispatched_count=dispatched_count,
    )


@dramatiq.actor
def reap_expired_publishing_jobs() -> None:
    assert_configured_worker_database_role()
    with SessionLocal() as session:
        result = reap_expired_sync_jobs(session, job_type="product_publish")
    with SessionLocal() as session:
        for sync_job_id, _organization_id in result.requeued:
            job = session.scalar(
                select(PublishingJob).where(PublishingJob.sync_job_id == sync_job_id)
            )
            if job is None:
                continue
            job.status = "queued"
            job.error_message = "Worker lease expired; publishing queued for retry."
            outbox = session.scalar(
                select(PublishingOutbox).where(
                    PublishingOutbox.publishing_job_id == job.id
                )
            )
            if outbox is not None:
                outbox.status = "pending"
                outbox.available_at = _utc_now()
                outbox.lease_owner = None
                outbox.lease_expires_at = None
                outbox.dispatched_at = None
        for sync_job_id in result.failed:
            job = session.scalar(
                select(PublishingJob).where(PublishingJob.sync_job_id == sync_job_id)
            )
            if job is None:
                continue
            job.status = "failed"
            job.completed_at = _utc_now()
            job.error_message = "Worker lease expired and retry attempts were exhausted."
            set_database_request_context(
                session,
                actor_id=None,
                organization_id=job.organization_id,
            )
            draft = session.scalar(
                select(ProviderProductDraft).where(
                    ProviderProductDraft.id == job.provider_product_draft_id
                )
            )
            if draft is not None:
                draft.publishing_status = "failed"
                draft.status = "ready"
        session.commit()
    dispatch_publishing_outbox()
    log_event(
        publishing_job_logger,
        "publishing.job.reaper_completed",
        requeued_count=len(result.requeued),
        failed_count=len(result.failed),
    )
