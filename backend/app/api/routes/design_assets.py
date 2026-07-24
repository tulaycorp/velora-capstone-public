from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_db, get_workspace_actor_context
from app.models import DesignAsset
from app.services import store_design_asset

router = APIRouter(tags=["design-assets"])


@router.post("/design-assets", response_model=DesignAsset, status_code=status.HTTP_201_CREATED)
async def upload_design_asset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> DesignAsset:
    return await store_design_asset(db, actor=actor, file=file)
