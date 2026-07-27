from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import BackgroundTasks
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.jobs.etsy_sales import (
    ETSY_SALES_JOB_TYPE,
    ETSY_SALES_SCOPE_KEY,
    run_etsy_sales_sync,
    sync_etsy_sales,
)
from app.services.sync_job_lifecycle import EnqueueResult, enqueue_sync_job


etsy_sales_dispatch_logger = get_logger("etsy_sales_dispatch")


def request_etsy_sales_sync(
    db: Session,
    background_tasks: BackgroundTasks,
    *,
    organization_id: str,
    force: bool = False,
    fallback_to_background: bool = True,
) -> EnqueueResult:
    result = enqueue_sync_job(
        db,
        organization_id=organization_id,
        job_type=ETSY_SALES_JOB_TYPE,
        scope_key=ETSY_SALES_SCOPE_KEY,
        provider="etsy",
        minimum_interval=timedelta(
            seconds=settings.commerce_sync_interval_seconds
        ),
        force=force,
    )
    if not result.created and result.job.status != "queued":
        return result

    try:
        sync_etsy_sales.send(result.job.id, organization_id)
    except RedisError as exc:
        log_event(
            etsy_sales_dispatch_logger,
            (
                "etsy_sales.dispatch.fallback_to_background_task"
                if fallback_to_background
                else "etsy_sales.dispatch.left_queued"
            ),
            level=logging.WARNING,
            job_id=result.job.id,
            organization_id=organization_id,
            error_type=type(exc).__name__,
        )
        if fallback_to_background:
            background_tasks.add_task(
                run_etsy_sales_sync,
                result.job.id,
                organization_id,
            )
    return result
