import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_workspace_actor_context, get_db
from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.models import SyncJob as DBSyncJob
from app.jobs.orders import run_order_sync_background, sync_org_orders
from app.api.etsy_sales_sync import request_etsy_sales_sync
from app.jobs.etsy_sales import ETSY_SALES_JOB_TYPE, ETSY_SALES_SCOPE_KEY
from app.models.schemas import EtsySalesSyncStatus, SyncJob
from app.services.sync_job_lifecycle import ACTIVE_SYNC_JOB_STATUSES, enqueue_sync_job

router = APIRouter(tags=["sync-jobs"])
sync_jobs_logger = get_logger("sync-jobs")


def _latest_order_sync_job_statement(organization_id: str):
    return (
        select(DBSyncJob)
        .where(
            DBSyncJob.organization_id == organization_id,
            DBSyncJob.job_type == "order_sync",
        )
        .order_by(DBSyncJob.created_at.desc(), DBSyncJob.updated_at.desc())
    )


def _get_latest_order_sync_job(db: Session, *, organization_id: str) -> DBSyncJob | None:
    return db.execute(_latest_order_sync_job_statement(organization_id)).scalars().first()


def _get_active_order_sync_job(db: Session, *, organization_id: str) -> DBSyncJob | None:
    return db.execute(
        _latest_order_sync_job_statement(organization_id).where(
            DBSyncJob.status.in_(ACTIVE_SYNC_JOB_STATUSES)
        )
    ).scalars().first()


def _etsy_sales_sync_jobs_statement(organization_id: str):
    return (
        select(DBSyncJob)
        .where(
            DBSyncJob.organization_id == organization_id,
            DBSyncJob.job_type == ETSY_SALES_JOB_TYPE,
            DBSyncJob.scope_key == ETSY_SALES_SCOPE_KEY,
        )
        .order_by(DBSyncJob.created_at.desc(), DBSyncJob.updated_at.desc())
    )


@router.get("/sync-jobs", response_model=list[SyncJob])
def list_sync_jobs(_actor: ActorContext = Depends(get_workspace_actor_context), db: Session = Depends(get_db)) -> list[SyncJob]:
    jobs = db.execute(
        select(DBSyncJob).where(DBSyncJob.organization_id == _actor.organization_id).order_by(DBSyncJob.created_at.desc())
    ).scalars().all()
    return [SyncJob.model_validate(j, from_attributes=True) for j in jobs]


@router.get("/sync-jobs/orders/latest", response_model=SyncJob | None)
def get_latest_order_sync_job(
    _actor: ActorContext = Depends(get_workspace_actor_context),
    db: Session = Depends(get_db),
) -> SyncJob | None:
    job = _get_latest_order_sync_job(db, organization_id=_actor.organization_id)
    if job is None:
        return None
    return SyncJob.model_validate(job, from_attributes=True)


@router.get("/sync-jobs/etsy-sales/status", response_model=EtsySalesSyncStatus)
def get_etsy_sales_sync_status(
    _actor: ActorContext = Depends(get_workspace_actor_context),
    db: Session = Depends(get_db),
) -> EtsySalesSyncStatus:
    statement = _etsy_sales_sync_jobs_statement(_actor.organization_id)
    latest_job = db.execute(statement.limit(1)).scalars().first()
    last_successful_job = db.execute(
        statement.where(DBSyncJob.status.in_(("completed", "partial"))).limit(1)
    ).scalars().first()
    return EtsySalesSyncStatus(
        latest_job=(
            SyncJob.model_validate(latest_job, from_attributes=True)
            if latest_job is not None
            else None
        ),
        last_successful_at=(
            last_successful_job.completed_at
            if last_successful_job is not None
            else None
        ),
    )


@router.get("/sync-jobs/{job_id}", response_model=SyncJob)
def get_sync_job(job_id: str, _actor: ActorContext = Depends(get_workspace_actor_context), db: Session = Depends(get_db)) -> SyncJob:
    job = db.execute(
        select(DBSyncJob).where(DBSyncJob.id == job_id, DBSyncJob.organization_id == _actor.organization_id)
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")
    return SyncJob.model_validate(job, from_attributes=True)


@router.post("/sync-jobs/orders/run", response_model=SyncJob)
def run_order_sync(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    _actor: ActorContext = Depends(get_workspace_actor_context),
    db: Session = Depends(get_db),
) -> SyncJob:
    result = enqueue_sync_job(
        db,
        organization_id=_actor.organization_id,
        job_type="order_sync",
        minimum_interval=timedelta(seconds=settings.commerce_sync_interval_seconds),
        force=force,
    )
    job = result.job

    if not result.created and job.status != "queued":
        return SyncJob.model_validate(job, from_attributes=True)

    try:
        sync_org_orders.send(job.id, _actor.organization_id)
    except RedisError as exc:
        log_event(
            sync_jobs_logger,
            "sync_jobs.order_sync.fallback_to_background_task",
            level=logging.WARNING,
            job_id=job.id,
            organization_id=_actor.organization_id,
            error_type=type(exc).__name__,
        )
        background_tasks.add_task(run_order_sync_background, job.id, _actor.organization_id)

    return SyncJob.model_validate(job, from_attributes=True)


@router.post("/sync-jobs/etsy-sales/run", response_model=SyncJob)
def run_etsy_sales_sync(
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    _actor: ActorContext = Depends(get_workspace_actor_context),
    db: Session = Depends(get_db),
) -> SyncJob:
    result = request_etsy_sales_sync(
        db,
        background_tasks,
        organization_id=_actor.organization_id,
        force=force,
    )
    return SyncJob.model_validate(result.job, from_attributes=True)
