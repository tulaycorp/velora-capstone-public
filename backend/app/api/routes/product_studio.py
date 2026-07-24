from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_db, get_workspace_actor_context
from app.models import ProductStudioState
from app.services import get_product_studio_state

router = APIRouter(tags=["product-studio"])


@router.get("/product-studio", response_model=ProductStudioState)
def get_product_studio_state_route(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> ProductStudioState:
    return get_product_studio_state(db, actor=actor)
