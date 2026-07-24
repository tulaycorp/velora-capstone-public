from __future__ import annotations

import base64
from collections.abc import Iterable, Mapping
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import secrets
from threading import Lock
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.distributed_rate_limit import RateLimiterUnavailable, wait_for_redis_sliding_window_slot
from app.core.logging import get_logger, log_event, summarize_mapping_for_log
from app.db.encryption import decrypt_value, encrypt_value
from app.db.models import OAuthRequestState

etsy_logger = get_logger("etsy")

_TOKEN_REFRESH_LOCK = Lock()
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_RATE_LIMIT_LOCK = Lock()
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = {}
_REDIS_LIMITER_WARNING_COOLDOWN_SECONDS = 60.0
_LAST_REDIS_LIMITER_WARNING_AT = 0.0
ETSY_OAUTH_SCOPES = ("shops_r", "listings_r", "listings_w", "transactions_r")
_OAUTH_STATE_VERSION = 1
ETSY_LISTING_IMAGE_LIMIT = 10


@dataclass(frozen=True)
class EtsyListingImageUpload:
    file_name: str
    content_type: str
    content: bytes


def _missing_etsy_app_settings() -> list[str]:
    required = {
        "VELORA_ETSY_API_KEYSTRING": settings.etsy_api_keystring,
        "VELORA_ETSY_SHARED_SECRET": settings.etsy_shared_secret,
    }
    return [key for key, value in required.items() if not str(value or "").strip()]


def _missing_etsy_direct_edit_settings() -> list[str]:
    required = {
        "VELORA_ETSY_API_KEYSTRING": settings.etsy_api_keystring,
        "VELORA_ETSY_SHARED_SECRET": settings.etsy_shared_secret,
        "VELORA_ETSY_REFRESH_TOKEN": settings.etsy_refresh_token,
    }
    return [key for key, value in required.items() if not str(value or "").strip()]


def _missing_etsy_oauth_settings() -> list[str]:
    required = {
        "VELORA_ETSY_API_KEYSTRING": settings.etsy_api_keystring,
        "VELORA_ETSY_SHARED_SECRET": settings.etsy_shared_secret,
        "VELORA_ETSY_OAUTH_REDIRECT_URI": settings.etsy_oauth_redirect_uri,
    }
    return [key for key, value in required.items() if not str(value or "").strip()]


def get_etsy_oauth_scopes() -> list[str]:
    return list(ETSY_OAUTH_SCOPES)


def _resolve_etsy_shop_id(raw_data: Mapping[str, Any] | None) -> str:
    return _resolve_etsy_shop_id_with_fallbacks(etsy_shop_id=None, raw_data=raw_data)


def _resolve_etsy_shop_id_with_fallbacks(
    *,
    etsy_shop_id: str | None,
    raw_data: Mapping[str, Any] | None,
) -> str:
    candidates = [
        etsy_shop_id,
        raw_data.get("etsy_shop_id") if raw_data else None,
        raw_data.get("marketplace_shop_id") if raw_data else None,
    ]
    nested_collections = [
        raw_data.get("sales_channel_properties") if raw_data else None,
        raw_data.get("marketplace") if raw_data else None,
        raw_data.get("marketplace_data") if raw_data else None,
        raw_data.get("external") if raw_data else None,
        raw_data.get("manual_seed") if raw_data else None,
    ]
    for collection in nested_collections:
        mappings: list[Mapping[str, Any]] = []
        if isinstance(collection, Mapping):
            mappings.append(collection)
        elif isinstance(collection, list):
            mappings.extend(item for item in collection if isinstance(item, Mapping))
        for item in mappings:
            candidates.extend(
                [
                    item.get("etsy_shop_id"),
                    item.get("marketplace_shop_id"),
                    item.get("shop_id"),
                    item.get("shopId"),
                    item.get("etsyShopId"),
                    item.get("marketplaceShopId"),
                ]
            )
    candidates.append(settings.etsy_shop_id)
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    raise HTTPException(
        status_code=409,
        detail=(
            "Direct Etsy listing edits require an Etsy shop id. "
            "Set VELORA_ETSY_SHOP_ID or store an etsy_shop_id on the store connection."
        ),
    )


def _ensure_etsy_direct_edit_is_configured() -> None:
    missing = _missing_etsy_direct_edit_settings()
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Published Etsy products now save listing info directly to Etsy. "
                f"Configure {', '.join(missing)} in backend/.env before editing Etsy listing fields."
            ),
        )


def _ensure_etsy_oauth_is_configured() -> None:
    missing = _missing_etsy_oauth_settings()
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Etsy account connection requires Etsy OAuth settings. "
                f"Configure {', '.join(missing)} in backend/.env before connecting Etsy."
            ),
        )


def _ensure_etsy_api_app_is_configured() -> None:
    missing = _missing_etsy_app_settings()
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Etsy API access requires Etsy app credentials. "
                f"Configure {', '.join(missing)} in backend/.env before continuing."
            ),
        )


def _build_api_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": f"{settings.etsy_api_keystring}:{settings.etsy_shared_secret}",
        "User-Agent": settings.etsy_user_agent,
    }


def _build_pkce_code_verifier() -> str:
    verifier = secrets.token_urlsafe(72)
    return verifier[:128]


def _build_pkce_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _hash_oauth_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _coerce_utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _encode_oauth_state(payload: dict[str, Any]) -> str:
    return encrypt_value(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _decode_oauth_state(state: str) -> dict[str, Any]:
    try:
        raw_payload = decrypt_value(state)
        payload = json.loads(raw_payload)
    except Exception as exc:  # pragma: no cover - defensive against malformed encrypted state
        raise HTTPException(status_code=400, detail="Invalid Etsy OAuth state.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Etsy OAuth state.")
    return payload


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if isinstance(payload, dict):
        for key in ("error", "error_description", "detail", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first_error = errors[0]
            if isinstance(first_error, str) and first_error.strip():
                return first_error.strip()
            if isinstance(first_error, dict):
                for key in ("detail", "message", "error"):
                    value = first_error.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return summarize_mapping_for_log(payload)

    if isinstance(payload, list) and payload:
        first_item = payload[0]
        if isinstance(first_item, str) and first_item.strip():
            return first_item.strip()
        if isinstance(first_item, dict):
            return summarize_mapping_for_log(first_item)

    if isinstance(payload, str) and payload.strip():
        return payload.strip()

    return response.reason_phrase or "Unknown Etsy API error"


def _raise_for_etsy_error(response: httpx.Response, *, action: str) -> None:
    detail = _extract_error_detail(response)
    raise HTTPException(
        status_code=502,
        detail=f"Etsy {action} failed: {detail}",
    )


def build_etsy_oauth_authorization(
    *,
    actor_id: str,
    organization_id: str,
    expected_seller_user_id: str | None = None,
) -> dict[str, Any]:
    _ensure_etsy_oauth_is_configured()

    redirect_uri = str(settings.etsy_oauth_redirect_uri or "").strip()
    scopes = get_etsy_oauth_scopes()
    code_verifier = _build_pkce_code_verifier()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.etsy_oauth_state_ttl_seconds)
    state = _encode_oauth_state(
        {
            "v": _OAUTH_STATE_VERSION,
            "actor_id": actor_id,
            "organization_id": organization_id,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "scopes": scopes,
            "expected_seller_user_id": str(expected_seller_user_id or "").strip() or None,
            "expires_at": expires_at.isoformat(),
        }
    )
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.etsy_api_keystring,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": _build_pkce_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return {
        "authorization_url": f"https://www.etsy.com/oauth/connect?{params}",
        "state": state,
        "redirect_uri": redirect_uri,
        "expires_at": expires_at,
        "scopes": scopes,
    }


def register_etsy_oauth_state_request(
    db: Session,
    *,
    actor_id: str,
    organization_id: str,
    state: str,
    expires_at: datetime,
) -> None:
    db.add(
        OAuthRequestState(
            organization_id=organization_id,
            actor_id=actor_id,
            provider="etsy",
            state_digest=_hash_oauth_state(state),
            expires_at=expires_at,
        )
    )
    db.commit()


def _validate_oauth_state(
    *,
    state: str,
    actor_id: str,
    organization_id: str,
) -> dict[str, Any]:
    payload = _decode_oauth_state(state)
    if payload.get("v") != _OAUTH_STATE_VERSION:
        raise HTTPException(status_code=400, detail="Invalid Etsy OAuth state version.")
    if str(payload.get("actor_id") or "") != actor_id:
        raise HTTPException(status_code=403, detail="This Etsy OAuth response belongs to a different user.")
    if str(payload.get("organization_id") or "") != organization_id:
        raise HTTPException(
            status_code=403,
            detail="This Etsy OAuth response belongs to a different organization.",
        )

    expires_at_raw = str(payload.get("expires_at") or "").strip()
    try:
        expires_at = datetime.fromisoformat(expires_at_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Etsy OAuth expiration.") from exc

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This Etsy OAuth request has expired. Start again from Settings.")
    return payload


def _consume_etsy_oauth_state_request(
    db: Session,
    *,
    actor_id: str,
    organization_id: str,
    state: str,
    expires_at: datetime,
) -> None:
    row = db.scalar(
        select(OAuthRequestState).where(
            OAuthRequestState.organization_id == organization_id,
            OAuthRequestState.actor_id == actor_id,
            OAuthRequestState.provider == "etsy",
            OAuthRequestState.state_digest == _hash_oauth_state(state),
        ).with_for_update()
    )
    if row is None:
        raise HTTPException(
            status_code=400,
            detail="This Etsy add-account session is invalid or was already used. Start again from Settings.",
        )

    now = datetime.now(timezone.utc)
    if row.consumed_at is not None:
        raise HTTPException(
            status_code=400,
            detail="This Etsy add-account session was already used. Start again from Settings.",
        )
    if _coerce_utc_datetime(row.expires_at) <= now or _coerce_utc_datetime(expires_at) <= now:
        raise HTTPException(
            status_code=400,
            detail="This Etsy add-account session expired. Start again from Settings.",
        )

    row.consumed_at = now
    db.commit()


def _extract_token_user_id(token: str | None) -> str | None:
    value = str(token or "").strip()
    if "." not in value:
        return None
    prefix = value.split(".", 1)[0].strip()
    return prefix if prefix.isdigit() else None


def _get_token_cache_key(refresh_token: str | None) -> str:
    source = str(refresh_token or settings.etsy_refresh_token or "").strip()
    if not source:
        return "default"
    return hashlib.sha256(source.encode()).hexdigest()


def _get_cached_access_token(cache_key: str) -> str | None:
    cache_entry = _TOKEN_CACHE.get(cache_key) or {}
    access_token = cache_entry.get("access_token")
    expires_at = cache_entry.get("expires_at")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    if not isinstance(expires_at, datetime):
        return None
    if expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
        return None
    return access_token


def _get_rate_key() -> str:
    return str(settings.etsy_api_keystring or "").strip() or "etsy-default"


def _get_shared_rate_limiter_key(*, rate_key: str) -> str:
    return f"ratelimit:etsy:{rate_key}:global"


def _wait_for_rate_slot(*, rate_key: str) -> float:
    limit = max(1, int(settings.etsy_max_requests_per_second or 1))
    window_seconds = 1.0
    waited_seconds = 0.0

    while True:
        with _RATE_LIMIT_LOCK:
            now = time.monotonic()
            bucket = _RATE_LIMIT_BUCKETS.get(rate_key)
            if bucket is None:
                bucket = deque()
                _RATE_LIMIT_BUCKETS[rate_key] = bucket

            while bucket and (now - bucket[0]) >= window_seconds:
                bucket.popleft()

            if len(bucket) < limit:
                bucket.append(now)
                return waited_seconds

            wait_for = max(0.05, window_seconds - (now - bucket[0]))

        time.sleep(wait_for)
        waited_seconds += wait_for


def _log_redis_limiter_fallback_once(*, error: str) -> None:
    global _LAST_REDIS_LIMITER_WARNING_AT

    now = time.monotonic()
    if now - _LAST_REDIS_LIMITER_WARNING_AT < _REDIS_LIMITER_WARNING_COOLDOWN_SECONDS:
        return

    _LAST_REDIS_LIMITER_WARNING_AT = now
    log_event(
        etsy_logger,
        "etsy.rate_limit.redis_unavailable",
        level=logging.WARNING,
        error=error,
    )


def _wait_for_effective_rate_slot(*, rate_key: str) -> tuple[float, str]:
    shared_rate_key = _get_shared_rate_limiter_key(rate_key=rate_key)
    limit = max(1, int(settings.etsy_max_requests_per_second or 1))
    try:
        waited_seconds = wait_for_redis_sliding_window_slot(
            redis_key=shared_rate_key,
            limit=limit,
            window_seconds=1.0,
        )
        return waited_seconds, "redis"
    except RateLimiterUnavailable as exc:
        _log_redis_limiter_fallback_once(error=str(exc))
        waited_seconds = _wait_for_rate_slot(rate_key=rate_key)
        return waited_seconds, "local_fallback"


def _safe_response_payload_for_log(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _parse_retry_after_seconds(value: str | None, *, fallback: float) -> float:
    raw_value = str(value or "").strip()
    if not raw_value:
        return fallback
    try:
        return max(float(raw_value), 0.0)
    except ValueError:
        return fallback


def _request_etsy(
    client: httpx.Client,
    *,
    method: str,
    path: str,
    action: str,
    data: Mapping[str, Any] | None = None,
    json_payload: Mapping[str, Any] | None = None,
    files: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    rate_key = _get_rate_key()
    max_retries = max(0, int(settings.etsy_max_retry_attempts or 0))

    for attempt in range(max_retries + 1):
        waited_seconds, limiter_backend = _wait_for_effective_rate_slot(rate_key=rate_key)
        started_at = time.perf_counter()
        try:
            response = client.request(
                method,
                path,
                data=data,
                json=json_payload,
                files=files,
                headers=headers,
                timeout=timeout,
            )
        except httpx.RequestError as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            will_retry = attempt < max_retries
            log_event(
                etsy_logger,
                "etsy.http.request_error",
                level=logging.WARNING,
                verbose_only=True,
                action=action,
                method=method,
                path=path,
                attempt=attempt + 1,
                max_attempts=max_retries + 1,
                will_retry=will_retry,
                waited_ms=round(waited_seconds * 1000, 2),
                rate_limiter_backend=limiter_backend,
                duration_ms=duration_ms,
                error=str(exc),
            )
            if not will_retry:
                raise HTTPException(
                    status_code=502,
                    detail=f"Etsy {action} failed: request error ({exc}).",
                ) from exc
            retry_after = max(1.0, float(2**attempt))
            time.sleep(retry_after)
            continue

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response_payload = _safe_response_payload_for_log(response)
        retry_after = _parse_retry_after_seconds(response.headers.get("retry-after"), fallback=max(1.0, float(2**attempt)))
        will_retry = response.status_code == 429 and attempt < max_retries
        log_event(
            etsy_logger,
            "etsy.http.response",
            verbose_only=True,
            action=action,
            method=method,
            path=path,
            attempt=attempt + 1,
            max_attempts=max_retries + 1,
            status_code=response.status_code,
            will_retry=will_retry,
            retry_after_s=retry_after if response.status_code == 429 else None,
            waited_ms=round(waited_seconds * 1000, 2),
            rate_limiter_backend=limiter_backend,
            duration_ms=duration_ms,
            qps_limit=response.headers.get("x-limit-per-second"),
            qps_remaining=response.headers.get("x-remaining-this-secon")
            or response.headers.get("x-remaining-this-second"),
            qpd_limit=response.headers.get("x-limit-per-day"),
            qpd_remaining=response.headers.get("x-remaining-today"),
            response_summary=summarize_mapping_for_log(response_payload),
        )
        if will_retry:
            time.sleep(retry_after)
            continue
        return response

    raise RuntimeError("Unexpected Etsy request retry loop termination.")


def build_etsy_listing_edit_url(listing_id: str) -> str:
    normalized_listing_id = str(listing_id or "").strip()
    if not normalized_listing_id:
        raise ValueError("An Etsy listing id is required to build the listing editor URL.")
    return f"https://www.etsy.com/your/shops/me/listing-editor/edit/{normalized_listing_id}"


def _request_oauth_token(*, data: Mapping[str, str], action: str) -> dict[str, Any]:
    with httpx.Client(base_url=settings.etsy_api_base_url.rstrip("/")) as client:
        response = _request_etsy(
            client,
            method="POST",
            path="/public/oauth/token",
            action=action,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
    if response.status_code >= 400:
        _raise_for_etsy_error(response, action=action)

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Etsy {action} failed: invalid JSON response ({exc}).",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail=f"Etsy {action} failed: response was not a JSON object.",
        )
    return payload


def _refresh_access_token(refresh_token_override: str | None = None) -> str:
    _ensure_etsy_api_app_is_configured()

    cache_key = _get_token_cache_key(refresh_token_override)
    cached = _get_cached_access_token(cache_key)
    if cached:
        return cached

    with _TOKEN_REFRESH_LOCK:
        cached = _get_cached_access_token(cache_key)
        if cached:
            return cached

        refresh_token = str(
            refresh_token_override
            or (_TOKEN_CACHE.get(cache_key) or {}).get("refresh_token")
            or settings.etsy_refresh_token
            or ""
        ).strip()
        if not refresh_token:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Published Etsy products now save listing info directly to Etsy. "
                    "Connect Etsy from Settings or configure VELORA_ETSY_REFRESH_TOKEN in backend/.env before editing Etsy listing fields."
                ),
            )

        payload = _request_oauth_token(
            data={
                "grant_type": "refresh_token",
                "client_id": settings.etsy_api_keystring,
                "refresh_token": refresh_token,
            },
            action="token refresh",
        )

        access_token = str(payload.get("access_token") or "").strip()
        next_refresh_token = str(payload.get("refresh_token") or refresh_token).strip()
        expires_in = int(payload.get("expires_in") or 0)
        if not access_token or expires_in <= 0:
            raise HTTPException(
                status_code=502,
                detail="Etsy token refresh failed: response did not include a valid access token.",
            )

        _TOKEN_CACHE[cache_key] = {
            "access_token": access_token,
            "refresh_token": next_refresh_token,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        }
        return access_token


def get_cached_etsy_refresh_token(refresh_token_override: str | None = None) -> str | None:
    cache_key = _get_token_cache_key(refresh_token_override)
    cached_refresh_token = (_TOKEN_CACHE.get(cache_key) or {}).get("refresh_token")
    if isinstance(cached_refresh_token, str) and cached_refresh_token.strip():
        return cached_refresh_token.strip()

    fallback_refresh_token = str(refresh_token_override or settings.etsy_refresh_token or "").strip()
    return fallback_refresh_token or None


def exchange_etsy_authorization_code(
    *,
    db: Session | None = None,
    code: str,
    state: str,
    actor_id: str,
    organization_id: str,
) -> dict[str, Any]:
    _ensure_etsy_oauth_is_configured()
    payload = _validate_oauth_state(
        state=state,
        actor_id=actor_id,
        organization_id=organization_id,
    )
    if db is not None:
        expires_at_raw = str(payload.get("expires_at") or "").strip()
        expires_at = datetime.fromisoformat(expires_at_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        _consume_etsy_oauth_state_request(
            db,
            actor_id=actor_id,
            organization_id=organization_id,
            state=state,
            expires_at=expires_at,
        )

    redirect_uri = str(payload.get("redirect_uri") or "").strip()
    code_verifier = str(payload.get("code_verifier") or "").strip()
    if not redirect_uri or not code_verifier:
        raise HTTPException(status_code=400, detail="Invalid Etsy OAuth request state.")

    token_payload = _request_oauth_token(
        data={
            "grant_type": "authorization_code",
            "client_id": str(settings.etsy_api_keystring or ""),
            "redirect_uri": redirect_uri,
            "code": code.strip(),
            "code_verifier": code_verifier,
        },
        action="authorization code exchange",
    )

    access_token = str(token_payload.get("access_token") or "").strip()
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    expires_in = int(token_payload.get("expires_in") or 0)
    if not access_token or not refresh_token or expires_in <= 0:
        raise HTTPException(
            status_code=502,
            detail="Etsy authorization code exchange failed: response did not include valid tokens.",
        )

    seller_user_id = fetch_etsy_authenticated_user_id(access_token=access_token)
    expected_seller_user_id = str(payload.get("expected_seller_user_id") or "").strip()
    if expected_seller_user_id and seller_user_id != expected_seller_user_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Etsy returned a different seller account. Sign out of Etsy and authorize "
                "the account selected in Velora."
            ),
        )
    shops = fetch_etsy_shops(access_token=access_token, user_id=seller_user_id)
    cache_key = _get_token_cache_key(refresh_token)
    _TOKEN_CACHE[cache_key] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }
    return {
        "refresh_token": refresh_token,
        "seller_user_id": seller_user_id,
        "scopes": payload.get("scopes") if isinstance(payload.get("scopes"), list) else get_etsy_oauth_scopes(),
        "shops": shops,
    }


def fetch_etsy_authenticated_user_id(*, access_token: str) -> str:
    _ensure_etsy_api_app_is_configured()
    with httpx.Client(
        base_url=settings.etsy_api_base_url.rstrip("/"),
        headers=_build_api_headers(access_token),
        timeout=30.0,
    ) as client:
        response = _request_etsy(
            client,
            method="GET",
            path="/application/users/me",
            action="user lookup",
            timeout=30.0,
        )
        if response.status_code >= 400:
            _raise_for_etsy_error(response, action="user lookup")

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Etsy user lookup failed: invalid JSON response ({exc}).",
            ) from exc

    if isinstance(payload, dict):
        for key in ("user_id", "userId", "id"):
            value = _extract_token_user_id(str(payload.get(key) or "")) or str(payload.get(key) or "").strip()
            if value and value.isdigit():
                return value

    token_user_id = _extract_token_user_id(access_token)
    if token_user_id:
        return token_user_id

    raise HTTPException(
        status_code=502,
        detail="Etsy user lookup failed: response did not include a valid user id.",
    )


def fetch_etsy_shops(*, access_token: str, user_id: str) -> list[dict[str, Any]]:
    _ensure_etsy_api_app_is_configured()
    with httpx.Client(
        base_url=settings.etsy_api_base_url.rstrip("/"),
        headers=_build_api_headers(access_token),
        timeout=30.0,
    ) as client:
        response = _request_etsy(
            client,
            method="GET",
            path=f"/application/users/{user_id}/shops",
            action="shop discovery",
            timeout=30.0,
        )
        if response.status_code >= 400:
            _raise_for_etsy_error(response, action="shop discovery")

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Etsy shop discovery failed: invalid JSON response ({exc}).",
            ) from exc

    raw_results: list[Any]
    if isinstance(payload, dict):
        nested_results = payload.get("results")
        if isinstance(nested_results, list):
            raw_results = nested_results
        elif any(key in payload for key in ("shop_id", "shopId", "id", "shop_name", "shopName", "title", "name")):
            raw_results = [payload]
        else:
            raise HTTPException(
                status_code=502,
                detail="Etsy shop discovery failed: response did not include a results list.",
            )
    elif isinstance(payload, list):
        raw_results = payload
    else:
        raise HTTPException(
            status_code=502,
            detail="Etsy shop discovery failed: response was not a list.",
        )

    shops: list[dict[str, Any]] = []
    for raw_shop in raw_results:
        if not isinstance(raw_shop, dict):
            continue
        shop_id = str(
            raw_shop.get("shop_id")
            or raw_shop.get("shopId")
            or raw_shop.get("id")
            or ""
        ).strip()
        if not shop_id:
            continue
        shop_name = str(
            raw_shop.get("shop_name")
            or raw_shop.get("shopName")
            or raw_shop.get("title")
            or raw_shop.get("name")
            or shop_id
        ).strip()
        shop_url = str(
            raw_shop.get("url")
            or raw_shop.get("shop_url")
            or raw_shop.get("shopUrl")
            or ""
        ).strip() or None
        shops.append(
            {
                "shop_id": shop_id,
                "shop_name": shop_name or shop_id,
                "shop_url": shop_url,
            }
        )

    return shops


def fetch_etsy_shop(*, access_token: str, shop_id: str) -> dict[str, Any]:
    _ensure_etsy_api_app_is_configured()
    with httpx.Client(
        base_url=settings.etsy_api_base_url.rstrip("/"),
        headers=_build_api_headers(access_token),
        timeout=30.0,
    ) as client:
        response = _request_etsy(
            client,
            method="GET",
            path=f"/application/shops/{shop_id}",
            action="shop metrics lookup",
            timeout=30.0,
        )
        if response.status_code >= 400:
            _raise_for_etsy_error(response, action="shop metrics lookup")

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Etsy shop metrics lookup failed: invalid JSON response ({exc}).",
            ) from exc

    if isinstance(payload, dict):
        nested_results = payload.get("results")
        if isinstance(nested_results, list) and nested_results and isinstance(nested_results[0], dict):
            return nested_results[0]
        if any(key in payload for key in ("shop_id", "shopId", "id", "shop_name", "shopName", "title", "name")):
            return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    raise HTTPException(
        status_code=502,
        detail="Etsy shop metrics lookup failed: response did not include a shop object.",
    )


def fetch_etsy_shop_receipts(
    *,
    access_token: str,
    shop_id: str,
    min_last_modified: datetime | None = None,
    max_last_modified: datetime | None = None,
) -> list[dict[str, Any]]:
    _ensure_etsy_api_app_is_configured()
    results: list[dict[str, Any]] = []
    offset = 0
    limit = 100
    with httpx.Client(
        base_url=settings.etsy_api_base_url.rstrip("/"),
        headers=_build_api_headers(access_token),
        timeout=30.0,
    ) as client:
        while True:
            query_params: dict[str, object] = {"limit": limit, "offset": offset}
            if min_last_modified is not None:
                query_params["min_last_modified"] = int(
                    _as_utc_timestamp(min_last_modified)
                )
            if max_last_modified is not None:
                query_params["max_last_modified"] = int(
                    _as_utc_timestamp(max_last_modified)
                )
            query = urlencode(query_params)
            response = _request_etsy(
                client,
                method="GET",
                path=f"/application/shops/{shop_id}/receipts?{query}",
                action="receipt list",
            )
            if response.status_code != 200:
                _raise_for_etsy_error(response, action="receipt list")
            payload = response.json()
            page = payload.get("results") if isinstance(payload, dict) else None
            page_rows = [item for item in (page or []) if isinstance(item, dict)]
            results.extend(page_rows)
            total = int(payload.get("count") or 0) if isinstance(payload, dict) else len(results)
            if len(page_rows) < limit or len(results) >= total:
                return results
            offset += limit


def fetch_etsy_receipt_transactions(
    *,
    access_token: str,
    shop_id: str,
    receipt_id: str,
) -> list[dict[str, Any]]:
    _ensure_etsy_api_app_is_configured()
    with httpx.Client(
        base_url=settings.etsy_api_base_url.rstrip("/"),
        headers=_build_api_headers(access_token),
        timeout=30.0,
    ) as client:
        response = _request_etsy(
            client,
            method="GET",
            path=f"/application/shops/{shop_id}/receipts/{receipt_id}/transactions",
            action="receipt transactions",
        )
        if response.status_code != 200:
            _raise_for_etsy_error(response, action="receipt transactions")
        payload = response.json()
        rows = payload.get("results") if isinstance(payload, dict) else None
        return [item for item in (rows or []) if isinstance(item, dict)]


def fetch_etsy_ledger_entries(
    *,
    access_token: str,
    shop_id: str,
    min_created: datetime,
    max_created: datetime,
) -> list[dict[str, Any]]:
    _ensure_etsy_api_app_is_configured()
    limit = 100
    windows: list[tuple[datetime, datetime]] = []
    window_start = min_created
    while window_start < max_created:
        window_end = min(window_start + timedelta(days=30), max_created)
        windows.append((window_start, window_end))
        window_start = window_end + timedelta(seconds=1)
    if not windows:
        return []

    worker_count = min(
        len(windows),
        max(1, int(settings.etsy_ledger_max_concurrency or 1)),
        max(1, int(settings.etsy_max_requests_per_second or 1)),
    )
    worker_windows = [windows[index::worker_count] for index in range(worker_count)]
    progress_lock = Lock()
    completed_windows = 0

    def fetch_windows(
        assigned_windows: list[tuple[datetime, datetime]],
    ) -> list[dict[str, Any]]:
        nonlocal completed_windows
        worker_results: list[dict[str, Any]] = []
        with httpx.Client(
            base_url=settings.etsy_api_base_url.rstrip("/"),
            headers=_build_api_headers(access_token),
            timeout=30.0,
        ) as client:
            for assigned_start, assigned_end in assigned_windows:
                offset = 0
                window_result_count = 0
                while True:
                    query = urlencode(
                        {
                            "min_created": int(_as_utc_timestamp(assigned_start)),
                            "max_created": int(_as_utc_timestamp(assigned_end)),
                            "limit": limit,
                            "offset": offset,
                        }
                    )
                    response = _request_etsy(
                        client,
                        method="GET",
                        path=(
                            f"/application/shops/{shop_id}/payment-account/"
                            f"ledger-entries?{query}"
                        ),
                        action="payment ledger",
                    )
                    if response.status_code != 200:
                        _raise_for_etsy_error(response, action="payment ledger")
                    payload = response.json()
                    page = payload.get("results") if isinstance(payload, dict) else None
                    page_rows = [
                        item for item in (page or []) if isinstance(item, dict)
                    ]
                    worker_results.extend(page_rows)
                    window_result_count += len(page_rows)
                    total = (
                        int(payload.get("count") or 0)
                        if isinstance(payload, dict)
                        else window_result_count
                    )
                    if len(page_rows) < limit or window_result_count >= total:
                        break
                    offset += limit

                with progress_lock:
                    completed_windows += 1
                    if (
                        completed_windows == 1
                        or completed_windows % 10 == 0
                        or completed_windows == len(windows)
                    ):
                        log_event(
                            etsy_logger,
                            "etsy.ledger_history.progress",
                            completed_windows=completed_windows,
                            total_windows=len(windows),
                        )
        return worker_results

    log_event(
        etsy_logger,
        "etsy.ledger_history.started",
        total_windows=len(windows),
        worker_count=worker_count,
    )
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="etsy-ledger",
    ) as executor:
        for worker_result in executor.map(fetch_windows, worker_windows):
            results.extend(worker_result)
    log_event(
        etsy_logger,
        "etsy.ledger_history.completed",
        total_windows=len(windows),
        entry_count=len(results),
    )
    return results


def _as_utc_timestamp(value: datetime) -> float:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).timestamp()


def _normalize_inventory_price(raw_price: Any) -> float:
    if isinstance(raw_price, (int, float)):
        return float(raw_price)
    if isinstance(raw_price, str):
        try:
            return float(raw_price)
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Etsy inventory returned an unsupported price value '{raw_price}'.",
            ) from exc
    if isinstance(raw_price, dict):
        amount = raw_price.get("amount")
        divisor = raw_price.get("divisor") or 1
        if amount is None:
            raise HTTPException(
                status_code=502,
                detail="Etsy inventory returned a price object without an amount.",
            )
        try:
            return float(amount) / float(divisor)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise HTTPException(
                status_code=502,
                detail="Etsy inventory returned a price object that could not be normalized.",
            ) from exc
    raise HTTPException(
        status_code=502,
        detail="Etsy inventory returned an unsupported price format.",
    )


def _normalize_inventory_update_products(
    *,
    products: list[Any],
    retail_price: float | None,
    sku: str | None,
) -> list[dict[str, Any]]:
    if sku is not None and len(products) != 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "This Etsy listing has multiple inventory variants. "
                "Velora can sync title, description, tags, and price directly, "
                "but SKU sync currently requires a single-SKU Etsy listing."
            ),
        )

    normalized_products: list[dict[str, Any]] = []
    for raw_product in products:
        if not isinstance(raw_product, dict):
            raise HTTPException(
                status_code=502,
                detail="Etsy inventory returned an unexpected product entry.",
            )
        raw_offerings = raw_product.get("offerings")
        raw_property_values = raw_product.get("property_values")
        if not isinstance(raw_offerings, list) or not raw_offerings:
            raise HTTPException(
                status_code=502,
                detail="Etsy inventory returned a product without offerings.",
            )
        if not isinstance(raw_property_values, list):
            raise HTTPException(
                status_code=502,
                detail="Etsy inventory returned a product without property values.",
            )

        normalized_offerings: list[dict[str, Any]] = []
        for raw_offering in raw_offerings:
            if not isinstance(raw_offering, dict):
                raise HTTPException(
                    status_code=502,
                    detail="Etsy inventory returned an unexpected offering entry.",
                )
            normalized_offering: dict[str, Any] = {
                "quantity": raw_offering.get("quantity"),
                "is_enabled": raw_offering.get("is_enabled"),
                "price": retail_price
                if retail_price is not None
                else _normalize_inventory_price(raw_offering.get("price")),
            }
            readiness_state_id = raw_offering.get("readiness_state_id")
            if readiness_state_id is not None:
                normalized_offering["readiness_state_id"] = readiness_state_id
            normalized_offerings.append(normalized_offering)

        normalized_property_values: list[dict[str, Any]] = []
        for raw_property_value in raw_property_values:
            if not isinstance(raw_property_value, dict):
                raise HTTPException(
                    status_code=502,
                    detail="Etsy inventory returned an unexpected property value entry.",
                )
            normalized_property_values.append(
                {
                    key: raw_property_value.get(key)
                    for key in (
                        "property_id",
                        "property_name",
                        "scale_id",
                        "value_ids",
                        "values",
                    )
                    if key in raw_property_value
                }
            )

        normalized_product: dict[str, Any] = {
            "sku": sku if sku is not None else raw_product.get("sku"),
            "offerings": normalized_offerings,
            "property_values": normalized_property_values,
        }
        normalized_products.append(normalized_product)

    return normalized_products


def sync_product_listing_to_etsy(
    *,
    listing_id: str,
    etsy_shop_id: str | None,
    refresh_token: str | None,
    title: str | None,
    description: str | None,
    tags: list[str] | None,
    retail_price: float | None,
    sku: str | None,
) -> None:
    access_token = _refresh_access_token(refresh_token)
    shop_id = _resolve_etsy_shop_id_with_fallbacks(
        etsy_shop_id=etsy_shop_id,
        raw_data=None,
    )
    headers = _build_api_headers(access_token)
    started_at = datetime.now(timezone.utc)

    with httpx.Client(
        base_url=settings.etsy_api_base_url.rstrip("/"),
        headers=headers,
        timeout=30.0,
    ) as client:
        metadata_payload: dict[str, Any] = {}
        if title is not None:
            metadata_payload["title"] = title
        if description is not None:
            metadata_payload["description"] = description
        if tags is not None:
            metadata_payload["tags"] = ",".join(tags)

        if metadata_payload:
            response = _request_etsy(
                client,
                method="PATCH",
                path=f"/application/shops/{shop_id}/listings/{listing_id}",
                action="listing update",
                data=metadata_payload,
                timeout=30.0,
            )
            if response.status_code >= 400:
                _raise_for_etsy_error(response, action="listing update")

        if retail_price is not None or sku is not None:
            inventory_response = _request_etsy(
                client,
                method="GET",
                path=f"/application/listings/{listing_id}/inventory",
                action="inventory fetch",
                timeout=30.0,
            )
            if inventory_response.status_code >= 400:
                _raise_for_etsy_error(inventory_response, action="inventory fetch")

            try:
                inventory_payload = inventory_response.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Etsy inventory fetch failed: invalid JSON response ({exc}).",
                ) from exc

            if not isinstance(inventory_payload, dict):
                raise HTTPException(
                    status_code=502,
                    detail="Etsy inventory fetch failed: response was not an object.",
                )

            raw_products = inventory_payload.get("products")
            if not isinstance(raw_products, list) or not raw_products:
                raise HTTPException(
                    status_code=502,
                    detail="Etsy inventory fetch failed: response did not include products.",
                )

            update_inventory_payload = {
                "products": _normalize_inventory_update_products(
                    products=raw_products,
                    retail_price=retail_price,
                    sku=sku,
                ),
                "price_on_property": inventory_payload.get("price_on_property") or [],
                "quantity_on_property": inventory_payload.get("quantity_on_property") or [],
                "sku_on_property": inventory_payload.get("sku_on_property") or [],
            }

            inventory_update_response = _request_etsy(
                client,
                method="PUT",
                path=f"/application/listings/{listing_id}/inventory",
                action="inventory update",
                json_payload=update_inventory_payload,
                timeout=30.0,
            )
            if inventory_update_response.status_code >= 400:
                _raise_for_etsy_error(inventory_update_response, action="inventory update")

    duration_ms = round((datetime.now(timezone.utc) - started_at).total_seconds() * 1000, 2)
    log_event(
        etsy_logger,
        "etsy.listing.synced",
        verbose_only=True,
        listing_id=listing_id,
        shop_id=shop_id,
        synced_fields=[
            field
            for field, value in (
                ("title", title),
                ("description", description),
                ("tags", tags),
                ("retail_price", retail_price),
                ("sku", sku),
            )
            if value is not None
        ],
        duration_ms=duration_ms,
    )


def sync_product_listing_images_to_etsy(
    *,
    listing_id: str,
    etsy_shop_id: str | None,
    refresh_token: str | None,
    images: Iterable[EtsyListingImageUpload],
) -> int:
    """Replace the Etsy listing gallery with Velora's ordered marketplace images."""
    access_token = _refresh_access_token(refresh_token)
    shop_id = _resolve_etsy_shop_id_with_fallbacks(
        etsy_shop_id=etsy_shop_id,
        raw_data=None,
    )
    headers = _build_api_headers(access_token)
    uploaded_count = 0
    started_at = datetime.now(timezone.utc)

    with httpx.Client(
        base_url=settings.etsy_api_base_url.rstrip("/"),
        headers=headers,
        timeout=60.0,
    ) as client:
        for rank, image in enumerate(images, start=1):
            if rank > ETSY_LISTING_IMAGE_LIMIT:
                raise HTTPException(
                    status_code=400,
                    detail=f"Etsy listing galleries are limited to {ETSY_LISTING_IMAGE_LIMIT} images in Velora.",
                )
            if not image.content:
                raise HTTPException(
                    status_code=400,
                    detail=f"The saved marketplace image '{image.file_name}' is empty.",
                )

            image_action = f"listing image {rank} '{image.file_name}' upload"
            log_event(
                etsy_logger,
                "etsy.listing.image_upload_started",
                verbose_only=True,
                listing_id=listing_id,
                shop_id=shop_id,
                rank=rank,
                file_name=image.file_name,
            )
            response = _request_etsy(
                client,
                method="POST",
                path=f"/application/shops/{shop_id}/listings/{listing_id}/images",
                action=image_action,
                data={"rank": rank, "overwrite": True},
                files={
                    "image": (
                        image.file_name,
                        image.content,
                        image.content_type or "application/octet-stream",
                    )
                },
                timeout=60.0,
            )
            if response.status_code >= 400:
                _raise_for_etsy_error(response, action=image_action)
            uploaded_count = rank
            log_event(
                etsy_logger,
                "etsy.listing.image_uploaded",
                verbose_only=True,
                listing_id=listing_id,
                shop_id=shop_id,
                rank=rank,
                file_name=image.file_name,
            )

        gallery_response = _request_etsy(
            client,
            method="GET",
            path=f"/application/listings/{listing_id}/images",
            action="listing image gallery fetch",
            timeout=30.0,
        )
        if gallery_response.status_code >= 400:
            _raise_for_etsy_error(gallery_response, action="listing image gallery fetch")
        try:
            gallery_payload = gallery_response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Etsy listing image gallery fetch failed: invalid JSON response ({exc}).",
            ) from exc

        raw_images = gallery_payload.get("results") if isinstance(gallery_payload, dict) else None
        if isinstance(raw_images, list):
            extra_images = sorted(
                (
                    item
                    for item in raw_images
                    if isinstance(item, dict)
                    and int(item.get("rank") or 0) > uploaded_count
                    and item.get("listing_image_id") is not None
                ),
                key=lambda item: int(item.get("rank") or 0),
                reverse=True,
            )
            for item in extra_images:
                listing_image_id = item["listing_image_id"]
                delete_response = _request_etsy(
                    client,
                    method="DELETE",
                    path=(
                        f"/application/shops/{shop_id}/listings/{listing_id}/images/"
                        f"{listing_image_id}"
                    ),
                    action="extra listing image removal",
                    timeout=30.0,
                )
                if delete_response.status_code >= 400:
                    _raise_for_etsy_error(delete_response, action="extra listing image removal")

    duration_ms = round((datetime.now(timezone.utc) - started_at).total_seconds() * 1000, 2)
    log_event(
        etsy_logger,
        "etsy.listing.images_synced",
        verbose_only=True,
        listing_id=listing_id,
        shop_id=shop_id,
        image_count=uploaded_count,
        duration_ms=duration_ms,
    )
    return uploaded_count
