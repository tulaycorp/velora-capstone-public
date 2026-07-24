from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.actor import ActorContext
from app.core.logging import get_logger, log_event
from app.db.models import Membership, Organization, OrganizationJoinRequest, User
from app.db.tenant_context import set_database_join_code_context
from app.models import (
    OrganizationCreateRequest,
    OrganizationCreateResponse,
    OrganizationUpdateRequest,
    OrganizationUpdateResponse,
    OrganizationLeaveResponse,
    OrganizationJoinRequestCreateRequest,
    OrganizationJoinRequestListResponse,
    OrganizationJoinRequestResponse,
    OrganizationJoinRequestSummary,
    OrganizationMemberListResponse,
    OrganizationMemberResponse,
    OrganizationMemberSummary,
    SessionContextMembership,
    SessionContextOrganization,
    SessionContextResponse,
    SessionContextUser,
)
from app.services.identity import (
    JOIN_REQUEST_APPROVED,
    JOIN_REQUEST_PENDING,
    JOIN_REQUEST_REJECTED,
    ROLE_ADMIN,
    ROLE_MEMBER,
    count_pending_join_requests_for_organization,
    display_name_for_user,
    ensure_user_record,
    generate_join_code,
    get_approved_membership_for_user,
    get_pending_join_request_for_user,
)

organization_logger = get_logger("organization")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_session_user(user: User | ActorContext) -> SessionContextUser:
    return SessionContextUser(
        id=getattr(user, "id", None) or user.actor_id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        image_url=user.image_url,
        display_name=display_name_for_user(user),
    )


def _to_session_organization(organization: Organization) -> SessionContextOrganization:
    admin_user = organization.created_by_user
    return SessionContextOrganization(
        id=organization.id,
        name=organization.name or "Untitled Organization",
        join_code=organization.join_code,
        admin_user_id=organization.created_by_user_id,
        admin_name=display_name_for_user(admin_user) if admin_user else None,
    )


def _to_join_request_summary(join_request: OrganizationJoinRequest) -> OrganizationJoinRequestSummary:
    requested_user = join_request.requested_by_user
    organization = join_request.organization
    return OrganizationJoinRequestSummary(
        id=join_request.id,
        organization_id=join_request.organization_id,
        organization_name=organization.name if organization and organization.name else "Untitled Organization",
        requested_by_user_id=join_request.requested_by_user_id,
        requested_by_name=display_name_for_user(requested_user),
        requested_by_email=requested_user.email if requested_user else None,
        status=join_request.status,  # type: ignore[arg-type]
        created_at=join_request.created_at,
        reviewed_at=join_request.reviewed_at,
    )


def _to_member_summary(membership: Membership, *, actor_id: str) -> OrganizationMemberSummary:
    member_user = membership.user
    return OrganizationMemberSummary(
        user_id=membership.user_id,
        display_name=display_name_for_user(member_user) if member_user else membership.user_id,
        email=member_user.email if member_user else None,
        role=membership.role,  # type: ignore[arg-type]
        joined_at=membership.created_at,
        is_current_user=membership.user_id == actor_id,
        is_removable=membership.user_id != actor_id and membership.role != ROLE_ADMIN,
    )


def get_session_context(db: Session, *, actor: ActorContext) -> SessionContextResponse:
    user = db.get(User, actor.actor_id) if actor.auth_provider != "local" else None
    membership = get_approved_membership_for_user(db, user_id=actor.actor_id)
    pending_join_request = None

    if membership is None and actor.auth_provider != "local":
        pending_join_request = get_pending_join_request_for_user(db, user_id=actor.actor_id)

    if membership is not None and membership.organization is None:
        membership = db.scalar(
            select(Membership)
            .options(selectinload(Membership.organization).selectinload(Organization.created_by_user))
            .where(Membership.id == membership.id)
        )

    if membership is not None:
        organization = membership.organization
        pending_count = (
            count_pending_join_requests_for_organization(db, organization_id=membership.organization_id)
            if membership.role == ROLE_ADMIN
            else 0
        )
        return SessionContextResponse(
            auth_mode=actor.auth_provider,  # type: ignore[arg-type]
            onboarding_status="approved",
            user=_to_session_user(user or actor),
            organization=_to_session_organization(organization),
            membership=SessionContextMembership(role=membership.role),  # type: ignore[arg-type]
            admin_pending_request_count=pending_count,
        )

    if pending_join_request is not None:
        return SessionContextResponse(
            auth_mode=actor.auth_provider,  # type: ignore[arg-type]
            onboarding_status="pending",
            user=_to_session_user(user or actor),
            pending_join_request=_to_join_request_summary(pending_join_request),
        )

    return SessionContextResponse(
        auth_mode=actor.auth_provider,  # type: ignore[arg-type]
        onboarding_status="needs_organization",
        user=_to_session_user(user or actor),
    )


def create_organization_for_actor(
    db: Session,
    *,
    actor: ActorContext,
    payload: OrganizationCreateRequest,
) -> OrganizationCreateResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Organization name is required.")

    if get_approved_membership_for_user(db, user_id=actor.actor_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already belong to an organization.")

    if get_pending_join_request_for_user(db, user_id=actor.actor_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending organization access request.",
        )

    ensure_user_record(db, actor=actor)
    organization = Organization(
        id=f"org_{uuid.uuid4().hex[:24]}",
        auth_provider=actor.auth_provider,
        name=name,
        created_by_user_id=actor.actor_id,
        join_code=generate_join_code(db),
    )
    db.add(organization)
    membership = Membership(
        organization_id=organization.id,
        user_id=actor.actor_id,
        role=ROLE_ADMIN,
    )
    db.add(membership)
    db.commit()

    created = db.scalar(
        select(Organization)
        .options(selectinload(Organization.created_by_user))
        .where(Organization.id == organization.id)
    )
    log_event(
        organization_logger,
        "organization.created",
        verbose_only=True,
        organization_id=organization.id,
        actor_id=actor.actor_id,
        join_code_present=bool(organization.join_code),
    )
    return OrganizationCreateResponse(
        status="ok",
        organization=_to_session_organization(created),
        membership=SessionContextMembership(role=ROLE_ADMIN),
    )


def update_organization_for_actor(
    db: Session,
    *,
    actor: ActorContext,
    payload: OrganizationUpdateRequest,
) -> OrganizationUpdateResponse:
    if actor.organization_id is None or actor.org_role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Organization name is required.")

    organization = db.get(Organization, actor.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization was not found.")

    organization.name = name
    db.commit()

    log_event(
        organization_logger,
        "organization.updated",
        verbose_only=True,
        organization_id=organization.id,
        actor_id=actor.actor_id,
        new_name=name,
    )
    return OrganizationUpdateResponse(
        status="ok",
        organization=_to_session_organization(organization),
    )


def submit_join_request_for_actor(
    db: Session,
    *,
    actor: ActorContext,
    payload: OrganizationJoinRequestCreateRequest,
) -> OrganizationJoinRequestResponse:
    if get_approved_membership_for_user(db, user_id=actor.actor_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already belong to an organization.")

    if get_pending_join_request_for_user(db, user_id=actor.actor_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending organization access request.",
        )

    join_code = payload.join_code.strip().upper()
    set_database_join_code_context(db, join_code=join_code)
    organization = db.scalar(
        select(Organization)
        .options(selectinload(Organization.created_by_user))
        .where(Organization.join_code == join_code)
    )
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization code was not found.")

    ensure_user_record(db, actor=actor)
    join_request = OrganizationJoinRequest(
        organization_id=organization.id,
        requested_by_user_id=actor.actor_id,
        status=JOIN_REQUEST_PENDING,
    )
    db.add(join_request)
    db.commit()

    created = db.scalar(
        select(OrganizationJoinRequest)
        .options(
            selectinload(OrganizationJoinRequest.organization),
            selectinload(OrganizationJoinRequest.requested_by_user),
        )
        .where(OrganizationJoinRequest.id == join_request.id)
    )
    log_event(
        organization_logger,
        "organization.join_request.submitted",
        verbose_only=True,
        organization_id=organization.id,
        join_request_id=join_request.id,
        actor_id=actor.actor_id,
    )
    return OrganizationJoinRequestResponse(status="ok", join_request=_to_join_request_summary(created))


def list_pending_join_requests_for_actor(
    db: Session,
    *,
    actor: ActorContext,
) -> OrganizationJoinRequestListResponse:
    if actor.organization_id is None or actor.org_role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")

    join_requests = list(
        db.scalars(
            select(OrganizationJoinRequest)
            .options(
                selectinload(OrganizationJoinRequest.organization),
                selectinload(OrganizationJoinRequest.requested_by_user),
            )
            .where(
                OrganizationJoinRequest.organization_id == actor.organization_id,
                OrganizationJoinRequest.status == JOIN_REQUEST_PENDING,
            )
            .order_by(OrganizationJoinRequest.created_at.asc())
        )
    )
    return OrganizationJoinRequestListResponse(
        pending_request_count=len(join_requests),
        join_requests=[_to_join_request_summary(item) for item in join_requests],
    )


def review_join_request_for_actor(
    db: Session,
    *,
    actor: ActorContext,
    join_request_id: str,
    approve: bool,
) -> OrganizationJoinRequestResponse:
    if actor.organization_id is None or actor.org_role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")

    join_request = db.scalar(
        select(OrganizationJoinRequest)
        .options(
            selectinload(OrganizationJoinRequest.organization),
            selectinload(OrganizationJoinRequest.requested_by_user),
        )
        .where(
            OrganizationJoinRequest.id == join_request_id,
            OrganizationJoinRequest.organization_id == actor.organization_id,
        )
    )
    if join_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Join request was not found.")
    if join_request.status != JOIN_REQUEST_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Join request has already been reviewed.")

    if approve:
        existing_membership = get_approved_membership_for_user(db, user_id=join_request.requested_by_user_id)
        if existing_membership is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That user already belongs to an organization.",
            )
        db.add(
            Membership(
                organization_id=join_request.organization_id,
                user_id=join_request.requested_by_user_id,
                role=ROLE_MEMBER,
            )
        )
        join_request.status = JOIN_REQUEST_APPROVED
    else:
        join_request.status = JOIN_REQUEST_REJECTED

    join_request.reviewed_by_user_id = actor.actor_id
    join_request.reviewed_at = utc_now()
    db.commit()

    reviewed = db.scalar(
        select(OrganizationJoinRequest)
        .options(
            selectinload(OrganizationJoinRequest.organization),
            selectinload(OrganizationJoinRequest.requested_by_user),
        )
        .where(OrganizationJoinRequest.id == join_request.id)
    )
    log_event(
        organization_logger,
        "organization.join_request.reviewed",
        verbose_only=True,
        organization_id=join_request.organization_id,
        join_request_id=join_request.id,
        reviewed_by_actor_id=actor.actor_id,
        approved=approve,
    )
    return OrganizationJoinRequestResponse(status="ok", join_request=_to_join_request_summary(reviewed))


def list_members_for_actor(
    db: Session,
    *,
    actor: ActorContext,
) -> OrganizationMemberListResponse:
    if actor.organization_id is None or actor.org_role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")

    memberships = list(
        db.scalars(
            select(Membership)
            .options(selectinload(Membership.user))
            .where(Membership.organization_id == actor.organization_id)
        )
    )
    memberships.sort(
        key=lambda item: (
            0 if item.role == ROLE_ADMIN else 1,
            item.created_at or datetime.min.replace(tzinfo=timezone.utc),
        )
    )

    return OrganizationMemberListResponse(
        member_count=len(memberships),
        members=[_to_member_summary(item, actor_id=actor.actor_id) for item in memberships],
    )


def remove_member_for_actor(
    db: Session,
    *,
    actor: ActorContext,
    member_user_id: str,
) -> OrganizationMemberResponse:
    if actor.organization_id is None or actor.org_role != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")

    if member_user_id == actor.actor_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use the leave organization flow to remove yourself from the workspace.",
        )

    membership = db.scalar(
        select(Membership)
        .options(selectinload(Membership.user))
        .where(
            Membership.organization_id == actor.organization_id,
            Membership.user_id == member_user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization member was not found.")

    if membership.role == ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin ownership can only change through the admin leave flow.",
        )

    removed_member = _to_member_summary(membership, actor_id=actor.actor_id)
    db.delete(membership)
    db.commit()
    log_event(
        organization_logger,
        "organization.member.removed",
        verbose_only=True,
        organization_id=actor.organization_id,
        removed_user_id=member_user_id,
        removed_by_actor_id=actor.actor_id,
    )

    return OrganizationMemberResponse(status="ok", member=removed_member)


def leave_organization_for_actor(
    db: Session,
    *,
    actor: ActorContext,
) -> OrganizationLeaveResponse:
    if actor.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization membership is required to leave an organization.",
        )

    membership = db.scalar(
        select(Membership)
        .options(selectinload(Membership.organization).selectinload(Organization.created_by_user))
        .where(
            Membership.organization_id == actor.organization_id,
            Membership.user_id == actor.actor_id,
        )
    )
    if membership is None or membership.organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization membership was not found.")

    if membership.role == ROLE_ADMIN:
        replacement_membership = db.scalar(
            select(Membership)
            .where(
                Membership.organization_id == actor.organization_id,
                Membership.user_id != actor.actor_id,
            )
            .order_by(Membership.created_at.asc())
        )
        if replacement_membership is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You must transfer organization ownership before leaving the only admin role.",
            )

        replacement_membership.role = ROLE_ADMIN
        membership.organization.created_by_user_id = replacement_membership.user_id

    db.delete(membership)
    db.commit()
    log_event(
        organization_logger,
        "organization.left",
        verbose_only=True,
        organization_id=actor.organization_id,
        actor_id=actor.actor_id,
        transferred_admin=membership.role == ROLE_ADMIN,
    )

    return OrganizationLeaveResponse(
        status="ok",
        session_context=get_session_context(
            db,
            actor=ActorContext(
                organization_id=None,
                actor_id=actor.actor_id,
                auth_provider=actor.auth_provider,
                session_id=actor.session_id,
                organization_slug=None,
                email=actor.email,
                first_name=actor.first_name,
                last_name=actor.last_name,
                image_url=actor.image_url,
            ),
        ),
    )
