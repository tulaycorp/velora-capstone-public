from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import socket
import uuid

import dramatiq
from sqlalchemy import select

from app.core.logging import get_logger, log_event, reset_request_id, set_request_id
from app.db.database import (
    WorkerSessionLocal as SessionLocal,
    assert_configured_worker_database_role,
)
from app.db.models import AnalyticsSnapshot, ProviderStoreConnection
from app.db.tenant_context import set_database_request_context
from app.services.analytics import (
    ETSY_SNAPSHOT_PROVIDER,
    ETSY_SNAPSHOT_SCOPE,
    record_etsy_analytics_refresh_failure,
    refresh_etsy_analytics_snapshot,
)
from app.services.sync_job_lifecycle import (
    claim_sync_job,
    enqueue_sync_job,
    finish_sync_job,
    mark_sync_job_running,
    reap_expired_sync_jobs,
    retry_sync_job,
)
from app.jobs.broker import broker

analytics_job_logger = get_logger("analytics_jobs")
ANALYTICS_JOB_TYPE = "analytics_refresh"
ANALYTICS_SCOPE_KEY = "etsy:organization"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


def _set_worker_tenant_context(session, organization_id: str) -> None:
    set_database_request_context(
        session,
        actor_id=None,
        organization_id=organization_id,
    )


def run_analytics_refresh(job_id: str, organization_id: str) -> None:
    assert_configured_worker_database_role()
    token = set_request_id(f"analytics_job_{job_id}")
    lease_owner = _lease_owner()
    try:
        with SessionLocal() as session:
            job = claim_sync_job(session, job_id=job_id, lease_owner=lease_owner)
            if job is None:
                return
            if mark_sync_job_running(session, job_id=job_id, lease_owner=lease_owner) is None:
                return

        try:
            with SessionLocal() as session:
                _set_worker_tenant_context(session, organization_id)
                result = refresh_etsy_analytics_snapshot(
                    session,
                    organization_id=organization_id,
                )
        except Exception as exc:
            failure_summary = "Etsy analytics background refresh failed; serving the last successful snapshot."
            with SessionLocal() as session:
                _set_worker_tenant_context(session, organization_id)
                record_etsy_analytics_refresh_failure(
                    session,
                    organization_id=organization_id,
                    failure_summary=failure_summary,
                )
            with SessionLocal() as session:
                retried_job = retry_sync_job(
                    session,
                    job_id=job_id,
                    lease_owner=lease_owner,
                    error_message=f"{type(exc).__name__}: analytics refresh worker failed.",
                )
            log_event(
                analytics_job_logger,
                "analytics.refresh.failed",
                level=logging.ERROR,
                job_id=job_id,
                organization_id=organization_id,
                error_type=type(exc).__name__,
                will_retry=bool(retried_job is not None and retried_job.status == "queued"),
            )
            if retried_job is not None and retried_job.status == "queued":
                refresh_etsy_analytics.send(job_id, organization_id)
            return

        terminal_status = "completed" if result.outcome == "completed" else result.outcome
        with SessionLocal() as session:
            finish_sync_job(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                status=terminal_status,
                result_json={
                    "fetched_shop_count": result.fetched_shop_count,
                    "failed_shop_count": result.failed_shop_count,
                },
                error_message=result.failure_summary,
            )
        log_event(
            analytics_job_logger,
            f"analytics.refresh.{terminal_status}",
            level=logging.WARNING if terminal_status == "partial" else logging.ERROR if terminal_status == "failed" else logging.INFO,
            job_id=job_id,
            organization_id=organization_id,
            fetched_shop_count=result.fetched_shop_count,
            failed_shop_count=result.failed_shop_count,
        )
    finally:
        reset_request_id(token)


@dramatiq.actor
def refresh_etsy_analytics(job_id: str, organization_id: str) -> None:
    run_analytics_refresh(job_id, organization_id)


@dramatiq.actor
def enqueue_due_analytics_refreshes() -> None:
    assert_configured_worker_database_role()
    now = _utc_now()
    with SessionLocal() as session:
        organization_ids = session.scalars(
            select(ProviderStoreConnection.organization_id)
            .where(
                ProviderStoreConnection.storefront_type == "etsy",
                ProviderStoreConnection.status == "connected",
                ProviderStoreConnection.deleted_at.is_(None),
            )
            .distinct()
        ).all()

    dispatched_count = 0
    for organization_id in organization_ids:
        with SessionLocal() as session:
            _set_worker_tenant_context(session, organization_id)
            snapshot = session.scalar(
                select(AnalyticsSnapshot).where(
                    AnalyticsSnapshot.organization_id == organization_id,
                    AnalyticsSnapshot.provider == ETSY_SNAPSHOT_PROVIDER,
                    AnalyticsSnapshot.source_scope == ETSY_SNAPSHOT_SCOPE,
                )
            )
            if (
                snapshot is not None
                and snapshot.status == "succeeded"
                and snapshot.expires_at is not None
                and (_coerce_utc(snapshot.expires_at) or now) > now
            ):
                continue
            result = enqueue_sync_job(
                session,
                organization_id=organization_id,
                job_type=ANALYTICS_JOB_TYPE,
                scope_key=ANALYTICS_SCOPE_KEY,
                provider=ETSY_SNAPSHOT_PROVIDER,
            )
        if result.job.status == "queued":
            refresh_etsy_analytics.send(result.job.id, organization_id)
            dispatched_count += 1

    log_event(
        analytics_job_logger,
        "analytics.scheduler_dispatch.completed",
        organization_count=len(organization_ids),
        dispatched_count=dispatched_count,
    )


@dramatiq.actor
def reap_expired_analytics_refreshes() -> None:
    assert_configured_worker_database_role()
    with SessionLocal() as session:
        result = reap_expired_sync_jobs(session, job_type=ANALYTICS_JOB_TYPE)
    for job_id, organization_id in result.requeued:
        refresh_etsy_analytics.send(job_id, organization_id)
    log_event(
        analytics_job_logger,
        "analytics.refresh.reaper_completed",
        requeued_count=len(result.requeued),
        failed_count=len(result.failed),
    )
