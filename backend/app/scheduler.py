import os
from pathlib import Path
import tempfile
from typing import BinaryIO

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.jobs.broker import broker

from app.jobs.orders import reap_expired_order_sync_jobs, sync_all_provider_orders
from app.jobs.etsy_sales import enqueue_due_etsy_sales_syncs, reap_expired_etsy_sales_syncs
from app.jobs.publishing import (
    dispatch_pending_publishing_outbox,
    reap_expired_publishing_jobs,
)
from app.jobs.analytics import enqueue_due_analytics_refreshes, reap_expired_analytics_refreshes
from app.core.logging import get_logger, log_event, reset_request_id, set_request_id
from app.db.database import assert_configured_worker_database_role

scheduler_logger = get_logger("scheduler")


def _acquire_scheduler_lock() -> BinaryIO | None:
    lock_path = Path(tempfile.gettempdir()) / "velora-scheduler.lock"
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if lock_path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        handle.close()
        return None
    return handle


def start_scheduler():
    lock_handle = _acquire_scheduler_lock()
    if lock_handle is None:
        log_event(
            scheduler_logger,
            "scheduler.duplicate_rejected",
        )
        return
    try:
        assert_configured_worker_database_role()
    except Exception:
        lock_handle.close()
        raise
    token = set_request_id("scheduler")
    scheduler = BlockingScheduler()
    try:
        scheduler.add_job(
            sync_all_provider_orders.send,
            trigger=IntervalTrigger(minutes=15),
            id="sync_all_provider_orders",
            name="Check for due provider order syncs every 15 minutes",
            replace_existing=True,
        )
        scheduler.add_job(
            reap_expired_order_sync_jobs.send,
            trigger=IntervalTrigger(minutes=5),
            id="reap_expired_order_sync_jobs",
            name="Recover expired order sync jobs every 5 minutes",
            replace_existing=True,
        )
        scheduler.add_job(
            enqueue_due_etsy_sales_syncs.send,
            trigger=IntervalTrigger(minutes=15),
            id="enqueue_due_etsy_sales_syncs",
            name="Check for due Etsy sales syncs every 15 minutes",
            replace_existing=True,
        )
        scheduler.add_job(
            reap_expired_etsy_sales_syncs.send,
            trigger=IntervalTrigger(minutes=5),
            id="reap_expired_etsy_sales_syncs",
            name="Recover expired Etsy sales syncs every 5 minutes",
            replace_existing=True,
        )
        scheduler.add_job(
            dispatch_pending_publishing_outbox.send,
            trigger=IntervalTrigger(minutes=1),
            id="dispatch_pending_publishing_outbox",
            name="Dispatch committed publishing outbox rows every minute",
            replace_existing=True,
        )
        scheduler.add_job(
            reap_expired_publishing_jobs.send,
            trigger=IntervalTrigger(minutes=5),
            id="reap_expired_publishing_jobs",
            name="Recover expired publishing jobs every 5 minutes",
            replace_existing=True,
        )
        scheduler.add_job(
            enqueue_due_analytics_refreshes.send,
            trigger=IntervalTrigger(minutes=5),
            id="enqueue_due_analytics_refreshes",
            name="Refresh expired provider analytics snapshots every 5 minutes",
            replace_existing=True,
        )
        scheduler.add_job(
            reap_expired_analytics_refreshes.send,
            trigger=IntervalTrigger(minutes=5),
            id="reap_expired_analytics_refreshes",
            name="Recover expired analytics refresh jobs every 5 minutes",
            replace_existing=True,
        )

        log_event(
            scheduler_logger,
            "scheduler.started",
            job_count=len(scheduler.get_jobs()),
        )
        for job in scheduler.get_jobs():
            next_run_time = getattr(job, "next_run_time", None)
            log_event(
                scheduler_logger,
                "scheduler.job.registered",
                scheduler_job_id=getattr(job, "id", None),
                scheduler_job_name=job.name,
                next_run_time=str(next_run_time or "pending scheduler start"),
            )

        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log_event(
            scheduler_logger,
            "scheduler.stopped",
        )
    finally:
        reset_request_id(token)
        lock_handle.close()

if __name__ == "__main__":
    start_scheduler()
