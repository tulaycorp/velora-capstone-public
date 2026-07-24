from __future__ import annotations

import asyncio
from datetime import timedelta
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
from app.services.orders import ConnectionSyncResult, OrderSyncInterruptedError, execute_connection_sync
from app.services.sync_job_lifecycle import (
    claim_sync_job,
    enqueue_sync_job,
    finish_sync_job,
    heartbeat_sync_job,
    mark_sync_job_running,
    reap_expired_sync_jobs,
)
from app.jobs.broker import broker

orders_job_logger = get_logger("orders_jobs")


class SyncJobLeaseLostError(RuntimeError):
    pass


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


def _run_org_order_sync(job_id: str, org_id: str) -> None:
    lease_owner = _lease_owner()
    with SessionLocal() as session:
        job = claim_sync_job(session, job_id=job_id, lease_owner=lease_owner)
        if job is None:
            log_event(
                orders_job_logger,
                "orders.sync_job.claim_skipped",
                job_id=job_id,
                organization_id=org_id,
            )
            return
        if mark_sync_job_running(session, job_id=job_id, lease_owner=lease_owner) is None:
            log_event(
                orders_job_logger,
                "orders.sync_job.lease_lost",
                level=30,
                job_id=job_id,
                organization_id=org_id,
            )
            return

    connection_results: list[ConnectionSyncResult] = []
    try:
        with SessionLocal() as session:
            connection_ids = session.execute(
                select(ProviderStoreConnection.id).where(
                    ProviderStoreConnection.organization_id == org_id,
                    ProviderStoreConnection.status == "connected",
                    ProviderStoreConnection.deleted_at.is_(None),
                )
            ).scalars().all()

        log_event(
            orders_job_logger,
            "orders.sync_job.started",
            job_id=job_id,
            organization_id=org_id,
            provider_store_connection_count=len(connection_ids),
        )

        def heartbeat() -> bool:
            with SessionLocal() as heartbeat_session:
                return heartbeat_sync_job(
                    heartbeat_session,
                    job_id=job_id,
                    lease_owner=lease_owner,
                )

        for connection_id in connection_ids:
            if not heartbeat():
                raise SyncJobLeaseLostError("Sync job lease was lost before connection processing.")
            try:
                connection_result = asyncio.run(
                    execute_connection_sync(job_id, connection_id, heartbeat=heartbeat)
                )
            except OrderSyncInterruptedError:
                raise
            except Exception as exc:
                log_event(
                    orders_job_logger,
                    "orders.connection_sync.failed",
                    level=40,
                    job_id=job_id,
                    organization_id=org_id,
                    provider_store_connection_id=connection_id,
                    error_type=type(exc).__name__,
                )
                connection_result = ConnectionSyncResult(
                    connection_id=connection_id,
                    provider=None,
                    outcome="failed",
                    failed=1,
                    failure_summaries=[
                        {"code": "connection_sync_failed", "count": 1, "error_type": type(exc).__name__}
                    ],
                )
            connection_results.append(connection_result)
            if not heartbeat():
                raise SyncJobLeaseLostError("Sync job lease was lost after connection processing.")

        totals = {
            metric: sum(getattr(result, metric) for result in connection_results)
            for metric in ("pages", "fetched", "inserted", "updated", "skipped", "failed")
        }
        processed_connection_count = len(connection_results)
        useful_connection_count = sum(result.useful_scope_completed for result in connection_results)
        failed_connection_count = sum(result.outcome == "failed" for result in connection_results)
        partial_connection_count = sum(result.outcome == "partial" for result in connection_results)
        if connection_results and useful_connection_count == 0:
            terminal_status = "failed"
        elif failed_connection_count or partial_connection_count or totals["failed"]:
            terminal_status = "partial"
        else:
            terminal_status = "completed"

        result_json = {
            "connections": {
                "total": len(connection_ids),
                "processed": processed_connection_count,
                "useful": useful_connection_count,
                "partial": partial_connection_count,
                "failed": failed_connection_count,
            },
            "orders": totals,
            "connection_results": [result.to_result_json() for result in connection_results],
            "last_successful_at": max(
                (
                    result.last_successful_at
                    for result in connection_results
                    if result.last_successful_at is not None
                ),
                default=None,
            ).isoformat()
            if any(result.last_successful_at is not None for result in connection_results)
            else None,
        }

        with SessionLocal() as session:
            completed_job = finish_sync_job(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                status=terminal_status,
                result_json=result_json,
                error_message=(
                    "Order sync completed with provider or item failures."
                    if terminal_status == "partial" and totals["failed"] > 0
                    else "Order sync stopped after bounded progress and will resume from its saved cursor."
                    if terminal_status == "partial"
                    else "Order sync failed before any connection completed useful work."
                    if terminal_status == "failed"
                    else None
                ),
            )
        if completed_job is None:
            raise SyncJobLeaseLostError("Sync job lease was lost before completion.")
        log_event(
            orders_job_logger,
            f"orders.sync_job.{terminal_status}",
            level=30 if terminal_status == "partial" else 40 if terminal_status == "failed" else 20,
            job_id=job_id,
            organization_id=org_id,
            provider_store_connection_count=len(connection_ids),
            processed_connection_count=processed_connection_count,
            failed_order_count=totals["failed"],
        )
    except Exception as exc:
        log_event(
            orders_job_logger,
            "orders.sync_job.failed",
            level=40,
            job_id=job_id,
            organization_id=org_id,
            error_type=type(exc).__name__,
        )
        with SessionLocal() as session:
            finish_sync_job(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                status="failed",
                result_json={
                    "connections": {
                        "processed": len(connection_results),
                    }
                },
                error_message=f"{type(exc).__name__}: order sync worker failed.",
            )


def run_order_sync_background(job_id: str, org_id: str) -> None:
    assert_configured_worker_database_role()
    token = set_request_id(f"sync_job_{job_id}")
    try:
        _run_org_order_sync(job_id, org_id)
    finally:
        reset_request_id(token)


@dramatiq.actor
def sync_org_orders(job_id: str, org_id: str) -> None:
    run_order_sync_background(job_id, org_id)


@dramatiq.actor
def sync_all_provider_orders() -> None:
    assert_configured_worker_database_role()
    token = set_request_id("scheduler_job_all_orgs")
    try:
        with SessionLocal() as session:
            organization_ids = session.execute(
                select(ProviderStoreConnection.organization_id)
                .where(
                    ProviderStoreConnection.status == "connected",
                    ProviderStoreConnection.deleted_at.is_(None),
                )
                .distinct()
            ).scalars().all()
        log_event(
            orders_job_logger,
            "orders.scheduler_dispatch.started",
            organization_count=len(organization_ids),
        )
        dispatched_count = 0
        for organization_id in organization_ids:
            with SessionLocal() as session:
                result = enqueue_sync_job(
                    session,
                    organization_id=organization_id,
                    job_type="order_sync",
                    minimum_interval=timedelta(seconds=settings.commerce_sync_interval_seconds),
                )
            if result.created:
                sync_org_orders.send(result.job.id, organization_id)
                dispatched_count += 1
        log_event(
            orders_job_logger,
            "orders.scheduler_dispatch.completed",
            organization_count=len(organization_ids),
            dispatched_count=dispatched_count,
        )
    finally:
        reset_request_id(token)


@dramatiq.actor
def reap_expired_order_sync_jobs() -> None:
    assert_configured_worker_database_role()
    token = set_request_id("scheduler_job_sync_reaper")
    try:
        with SessionLocal() as session:
            result = reap_expired_sync_jobs(session, job_type="order_sync")
        for job_id, organization_id in result.requeued:
            sync_org_orders.send(job_id, organization_id)
        log_event(
            orders_job_logger,
            "orders.sync_job.reaper_completed",
            requeued_count=len(result.requeued),
            failed_count=len(result.failed),
        )
    finally:
        reset_request_id(token)
