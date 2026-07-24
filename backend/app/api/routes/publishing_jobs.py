from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_db, get_workspace_actor_context
from app.models import PublishingJob
from app.services import get_publishing_job, list_publishing_jobs

router = APIRouter(tags=["publishing-jobs"])


@router.get("/publishing-jobs", response_model=list[PublishingJob])
def list_publishing_job_records(
    product_id: str | None = None,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> list[PublishingJob]:
    return list_publishing_jobs(db, actor=actor, product_id=product_id)


@router.get("/publishing-jobs/{job_id}", response_model=PublishingJob)
def get_publishing_job_record(
    job_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> PublishingJob:
    return get_publishing_job(db, actor=actor, job_id=job_id)
