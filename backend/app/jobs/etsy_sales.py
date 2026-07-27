from __future__ import annotations

from datetime import timedelta
import logging
import os
import socket
import uuid

import dramatiq
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger, log_event, reset_request_id, set_request_id
from app.db.database import (
    WorkerSessionLocal as SessionLocal,
    assert_configured_worker_database_role,
)
from app.db.models import ProviderStoreConnection
from app.db.tenant_context import set_database_request_context
from app.jobs.broker import broker
from app.services.etsy_sales import sync_etsy_marketplace_sales
from app.services.sync_job_lifecycle import (
    claim_sync_job,
    enqueue_sync_job,
    finish_sync_job,
    mark_sync_job_running,
    reap_expired_sync_jobs,
    retry_sync_job,
)


etsy_sales_logger = get_logger("etsy_sales_jobs")
ETSY_SALES_JOB_TYPE = "marketplace_sales_sync"
ETSY_SALES_SCOPE_KEY = "etsy:organization"


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


def _set_tenant_context(session, organization_id: str) -> None:
    set_database_request_context(
        session,
        actor_id=None,
        organization_id=organization_id,
    )


def run_etsy_sales_sync(job_id: str, organization_id: str) -> None:
    assert_configured_worker_database_role()
    token = set_request_id(f"etsy_sales_job_{job_id}")
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
                _set_tenant_context(session, organization_id)
                result = sync_etsy_marketplace_sales(
                    session,
                    organization_id=organization_id,
                )
        except Exception as exc:
            with SessionLocal() as session:
                retried = retry_sync_job(
                    session,
                    job_id=job_id,
                    lease_owner=lease_owner,
                    error_message=f"{type(exc).__name__}: Etsy sales sync failed.",
                )
            log_event(
                etsy_sales_logger,
                "etsy_sales.sync.failed",
                level=logging.ERROR,
                job_id=job_id,
                organization_id=organization_id,
                error_type=type(exc).__name__,
                will_retry=bool(retried is not None and retried.status == "queued"),
            )
            if retried is not None and retried.status == "queued":
                sync_etsy_sales.send(job_id, organization_id)
            return

        terminal_status = {
            "blocked": "failed",
            "partial": "partial",
        }.get(result.outcome, "completed")
        with SessionLocal() as session:
            finish_sync_job(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                status=terminal_status,
                result_json=result.to_result_json(),
                error_message=result.blocker,
            )
        log_event(
            etsy_sales_logger,
            f"etsy_sales.sync.{terminal_status}",
            level=logging.WARNING if terminal_status == "partial" else logging.INFO,
            job_id=job_id,
            organization_id=organization_id,
            **result.to_result_json(),
        )
    finally:
        reset_request_id(token)


@dramatiq.actor
def sync_etsy_sales(job_id: str, organization_id: str) -> None:
    run_etsy_sales_sync(job_id, organization_id)


@dramatiq.actor
def enqueue_due_etsy_sales_syncs() -> None:
    assert_configured_worker_database_role()
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
            _set_tenant_context(session, organization_id)
            result = enqueue_sync_job(
                session,
                organization_id=organization_id,
                job_type=ETSY_SALES_JOB_TYPE,
                scope_key=ETSY_SALES_SCOPE_KEY,
                provider="etsy",
                minimum_interval=timedelta(
                    seconds=settings.commerce_sync_interval_seconds
                ),
            )
        if result.job.status == "queued":
            sync_etsy_sales.send(result.job.id, organization_id)
            dispatched_count += 1

    log_event(
        etsy_sales_logger,
        "etsy_sales.scheduler_dispatch.completed",
        organization_count=len(organization_ids),
        dispatched_count=dispatched_count,
    )


@dramatiq.actor
def reap_expired_etsy_sales_syncs() -> None:
    assert_configured_worker_database_role()
    with SessionLocal() as session:
        result = reap_expired_sync_jobs(session, job_type=ETSY_SALES_JOB_TYPE)
    for job_id, organization_id in result.requeued:
        sync_etsy_sales.send(job_id, organization_id)
    log_event(
        etsy_sales_logger,
        "etsy_sales.reaper_completed",
        requeued_count=len(result.requeued),
        failed_count=len(result.failed),
    )
