from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.actor import ActorContext
from app.core.auth import AuthError, verify_clerk_session_token
from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.database import get_db as database_get_db
from app.db.tenant_context import set_database_request_context
from app.services.identity import ensure_local_actor_records, ensure_user_record, get_approved_membership_for_user


bearer_scheme = HTTPBearer(auto_error=False)
auth_logger = get_logger("auth")


def get_db() -> Generator[Session, None, None]:
    yield from database_get_db()


def get_default_actor_context() -> ActorContext:
    return ActorContext(
        organization_id=settings.default_organization_id,
        actor_id=settings.default_actor_id,
        auth_provider="local",
        org_role="admin",
    )


def get_actor_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ActorContext:
    if settings.resolved_auth_mode() == "local":
        if (
            settings.auth_mode == "auto"
            and credentials is not None
            and credentials.scheme.lower() == "bearer"
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Clerk session tokens were received, but backend Clerk verification is not configured.",
            )
        actor = get_default_actor_context()
        set_database_request_context(
            db,
            actor_id=actor.actor_id,
            organization_id=actor.organization_id,
        )
        ensure_local_actor_records(db, actor=actor)
        log_event(
            auth_logger,
            "auth.actor_resolved",
            verbose_only=True,
            auth_provider=actor.auth_provider,
            actor_id=actor.actor_id,
            organization_id=actor.organization_id,
            org_role=actor.org_role,
        )
        return actor

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        verified_session = verify_clerk_session_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    actor = ActorContext(
        organization_id=None,
        actor_id=verified_session.actor_id,
        auth_provider="clerk",
        session_id=verified_session.session_id,
        organization_slug=verified_session.organization_slug,
        email=verified_session.email,
        first_name=verified_session.first_name,
        last_name=verified_session.last_name,
        image_url=verified_session.image_url,
    )
    set_database_request_context(
        db,
        actor_id=actor.actor_id,
        organization_id=None,
    )
    ensure_user_record(db, actor=actor)
    membership = get_approved_membership_for_user(db, user_id=actor.actor_id)
    if membership is None:
        log_event(
            auth_logger,
            "auth.actor_resolved",
            verbose_only=True,
            auth_provider=actor.auth_provider,
            actor_id=actor.actor_id,
            organization_id=None,
            org_role=None,
            has_membership=False,
            session_id_present=bool(actor.session_id),
        )
        return actor

    organization = membership.organization
    resolved_actor = ActorContext(
        organization_id=membership.organization_id,
        actor_id=actor.actor_id,
        auth_provider=actor.auth_provider,
        session_id=actor.session_id,
        org_role=membership.role,
        organization_slug=organization.slug if organization else None,
        email=actor.email,
        first_name=actor.first_name,
        last_name=actor.last_name,
        image_url=actor.image_url,
    )
    set_database_request_context(
        db,
        actor_id=resolved_actor.actor_id,
        organization_id=resolved_actor.organization_id,
    )
    log_event(
        auth_logger,
        "auth.actor_resolved",
        verbose_only=True,
        auth_provider=resolved_actor.auth_provider,
        actor_id=resolved_actor.actor_id,
        organization_id=resolved_actor.organization_id,
        org_role=resolved_actor.org_role,
        has_membership=True,
        session_id_present=bool(resolved_actor.session_id),
    )
    return resolved_actor


def get_workspace_actor_context(
    actor: ActorContext = Depends(get_actor_context),
) -> ActorContext:
    if actor.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization membership is required to access the workspace.",
        )
    return actor


def get_admin_actor_context(
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> ActorContext:
    if actor.org_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required.",
        )
    return actor
