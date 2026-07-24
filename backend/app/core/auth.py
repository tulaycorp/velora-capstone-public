from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import settings


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class VerifiedClerkSession:
    actor_id: str
    organization_id: str | None
    organization_slug: str | None
    session_id: str | None
    org_role: str | None
    email: str | None
    first_name: str | None
    last_name: str | None
    image_url: str | None
    claims: dict[str, Any]


_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _b64url_decode(value: str) -> bytes:
    padding_length = (-len(value)) % 4
    return base64.urlsafe_b64decode(value + ("=" * padding_length))


def _decode_json_segment(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(_b64url_decode(value).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthError("Invalid session token.") from exc
    if not isinstance(payload, dict):
        raise AuthError("Invalid session token.")
    return payload


def _read_numeric_claim(claims: dict[str, Any], key: str) -> int | None:
    value = claims.get(key)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise AuthError("Invalid session token.")


def _build_rsa_public_key(jwk: dict[str, Any]) -> rsa.RSAPublicKey:
    n_value = jwk.get("n")
    e_value = jwk.get("e")
    if not isinstance(n_value, str) or not isinstance(e_value, str):
        raise AuthError("Invalid JWKS response.")
    modulus = int.from_bytes(_b64url_decode(n_value), "big")
    exponent = int.from_bytes(_b64url_decode(e_value), "big")
    return rsa.RSAPublicNumbers(exponent, modulus).public_key()


def fetch_jwks(url: str) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Unable to verify session token.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise AuthError("Invalid JWKS response.")
    return payload


def _get_jwks(url: str, *, force_refresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    cached = _JWKS_CACHE.get(url)
    if not force_refresh and cached and cached[0] > now:
        return cached[1]
    try:
        payload = fetch_jwks(url)
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("Unable to verify session token.") from exc
    _JWKS_CACHE[url] = (now + settings.clerk_jwks_cache_ttl_seconds, payload)
    return payload


def _resolve_jwk(jwks: dict[str, Any], kid: str) -> dict[str, Any]:
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise AuthError("Invalid JWKS response.")
    for key in keys:
        if isinstance(key, dict) and key.get("kid") == kid:
            return key
    raise AuthError("Unknown signing key.")


def verify_clerk_session_token(token: str) -> VerifiedClerkSession:
    if not settings.clerk_jwks_url:
        raise AuthError("Clerk JWKS URL is not configured.")

    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Invalid session token.")

    header = _decode_json_segment(parts[0])
    claims = _decode_json_segment(parts[1])
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")

    algorithm = header.get("alg")
    kid = header.get("kid")
    if algorithm != "RS256" or not isinstance(kid, str) or not kid.strip():
        raise AuthError("Invalid session token.")

    try:
        signature = _b64url_decode(parts[2])
    except ValueError as exc:
        raise AuthError("Invalid session token.") from exc

    jwks = _get_jwks(settings.clerk_jwks_url)
    try:
        jwk = _resolve_jwk(jwks, kid)
    except AuthError:
        jwk = _resolve_jwk(_get_jwks(settings.clerk_jwks_url, force_refresh=True), kid)
    public_key = _build_rsa_public_key(jwk)
    try:
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise AuthError("Invalid session token.") from exc

    now = int(time.time())
    clock_skew = settings.clerk_clock_skew_seconds
    not_before = _read_numeric_claim(claims, "nbf")
    expires_at = _read_numeric_claim(claims, "exp")
    if not_before is not None and now + clock_skew < not_before:
        raise AuthError("Session token is not active yet.")
    if expires_at is None:
        raise AuthError("Session token is missing an expiration.")
    if now - clock_skew >= expires_at:
        raise AuthError("Session token has expired.")

    if settings.clerk_issuer:
        issuer = claims.get("iss")
        if issuer != settings.clerk_issuer:
            raise AuthError("Invalid session issuer.")

    authorized_parties = settings.clerk_authorized_parties
    authorized_party = claims.get("azp")
    if authorized_parties:
        if not isinstance(authorized_party, str) or authorized_party not in authorized_parties:
            raise AuthError("Invalid authorized party.")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthError("Invalid session token.")

    org_claim = claims.get("o")
    org_id = claims.get("org_id")
    org_slug = claims.get("org_slug")
    org_role = claims.get("org_role")
    if not isinstance(org_id, str):
        org_id = None
    if not isinstance(org_slug, str):
        org_slug = None
    if not isinstance(org_role, str):
        org_role = None
    if org_id is None and isinstance(org_claim, dict):
        nested_org_id = org_claim.get("id")
        nested_org_slug = org_claim.get("slg")
        nested_org_role = org_claim.get("rol")
        if isinstance(nested_org_id, str):
            org_id = nested_org_id
        if org_slug is None and isinstance(nested_org_slug, str):
            org_slug = nested_org_slug
        if org_role is None and isinstance(nested_org_role, str):
            org_role = nested_org_role

    session_id = claims.get("sid")
    if not isinstance(session_id, str):
        session_id = None

    first_name = claims.get("first_name")
    if not isinstance(first_name, str):
        first_name = None

    last_name = claims.get("last_name")
    if not isinstance(last_name, str):
        last_name = None

    image_url = claims.get("image_url")
    if not isinstance(image_url, str):
        image_url = None

    email = None
    primary_email = claims.get("email")
    if isinstance(primary_email, str):
        email = primary_email
    elif isinstance(claims.get("email_addresses"), list):
        for candidate in claims["email_addresses"]:
            if isinstance(candidate, dict):
                address = candidate.get("email_address")
                if isinstance(address, str):
                    email = address
                    break

    return VerifiedClerkSession(
        actor_id=subject,
        organization_id=org_id,
        organization_slug=org_slug,
        session_id=session_id,
        org_role=org_role,
        email=email,
        first_name=first_name,
        last_name=last_name,
        image_url=image_url,
        claims=claims,
    )
