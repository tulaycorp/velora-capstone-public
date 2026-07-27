from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import text

from app.core.actor import ActorContext
from app.core import auth as auth_module
from app.core.config import settings
from app.db.models import User
import app.services.identity as identity_module


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_uint(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return _b64url_encode(value.to_bytes(size, "big"))


def _build_test_token(
    *,
    private_key: rsa.RSAPrivateKey,
    kid: str,
    user_id: str,
    org_id: str | None = None,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    omit_exp: bool = False,
    azp: object = "http://localhost:3000",
) -> str:
    now = datetime.now(UTC)
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    payload = {
        "sub": user_id,
        "sid": f"sess_{user_id}",
        "iss": "https://clerk.test",
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "iat": int(now.timestamp()),
    }
    if azp is not None:
        payload["azp"] = azp
    if omit_exp:
        payload.pop("exp")
    if org_id is not None:
        payload["org_id"] = org_id
    if email is not None:
        payload["email"] = email
    if first_name is not None:
        payload["first_name"] = first_name
    if last_name is not None:
        payload["last_name"] = last_name
    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"


def _build_test_jwks(*, private_key: rsa.RSAPrivateKey, kid: str) -> dict[str, object]:
    public_numbers = private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_uint(public_numbers.n),
                "e": _b64url_uint(public_numbers.e),
            }
        ]
    }


def _configure_clerk_mode(monkeypatch, *, jwks: dict[str, object]) -> None:
    auth_module._JWKS_CACHE.clear()
    monkeypatch.setattr(settings, "auth_mode", "clerk")
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.test/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_authorized_parties", ["http://localhost:3000"])
    monkeypatch.setattr(settings, "clerk_issuer", "https://clerk.test")
    monkeypatch.setattr(auth_module, "fetch_jwks", lambda _url: jwks)


def test_local_auth_mode_keeps_default_actor(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "local")

    response = client.get("/pod-providers")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_local_auth_mode_persists_default_identity_records(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "local")

    response = client.get("/pod-providers")

    assert response.status_code == 200

    with client.app.state.testing_session_local() as db:
        organizations = db.execute(text("select id, name from organizations")).all()
        users = db.execute(text("select id, auth_provider from users")).all()
        memberships = db.execute(
            text("select organization_id, user_id, role from memberships"),
        ).all()

    assert organizations == [("default-org", "Default Organization")]
    assert users == [("default-user", "local")]
    assert memberships == [("default-org", "default-user", "admin")]


def test_auto_auth_mode_rejects_bearer_token_when_backend_clerk_verifier_is_missing(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "auto")
    monkeypatch.setattr(settings, "clerk_jwks_url", None)

    response = client.get("/pod-providers", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "Clerk session tokens were received, but backend Clerk verification is not configured."
    )


def test_clerk_auth_mode_rejects_missing_bearer_token(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_clerk_mode(monkeypatch, jwks=_build_test_jwks(private_key=private_key, kid="test-key"))

    response = client.get("/pod-providers")

    assert response.status_code == 401


def test_clerk_token_requires_exp_and_allowlisted_string_azp(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    _configure_clerk_mode(monkeypatch, jwks=_build_test_jwks(private_key=private_key, kid=kid))

    missing_exp = _build_test_token(private_key=private_key, kid=kid, user_id="user-exp", omit_exp=True)
    missing_azp = _build_test_token(private_key=private_key, kid=kid, user_id="user-azp", azp=None)
    non_string_azp = _build_test_token(private_key=private_key, kid=kid, user_id="user-azp-type", azp=["http://localhost:3000"])

    for token in (missing_exp, missing_azp, non_string_azp):
        try:
            auth_module.verify_clerk_session_token(token)
        except auth_module.AuthError:
            pass
        else:  # pragma: no cover - regression guard
            raise AssertionError("Expected Clerk token validation to fail")


def test_clerk_token_refreshes_jwks_once_for_unknown_key(monkeypatch) -> None:
    old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_clerk_mode(monkeypatch, jwks=_build_test_jwks(private_key=old_key, kid="old-key"))
    token = _build_test_token(private_key=new_key, kid="new-key", user_id="user-jwks-refresh")
    calls = 0

    def fetch_jwks(_url: str) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return _build_test_jwks(private_key=old_key if calls == 1 else new_key, kid="old-key" if calls == 1 else "new-key")

    auth_module._JWKS_CACHE.clear()
    monkeypatch.setattr(auth_module, "fetch_jwks", fetch_jwks)

    verified = auth_module.verify_clerk_session_token(token)

    assert verified.actor_id == "user-jwks-refresh"
    assert calls == 2


def test_clerk_auth_mode_requires_approved_membership_for_workspace_routes(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    jwks = _build_test_jwks(private_key=private_key, kid=kid)
    _configure_clerk_mode(monkeypatch, jwks=jwks)
    token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_test_123",
        email="user@example.com",
        first_name="Test",
        last_name="User",
    )

    workspace_response = client.get("/pod-providers", headers={"Authorization": f"Bearer {token}"})
    assert workspace_response.status_code == 403

    session_context_response = client.get("/session-context", headers={"Authorization": f"Bearer {token}"})
    assert session_context_response.status_code == 200
    assert session_context_response.json()["onboarding_status"] == "needs_organization"


def test_clerk_auth_mode_fetches_missing_email_from_clerk_backend_api(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    _configure_clerk_mode(monkeypatch, jwks=_build_test_jwks(private_key=private_key, kid=kid))
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_backend")

    requested_user_ids: list[str] = []

    monkeypatch.setattr(
        identity_module,
        "fetch_clerk_user_profile",
        lambda *, user_id: requested_user_ids.append(user_id)
        or {
            "email": "fallback@example.com",
            "first_name": "Fallback",
            "last_name": "Member",
            "image_url": "https://img.clerk.test/avatar.png",
        },
        raising=False,
    )

    token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_missing_email_123",
    )

    response = client.get("/session-context", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["onboarding_status"] == "needs_organization"
    assert response.json()["user"]["email"] == "fallback@example.com"
    assert response.json()["user"]["display_name"] == "fallback@example.com"
    assert requested_user_ids == ["user_missing_email_123"]

    with client.app.state.testing_session_local() as db:
        users = db.execute(
            text("select id, email, first_name, last_name, image_url from users where id = 'user_missing_email_123'"),
        ).all()

    assert users == [
        (
            "user_missing_email_123",
            "fallback@example.com",
            "Fallback",
            "Member",
            "https://img.clerk.test/avatar.png",
        )
    ]


def test_clerk_user_record_creation_recovers_from_concurrent_insert(client, monkeypatch) -> None:
    actor = ActorContext(
        organization_id=None,
        actor_id="user_concurrent_signup",
        auth_provider="clerk",
        email="fresh-signup@example.com",
        first_name="Fresh",
        last_name="Signup",
        image_url="https://img.clerk.test/fresh.png",
    )

    with client.app.state.testing_session_local() as seed_db:
        seed_db.add(
            User(
                id=actor.actor_id,
                auth_provider="clerk",
                email=None,
                first_name=None,
                last_name=None,
                image_url=None,
            )
        )
        seed_db.commit()

    with client.app.state.testing_session_local() as db:
        original_get = db.get
        first_user_lookup = True

        def stale_user_lookup(entity, ident, *args, **kwargs):
            nonlocal first_user_lookup
            if entity is User and ident == actor.actor_id and first_user_lookup:
                first_user_lookup = False
                return None
            return original_get(entity, ident, *args, **kwargs)

        monkeypatch.setattr(db, "get", stale_user_lookup)

        user = identity_module.ensure_user_record(db, actor=actor)

    assert user.id == actor.actor_id
    assert user.email == "fresh-signup@example.com"
    assert user.first_name == "Fresh"
    assert user.last_name == "Signup"
    assert user.image_url == "https://img.clerk.test/fresh.png"

    with client.app.state.testing_session_local() as db:
        users = db.execute(
            text("select id, email, first_name, last_name, image_url from users where id = :user_id"),
            {"user_id": actor.actor_id},
        ).all()

    assert users == [
        (
            "user_concurrent_signup",
            "fresh-signup@example.com",
            "Fresh",
            "Signup",
            "https://img.clerk.test/fresh.png",
        )
    ]


def test_clerk_user_record_does_not_commit_when_profile_is_unchanged(client, monkeypatch) -> None:
    actor = ActorContext(
        organization_id=None,
        actor_id="user_existing_profile",
        auth_provider="clerk",
        email="existing@example.com",
        first_name="Existing",
        last_name="Member",
        image_url="https://img.clerk.test/existing.png",
    )

    with client.app.state.testing_session_local() as seed_db:
        seed_db.add(
            User(
                id=actor.actor_id,
                auth_provider=actor.auth_provider,
                email=actor.email,
                first_name=actor.first_name,
                last_name=actor.last_name,
                image_url=actor.image_url,
            )
        )
        seed_db.commit()

    with client.app.state.testing_session_local() as db:
        commit_calls: list[bool] = []
        monkeypatch.setattr(db, "commit", lambda: commit_calls.append(True))

        user = identity_module.ensure_user_record(db, actor=actor)

        assert user.id == actor.actor_id
        assert commit_calls == []


def test_clerk_auth_mode_supports_create_join_and_approve_flow(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    jwks = _build_test_jwks(private_key=private_key, kid=kid)
    _configure_clerk_mode(monkeypatch, jwks=jwks)
    admin_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_admin_123",
        email="admin@example.com",
        first_name="Avery",
        last_name="Admin",
    )
    member_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_member_123",
        email="member@example.com",
        first_name="Morgan",
        last_name="Member",
    )

    create_org_response = client.post(
        "/organizations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Nimbus Press"},
    )
    assert create_org_response.status_code == 201
    created_org = create_org_response.json()["organization"]
    assert created_org["name"] == "Nimbus Press"
    assert created_org["join_code"]

    admin_session_response = client.get(
        "/session-context",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_session_response.status_code == 200
    assert admin_session_response.json()["onboarding_status"] == "approved"
    assert admin_session_response.json()["user"]["display_name"] == "admin@example.com"
    assert admin_session_response.json()["membership"]["role"] == "admin"
    assert admin_session_response.json()["organization"]["name"] == "Nimbus Press"
    assert admin_session_response.json()["organization"]["admin_name"] == "admin@example.com"

    create_join_request_response = client.post(
        "/organizations/join-requests",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"join_code": created_org["join_code"]},
    )
    assert create_join_request_response.status_code == 201
    join_request = create_join_request_response.json()["join_request"]
    assert join_request["status"] == "pending"

    member_pending_session_response = client.get(
        "/session-context",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert member_pending_session_response.status_code == 200
    assert member_pending_session_response.json()["onboarding_status"] == "pending"
    assert member_pending_session_response.json()["user"]["display_name"] == "member@example.com"
    assert member_pending_session_response.json()["pending_join_request"]["organization_name"] == "Nimbus Press"
    assert member_pending_session_response.json()["pending_join_request"]["requested_by_name"] == "member@example.com"
    assert member_pending_session_response.json()["pending_join_request"]["requested_by_email"] == "member@example.com"

    pending_requests_response = client.get(
        "/organizations/join-requests",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert pending_requests_response.status_code == 200
    assert pending_requests_response.json()["pending_request_count"] == 1
    assert pending_requests_response.json()["join_requests"][0]["requested_by_name"] == "member@example.com"

    member_admin_settings_response = client.get(
        "/pod-providers/printify/credentials/status",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert member_admin_settings_response.status_code == 403

    approve_response = client.post(
        f"/organizations/join-requests/{join_request['id']}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_response.status_code == 200

    member_approved_session_response = client.get(
        "/session-context",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert member_approved_session_response.status_code == 200
    assert member_approved_session_response.json()["onboarding_status"] == "approved"
    assert member_approved_session_response.json()["user"]["display_name"] == "member@example.com"
    assert member_approved_session_response.json()["membership"]["role"] == "member"
    assert member_approved_session_response.json()["organization"]["name"] == "Nimbus Press"
    assert member_approved_session_response.json()["organization"]["admin_name"] == "admin@example.com"

    with client.app.state.testing_session_local() as db:
        organizations = db.execute(
            text("select id, auth_provider, name from organizations order by id"),
        ).all()
        users = db.execute(
            text("select id, auth_provider from users order by id"),
        ).all()
        memberships = db.execute(
            text("select organization_id, user_id, role from memberships order by organization_id, user_id"),
        ).all()

    assert organizations == [(created_org["id"], "clerk", "Nimbus Press")]
    assert users == [("user_admin_123", "clerk"), ("user_member_123", "clerk")]
    assert memberships == [
        (created_org["id"], "user_admin_123", "admin"),
        (created_org["id"], "user_member_123", "member"),
    ]


def test_clerk_member_can_leave_current_organization(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    jwks = _build_test_jwks(private_key=private_key, kid=kid)
    _configure_clerk_mode(monkeypatch, jwks=jwks)
    admin_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_admin_leave_member",
        email="admin-leave-member@example.com",
    )
    member_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_member_leave_member",
        email="member-leave-member@example.com",
    )

    create_org_response = client.post(
        "/organizations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Leave Flow Org"},
    )
    assert create_org_response.status_code == 201
    join_code = create_org_response.json()["organization"]["join_code"]

    join_request_response = client.post(
        "/organizations/join-requests",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"join_code": join_code},
    )
    assert join_request_response.status_code == 201

    approve_response = client.post(
        f"/organizations/join-requests/{join_request_response.json()['join_request']['id']}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_response.status_code == 200

    leave_response = client.post(
        "/organizations/leave",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert leave_response.status_code == 200
    assert leave_response.json()["session_context"]["onboarding_status"] == "needs_organization"
    assert leave_response.json()["session_context"]["organization"] is None
    assert leave_response.json()["session_context"]["membership"] is None

    member_session_response = client.get(
        "/session-context",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert member_session_response.status_code == 200
    assert member_session_response.json()["onboarding_status"] == "needs_organization"

    with client.app.state.testing_session_local() as db:
        memberships = db.execute(
            text("select organization_id, user_id, role from memberships order by organization_id, user_id"),
        ).all()

    assert memberships == [(create_org_response.json()["organization"]["id"], "user_admin_leave_member", "admin")]


def test_clerk_admin_can_list_members_and_remove_member(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    jwks = _build_test_jwks(private_key=private_key, kid=kid)
    _configure_clerk_mode(monkeypatch, jwks=jwks)
    admin_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_admin_manage_members",
        email="admin-manage-members@example.com",
    )
    member_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_member_manage_members",
        email="member-manage-members@example.com",
    )

    create_org_response = client.post(
        "/organizations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Membership Admin Org"},
    )
    assert create_org_response.status_code == 201
    organization_id = create_org_response.json()["organization"]["id"]
    join_code = create_org_response.json()["organization"]["join_code"]

    join_request_response = client.post(
        "/organizations/join-requests",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"join_code": join_code},
    )
    assert join_request_response.status_code == 201

    approve_response = client.post(
        f"/organizations/join-requests/{join_request_response.json()['join_request']['id']}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_response.status_code == 200

    members_response = client.get(
        "/organizations/members",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert members_response.status_code == 200
    members_payload = members_response.json()
    assert members_payload["member_count"] == 2

    admin_member = next(item for item in members_payload["members"] if item["user_id"] == "user_admin_manage_members")
    removed_member = next(item for item in members_payload["members"] if item["user_id"] == "user_member_manage_members")
    assert admin_member["role"] == "admin"
    assert admin_member["is_current_user"] is True
    assert admin_member["is_removable"] is False
    assert removed_member["role"] == "member"
    assert removed_member["is_current_user"] is False
    assert removed_member["is_removable"] is True

    remove_response = client.post(
        "/organizations/members/user_member_manage_members/remove",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert remove_response.status_code == 200
    assert remove_response.json()["member"]["user_id"] == "user_member_manage_members"

    removed_member_session_response = client.get(
        "/session-context",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert removed_member_session_response.status_code == 200
    assert removed_member_session_response.json()["onboarding_status"] == "needs_organization"
    assert removed_member_session_response.json()["organization"] is None
    assert removed_member_session_response.json()["membership"] is None

    refreshed_members_response = client.get(
        "/organizations/members",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert refreshed_members_response.status_code == 200
    assert refreshed_members_response.json()["member_count"] == 1

    with client.app.state.testing_session_local() as db:
        memberships = db.execute(
            text("select organization_id, user_id, role from memberships order by organization_id, user_id"),
        ).all()

    assert memberships == [(organization_id, "user_admin_manage_members", "admin")]


def test_clerk_admin_cannot_remove_self_from_member_management(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    jwks = _build_test_jwks(private_key=private_key, kid=kid)
    _configure_clerk_mode(monkeypatch, jwks=jwks)
    admin_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_admin_remove_self_blocked",
        email="admin-remove-self-blocked@example.com",
    )

    create_org_response = client.post(
        "/organizations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Self Remove Blocked Org"},
    )
    assert create_org_response.status_code == 201

    remove_response = client.post(
        "/organizations/members/user_admin_remove_self_blocked/remove",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert remove_response.status_code == 409
    assert (
        remove_response.json()["detail"]
        == "Use the leave organization flow to remove yourself from the workspace."
    )


def test_clerk_admin_leave_transfers_organization_to_remaining_member(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    jwks = _build_test_jwks(private_key=private_key, kid=kid)
    _configure_clerk_mode(monkeypatch, jwks=jwks)
    admin_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_admin_leave_transfer",
        email="admin-leave-transfer@example.com",
    )
    member_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_member_leave_transfer",
        email="member-leave-transfer@example.com",
    )

    create_org_response = client.post(
        "/organizations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Transfer Org"},
    )
    assert create_org_response.status_code == 201
    organization_id = create_org_response.json()["organization"]["id"]
    join_code = create_org_response.json()["organization"]["join_code"]

    join_request_response = client.post(
        "/organizations/join-requests",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"join_code": join_code},
    )
    assert join_request_response.status_code == 201

    approve_response = client.post(
        f"/organizations/join-requests/{join_request_response.json()['join_request']['id']}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_response.status_code == 200

    leave_response = client.post(
        "/organizations/leave",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert leave_response.status_code == 200
    assert leave_response.json()["session_context"]["onboarding_status"] == "needs_organization"

    member_session_response = client.get(
        "/session-context",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert member_session_response.status_code == 200
    assert member_session_response.json()["onboarding_status"] == "approved"
    assert member_session_response.json()["membership"]["role"] == "admin"
    assert member_session_response.json()["organization"]["admin_user_id"] == "user_member_leave_transfer"
    assert (
        member_session_response.json()["organization"]["admin_name"]
        == "member-leave-transfer@example.com"
    )

    with client.app.state.testing_session_local() as db:
        organizations = db.execute(
            text("select id, created_by_user_id from organizations where id = :organization_id"),
            {"organization_id": organization_id},
        ).all()
        memberships = db.execute(
            text("select organization_id, user_id, role from memberships order by organization_id, user_id"),
        ).all()

    assert organizations == [(organization_id, "user_member_leave_transfer")]
    assert memberships == [(organization_id, "user_member_leave_transfer", "admin")]


def test_clerk_admin_cannot_leave_last_member_organization(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    jwks = _build_test_jwks(private_key=private_key, kid=kid)
    _configure_clerk_mode(monkeypatch, jwks=jwks)
    admin_token = _build_test_token(
        private_key=private_key,
        kid=kid,
        user_id="user_admin_leave_blocked",
        email="admin-leave-blocked@example.com",
    )

    create_org_response = client.post(
        "/organizations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Blocked Leave Org"},
    )
    assert create_org_response.status_code == 201

    leave_response = client.post(
        "/organizations/leave",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert leave_response.status_code == 409
    assert (
        leave_response.json()["detail"]
        == "You must transfer organization ownership before leaving the only admin role."
    )


def test_clerk_auth_mode_rejects_request_when_jwks_lookup_fails(client, monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "test-key"
    _configure_clerk_mode(monkeypatch, jwks=_build_test_jwks(private_key=private_key, kid=kid))
    monkeypatch.setattr(auth_module, "fetch_jwks", lambda _url: (_ for _ in ()).throw(httpx.ConnectError("boom")))
    token = _build_test_token(private_key=private_key, kid=kid, user_id="user_test_123")

    response = client.get("/pod-providers", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Unable to verify session token."
