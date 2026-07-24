from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_actor_context, get_admin_actor_context, get_db
from app.models import (
    OrganizationCreateRequest,
    OrganizationCreateResponse,
    OrganizationUpdateRequest,
    OrganizationUpdateResponse,
    OrganizationJoinRequestCreateRequest,
    OrganizationJoinRequestListResponse,
    OrganizationJoinRequestResponse,
    OrganizationLeaveResponse,
    OrganizationMemberListResponse,
    OrganizationMemberResponse,
)
from app.services import (
    create_organization_for_actor,
    leave_organization_for_actor,
    list_members_for_actor,
    list_pending_join_requests_for_actor,
    remove_member_for_actor,
    review_join_request_for_actor,
    submit_join_request_for_actor,
    update_organization_for_actor,
)

router = APIRouter(tags=["organizations"])


@router.post("/organizations", response_model=OrganizationCreateResponse, status_code=status.HTTP_201_CREATED)
def create_organization_route(
    payload: OrganizationCreateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
) -> OrganizationCreateResponse:
    return create_organization_for_actor(db, actor=actor, payload=payload)


@router.patch("/organizations", response_model=OrganizationUpdateResponse)
def update_organization_route(
    payload: OrganizationUpdateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> OrganizationUpdateResponse:
    return update_organization_for_actor(db, actor=actor, payload=payload)


@router.post(
    "/organizations/join-requests",
    response_model=OrganizationJoinRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_join_request_route(
    payload: OrganizationJoinRequestCreateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
) -> OrganizationJoinRequestResponse:
    return submit_join_request_for_actor(db, actor=actor, payload=payload)


@router.post("/organizations/leave", response_model=OrganizationLeaveResponse)
def leave_organization_route(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
) -> OrganizationLeaveResponse:
    return leave_organization_for_actor(db, actor=actor)


@router.get("/organizations/members", response_model=OrganizationMemberListResponse)
def list_members_route(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> OrganizationMemberListResponse:
    return list_members_for_actor(db, actor=actor)


@router.post("/organizations/members/{member_user_id}/remove", response_model=OrganizationMemberResponse)
def remove_member_route(
    member_user_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> OrganizationMemberResponse:
    return remove_member_for_actor(db, actor=actor, member_user_id=member_user_id)


@router.get("/organizations/join-requests", response_model=OrganizationJoinRequestListResponse)
def list_join_requests_route(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> OrganizationJoinRequestListResponse:
    return list_pending_join_requests_for_actor(db, actor=actor)


@router.post("/organizations/join-requests/{join_request_id}/approve", response_model=OrganizationJoinRequestResponse)
def approve_join_request_route(
    join_request_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> OrganizationJoinRequestResponse:
    return review_join_request_for_actor(db, actor=actor, join_request_id=join_request_id, approve=True)


@router.post("/organizations/join-requests/{join_request_id}/reject", response_model=OrganizationJoinRequestResponse)
def reject_join_request_route(
    join_request_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> OrganizationJoinRequestResponse:
    return review_join_request_for_actor(db, actor=actor, join_request_id=join_request_id, approve=False)
