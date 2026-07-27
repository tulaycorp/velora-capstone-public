from __future__ import annotations

import random
import string
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.actor import ActorContext
from app.core.config import settings
from app.db.models import Membership, Organization, OrganizationJoinRequest, User


ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
JOIN_REQUEST_PENDING = "pending"
JOIN_REQUEST_APPROVED = "approved"
JOIN_REQUEST_REJECTED = "rejected"
JOIN_CODE_ALPHABET = string.ascii_uppercase + string.digits
JOIN_CODE_LENGTH = 8


def _normalized_string(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _extract_clerk_primary_email(payload: dict[str, Any]) -> str | None:
    primary_email_address_id = payload.get("primary_email_address_id") or payload.get("primaryEmailAddressId")
    email_addresses = payload.get("email_addresses") or payload.get("emailAddresses")
    if not isinstance(email_addresses, list):
        return None

    if isinstance(primary_email_address_id, str):
        for candidate in email_addresses:
            if isinstance(candidate, dict) and candidate.get("id") == primary_email_address_id:
                address = _normalized_string(candidate.get("email_address") or candidate.get("emailAddress"))
                if address:
                    return address

    for candidate in email_addresses:
        if not isinstance(candidate, dict):
            continue
        address = _normalized_string(candidate.get("email_address") or candidate.get("emailAddress"))
        if address:
            return address

    return None


def fetch_clerk_user_profile(*, user_id: str) -> dict[str, str | None]:
    secret_key = _normalized_string(settings.clerk_secret_key)
    if not secret_key:
        return {
            "email": None,
            "first_name": None,
            "last_name": None,
            "image_url": None,
        }

    try:
        response = httpx.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {
            "email": None,
            "first_name": None,
            "last_name": None,
            "image_url": None,
        }

    if not isinstance(payload, dict):
        return {
            "email": None,
            "first_name": None,
            "last_name": None,
            "image_url": None,
        }

    return {
        "email": _extract_clerk_primary_email(payload),
        "first_name": _normalized_string(payload.get("first_name") or payload.get("firstName")),
        "last_name": _normalized_string(payload.get("last_name") or payload.get("lastName")),
        "image_url": _normalized_string(payload.get("image_url") or payload.get("imageUrl")),
    }


def display_name_for_user(user: User | ActorContext | None) -> str:
    if user is None:
        return "Unknown user"

    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    email = getattr(user, "email", None)

    if isinstance(email, str) and email.strip():
        return email.strip()

    full_name = " ".join(part for part in [first_name, last_name] if part)
    if full_name.strip():
        return full_name.strip()
    return getattr(user, "actor_id", None) or getattr(user, "id", None) or "Unknown user"


def ensure_local_actor_records(db: Session, *, actor: ActorContext) -> None:
    organization = db.get(Organization, actor.organization_id)
    if organization is None:
        organization = Organization(
            id=actor.organization_id,
            auth_provider=actor.auth_provider,
            name="Default Organization",
            created_by_user_id=actor.actor_id,
            join_code="VELORADEV",
        )
        db.add(organization)
    else:
        organization.auth_provider = actor.auth_provider
        organization.name = organization.name or "Default Organization"
        organization.created_by_user_id = organization.created_by_user_id or actor.actor_id
        organization.join_code = organization.join_code or "VELORADEV"

    user = db.get(User, actor.actor_id)
    if user is None:
        user = User(
            id=actor.actor_id,
            auth_provider=actor.auth_provider,
            email=actor.email,
            first_name=actor.first_name,
            last_name=actor.last_name,
            image_url=actor.image_url,
        )
        db.add(user)
    else:
        user.auth_provider = actor.auth_provider
        if actor.email is not None:
            user.email = actor.email
        if actor.first_name is not None:
            user.first_name = actor.first_name
        if actor.last_name is not None:
            user.last_name = actor.last_name
        if actor.image_url is not None:
            user.image_url = actor.image_url

    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == actor.organization_id,
            Membership.user_id == actor.actor_id,
        )
    )
    if membership is None:
        membership = Membership(
            organization_id=actor.organization_id,
            user_id=actor.actor_id,
            role=ROLE_ADMIN,
        )
        db.add(membership)
    else:
        membership.role = ROLE_ADMIN

    db.commit()


def _apply_user_profile(
    user: User,
    *,
    auth_provider: str,
    email: str | None,
    first_name: str | None,
    last_name: str | None,
    image_url: str | None,
) -> None:
    user.auth_provider = auth_provider
    if email is not None:
        user.email = email
    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        user.last_name = last_name
    if image_url is not None:
        user.image_url = image_url


def ensure_user_record(db: Session, *, actor: ActorContext) -> User:
    user = db.get(User, actor.actor_id)
    created_user = user is None
    resolved_email = actor.email
    resolved_first_name = actor.first_name
    resolved_last_name = actor.last_name
    resolved_image_url = actor.image_url

    should_fetch_clerk_profile = (
        actor.auth_provider == "clerk"
        and (user is None or not user.email)
        and not resolved_email
    )
    if should_fetch_clerk_profile:
        profile = fetch_clerk_user_profile(user_id=actor.actor_id)
        resolved_email = resolved_email or profile.get("email")
        resolved_first_name = resolved_first_name or profile.get("first_name")
        resolved_last_name = resolved_last_name or profile.get("last_name")
        resolved_image_url = resolved_image_url or profile.get("image_url")

    if user is None:
        user = User(
            id=actor.actor_id,
            auth_provider=actor.auth_provider,
            email=resolved_email,
            first_name=resolved_first_name,
            last_name=resolved_last_name,
            image_url=resolved_image_url,
        )
        db.add(user)
    else:
        _apply_user_profile(
            user,
            auth_provider=actor.auth_provider,
            email=resolved_email,
            first_name=resolved_first_name,
            last_name=resolved_last_name,
            image_url=resolved_image_url,
        )

    if not created_user and not db.is_modified(user, include_collections=False):
        return user

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        user = db.get(User, actor.actor_id)
        if user is None:
            raise exc
        _apply_user_profile(
            user,
            auth_provider=actor.auth_provider,
            email=resolved_email,
            first_name=resolved_first_name,
            last_name=resolved_last_name,
            image_url=resolved_image_url,
        )
        if not db.is_modified(user, include_collections=False):
            return user
        db.commit()

    db.refresh(user)
    return user


def get_approved_membership_for_user(db: Session, *, user_id: str) -> Membership | None:
    return db.scalar(
        select(Membership)
        .options(joinedload(Membership.organization))
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at.asc())
    )


def get_pending_join_request_for_user(db: Session, *, user_id: str) -> OrganizationJoinRequest | None:
    return db.scalar(
        select(OrganizationJoinRequest)
        .options(selectinload(OrganizationJoinRequest.organization), selectinload(OrganizationJoinRequest.requested_by_user))
        .where(
            OrganizationJoinRequest.requested_by_user_id == user_id,
            OrganizationJoinRequest.status == JOIN_REQUEST_PENDING,
        )
        .order_by(OrganizationJoinRequest.created_at.desc())
    )


def count_pending_join_requests_for_organization(db: Session, *, organization_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(OrganizationJoinRequest.id)).where(
                OrganizationJoinRequest.organization_id == organization_id,
                OrganizationJoinRequest.status == JOIN_REQUEST_PENDING,
            )
        )
        or 0
    )


def generate_join_code(db: Session) -> str:
    while True:
        candidate = "".join(random.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))
        exists = db.scalar(select(Organization.id).where(Organization.join_code == candidate))
        if exists is None:
            return candidate
