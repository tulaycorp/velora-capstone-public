from __future__ import annotations

import io
import logging
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("VELORA_SECRET_ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")

import app.jobs.orders as order_jobs_module
import app.jobs.analytics as analytics_jobs_module
import app.jobs.etsy_sales as etsy_sales_jobs_module
import app.jobs.publishing as publishing_jobs_module
import app.jobs.broker as broker_module
import app.scheduler as scheduler_module
from app.core.logging import PrettyLogFormatter
from app.db.models import ProviderStoreConnection, SyncJob
from app.services.orders import ConnectionSyncResult


class DummyScheduler:
    def __init__(self) -> None:
        self.jobs: list[SimpleNamespace] = []
        self.started = False
        self.job_kwargs: list[dict[str, object]] = []

    def add_job(self, func, **kwargs) -> None:
        self.job_kwargs.append({"func": func, **kwargs})
        self.jobs.append(SimpleNamespace(id=kwargs["id"], name=kwargs["name"]))

    def get_jobs(self):
        return self.jobs

    def start(self) -> None:
        self.started = True


def test_all_background_actors_use_the_shared_broker() -> None:
    expected_actor_names = {
        "dispatch_pending_publishing_outbox",
        "publish_product",
        "reap_expired_publishing_jobs",
        "sync_org_orders",
        "sync_all_provider_orders",
        "reap_expired_order_sync_jobs",
        "sync_etsy_sales",
        "enqueue_due_etsy_sales_syncs",
        "reap_expired_etsy_sales_syncs",
        "refresh_etsy_analytics",
        "enqueue_due_analytics_refreshes",
        "reap_expired_analytics_refreshes",
    }

    assert order_jobs_module.broker is broker_module.broker
    assert publishing_jobs_module.broker is broker_module.broker
    assert analytics_jobs_module.broker is broker_module.broker
    assert etsy_sales_jobs_module.broker is broker_module.broker
    assert expected_actor_names <= set(broker_module.broker.actors)


def _capture_logger_output(logger: logging.Logger) -> tuple[io.StringIO, list[logging.Handler]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(PrettyLogFormatter())
    original_handlers = list(logger.handlers)
    logger.handlers = [handler]
    return stream, original_handlers


def test_start_scheduler_logs_before_next_run_time_exists(monkeypatch) -> None:
    scheduler = DummyScheduler()
    role_checks: list[bool] = []
    lock_handle = io.BytesIO()
    monkeypatch.setattr(scheduler_module, "BlockingScheduler", lambda: scheduler)
    monkeypatch.setattr(scheduler_module, "_acquire_scheduler_lock", lambda: lock_handle)
    monkeypatch.setattr(
        scheduler_module,
        "assert_configured_worker_database_role",
        lambda: role_checks.append(True),
    )
    stream, original_handlers = _capture_logger_output(scheduler_module.scheduler_logger)

    try:
        scheduler_module.start_scheduler()
    finally:
        scheduler_module.scheduler_logger.handlers = original_handlers

    assert scheduler.started is True
    assert role_checks == [True]
    assert [job["id"] for job in scheduler.job_kwargs] == [
        "sync_all_provider_orders",
        "reap_expired_order_sync_jobs",
        "enqueue_due_etsy_sales_syncs",
        "reap_expired_etsy_sales_syncs",
        "dispatch_pending_publishing_outbox",
        "reap_expired_publishing_jobs",
        "enqueue_due_analytics_refreshes",
        "reap_expired_analytics_refreshes",
    ]
    order_dispatch = scheduler.job_kwargs[0]
    assert order_dispatch["trigger"].interval.total_seconds() == 15 * 60
    assert order_dispatch["name"] == "Check for due provider order syncs every 15 minutes"
    output = stream.getvalue()
    assert "pending scheduler start" in output
    assert "scheduler.job.registered" in output


def test_scheduler_rejects_unsafe_role_before_registering_jobs(monkeypatch) -> None:
    scheduler_created = False

    def create_scheduler():
        nonlocal scheduler_created
        scheduler_created = True
        return DummyScheduler()

    def reject_role() -> None:
        raise RuntimeError("unsafe worker role")

    monkeypatch.setattr(scheduler_module, "BlockingScheduler", create_scheduler)
    monkeypatch.setattr(scheduler_module, "_acquire_scheduler_lock", lambda: io.BytesIO())
    monkeypatch.setattr(
        scheduler_module,
        "assert_configured_worker_database_role",
        reject_role,
    )

    with pytest.raises(RuntimeError, match="unsafe worker role"):
        scheduler_module.start_scheduler()

    assert scheduler_created is False


def test_scheduler_rejects_duplicate_process_before_registering_jobs(monkeypatch) -> None:
    scheduler_created = False

    def create_scheduler():
        nonlocal scheduler_created
        scheduler_created = True
        return DummyScheduler()

    monkeypatch.setattr(scheduler_module, "BlockingScheduler", create_scheduler)
    monkeypatch.setattr(scheduler_module, "_acquire_scheduler_lock", lambda: None)
    stream, original_handlers = _capture_logger_output(scheduler_module.scheduler_logger)

    try:
        scheduler_module.start_scheduler()
    finally:
        scheduler_module.scheduler_logger.handlers = original_handlers

    assert scheduler_created is False
    assert "scheduler.duplicate_rejected" in stream.getvalue()


def test_run_order_sync_background_logs_job_lifecycle(client, monkeypatch) -> None:
    async def fake_execute_connection_sync(job_id: str, connection_id: str, *, heartbeat):
        assert heartbeat() is True
        return ConnectionSyncResult(
            connection_id=connection_id,
            provider="printify",
            outcome="completed",
            pages=1,
            fetched=2,
            inserted=1,
            updated=1,
        )

    monkeypatch.setattr(order_jobs_module, "execute_connection_sync", fake_execute_connection_sync)
    monkeypatch.setattr(order_jobs_module, "SessionLocal", client.app.state.testing_session_local)
    stream, original_handlers = _capture_logger_output(order_jobs_module.orders_job_logger)

    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="log-connection",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="shop-log",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Log Test Shop",
                status="connected",
            )
        )
        db.add(
            SyncJob(
                id="job-log-test",
                organization_id="default-org",
                job_type="order_sync",
                status="queued",
            )
        )
        db.commit()

    try:
        order_jobs_module.run_order_sync_background("job-log-test", "default-org")
    finally:
        order_jobs_module.orders_job_logger.handlers = original_handlers

    output = stream.getvalue()
    assert "orders.sync_job.started" in output
    assert "orders.sync_job.completed" in output
    assert "job_id=job-log-test" in output

    with client.app.state.testing_session_local() as db:
        job = db.get(SyncJob, "job-log-test")

    assert job is not None
    assert job.status == "completed"
    assert job.result_json["orders"] == {
        "pages": 1,
        "fetched": 2,
        "inserted": 1,
        "updated": 1,
        "skipped": 0,
        "failed": 0,
    }


@pytest.mark.parametrize(
    ("connection_result", "expected_status"),
    [
        (
            ConnectionSyncResult(
                connection_id="outcome-connection",
                provider="printify",
                outcome="partial",
                pages=1,
                fetched=2,
                inserted=1,
                failed=1,
            ),
            "partial",
        ),
        (
            ConnectionSyncResult(
                connection_id="outcome-connection",
                provider="printify",
                outcome="failed",
                failed=1,
            ),
            "failed",
        ),
    ],
)
def test_run_order_sync_background_preserves_truthful_terminal_outcome(
    client,
    monkeypatch,
    connection_result: ConnectionSyncResult,
    expected_status: str,
) -> None:
    async def fake_execute_connection_sync(job_id: str, connection_id: str, *, heartbeat):
        assert heartbeat() is True
        return connection_result

    monkeypatch.setattr(order_jobs_module, "execute_connection_sync", fake_execute_connection_sync)
    monkeypatch.setattr(order_jobs_module, "SessionLocal", client.app.state.testing_session_local)
    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="outcome-connection",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="outcome-shop",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Outcome Test Shop",
                status="connected",
            )
        )
        db.add(
            SyncJob(
                id="outcome-job",
                organization_id="default-org",
                job_type="order_sync",
                status="queued",
            )
        )
        db.commit()

    order_jobs_module.run_order_sync_background("outcome-job", "default-org")

    with client.app.state.testing_session_local() as db:
        job = db.get(SyncJob, "outcome-job")
    assert job is not None
    assert job.status == expected_status
    assert job.result_json["connections"]["processed"] == 1
    assert job.result_json["orders"]["failed"] == 1
