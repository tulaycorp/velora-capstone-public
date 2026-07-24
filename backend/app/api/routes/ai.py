from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_db, get_workspace_actor_context
from app.models import AICapabilities, AIGenerationApplyRequest, AIGenerationApplyResponse, AIGenerationRequest, AIGenerationSummary
from app.services import apply_generation, generate_listing, get_ai_capabilities, list_generations

router = APIRouter(tags=["ai"])


@router.get("/ai/capabilities", response_model=AICapabilities)
def get_capabilities(_actor: ActorContext = Depends(get_workspace_actor_context)) -> AICapabilities:
    return get_ai_capabilities()


@router.post("/products/{product_id}/ai-generations", response_model=AIGenerationSummary)
def create_generation(product_id: str, payload: AIGenerationRequest, db: Session = Depends(get_db), actor: ActorContext = Depends(get_workspace_actor_context)) -> AIGenerationSummary:
    return generate_listing(db, actor=actor, product_id=product_id, payload=payload)


@router.get("/products/{product_id}/ai-generations", response_model=list[AIGenerationSummary])
def get_generations(product_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_workspace_actor_context)) -> list[AIGenerationSummary]:
    return list_generations(db, actor=actor, product_id=product_id)


@router.post("/products/{product_id}/ai-generations/{generation_id}/apply", response_model=AIGenerationApplyResponse)
def apply_generation_record(product_id: str, generation_id: str, payload: AIGenerationApplyRequest, db: Session = Depends(get_db), actor: ActorContext = Depends(get_workspace_actor_context)) -> AIGenerationApplyResponse:
    product, generation = apply_generation(db, actor=actor, product_id=product_id, generation_id=generation_id, payload=payload)
    return AIGenerationApplyResponse(product=product, generation=generation)
