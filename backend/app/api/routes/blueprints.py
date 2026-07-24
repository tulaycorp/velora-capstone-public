from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_db, get_workspace_actor_context
from app.models import (
    Blueprint,
    BlueprintCreateRequest,
    BlueprintUpdateRequest,
    BlueprintValidationResponse,
)
from app.services import (
    create_blueprint,
    delete_blueprint,
    get_blueprint,
    list_blueprints,
    update_blueprint,
    validate_blueprint_reference,
)

router = APIRouter(tags=["blueprints"])


@router.get("/blueprints", response_model=list[Blueprint])
def list_blueprint_records(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> list[Blueprint]:
    return list_blueprints(db, actor=actor)


@router.post("/blueprints", response_model=Blueprint, status_code=status.HTTP_201_CREATED)
async def create_blueprint_record(
    payload: BlueprintCreateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Blueprint:
    return await create_blueprint(db, actor=actor, payload=payload)


@router.get("/blueprints/{blueprint_id}", response_model=Blueprint)
def get_blueprint_record(
    blueprint_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Blueprint:
    return get_blueprint(db, actor=actor, blueprint_id=blueprint_id)


@router.patch("/blueprints/{blueprint_id}", response_model=Blueprint)
def update_blueprint_record(
    blueprint_id: str,
    payload: BlueprintUpdateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Blueprint:
    return update_blueprint(db, actor=actor, blueprint_id=blueprint_id, payload=payload)


@router.delete("/blueprints/{blueprint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blueprint_record(
    blueprint_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Response:
    delete_blueprint(db, actor=actor, blueprint_id=blueprint_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/blueprints/{blueprint_id}/validate-reference", response_model=BlueprintValidationResponse)
async def validate_blueprint_reference_record(
    blueprint_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> BlueprintValidationResponse:
    return await validate_blueprint_reference(db, actor=actor, blueprint_id=blueprint_id)
