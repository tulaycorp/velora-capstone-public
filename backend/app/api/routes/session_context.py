from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_actor_context, get_db
from app.models import SessionContextResponse
from app.services import get_session_context

router = APIRouter(tags=["session-context"])


@router.get("/session-context", response_model=SessionContextResponse)
def get_session_context_route(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
) -> SessionContextResponse:
    return get_session_context(db, actor=actor)
