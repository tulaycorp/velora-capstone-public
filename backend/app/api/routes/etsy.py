from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.etsy_sales_sync import request_etsy_sales_sync
from app.api.deps import ActorContext, get_admin_actor_context, get_db
from app.models import EtsyConnectionStatus, EtsyOAuthCallbackRequest, EtsyOAuthStartResponse
from app.services import (
    complete_etsy_oauth_connection,
    get_etsy_connection_status,
    start_etsy_oauth_connection,
    sync_etsy_connection_shops,
)

router = APIRouter(tags=["etsy"])


@router.get("/etsy/connection", response_model=EtsyConnectionStatus)
def get_etsy_connection(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> EtsyConnectionStatus:
    return get_etsy_connection_status(db, actor=actor)


@router.post("/etsy/oauth/start", response_model=EtsyOAuthStartResponse)
def start_etsy_oauth(
    expected_seller_user_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> EtsyOAuthStartResponse:
    return start_etsy_oauth_connection(
        db,
        actor=actor,
        expected_seller_user_id=expected_seller_user_id,
    )


@router.post("/etsy/oauth/callback", response_model=EtsyConnectionStatus)
def complete_etsy_oauth(
    payload: EtsyOAuthCallbackRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> EtsyConnectionStatus:
    status = complete_etsy_oauth_connection(
        db,
        actor=actor,
        code=payload.code,
        state=payload.state,
    )
    if status.matched_connection_count > 0:
        request_etsy_sales_sync(
            db,
            background_tasks,
            organization_id=actor.organization_id,
            force=True,
            fallback_to_background=False,
        )
    return status


@router.post("/etsy/connection/sync", response_model=EtsyConnectionStatus)
def sync_etsy_connection(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> EtsyConnectionStatus:
    status = sync_etsy_connection_shops(db, actor=actor)
    if status.matched_connection_count > 0:
        request_etsy_sales_sync(
            db,
            background_tasks,
            organization_id=actor.organization_id,
            force=True,
            fallback_to_background=False,
        )
    return status
