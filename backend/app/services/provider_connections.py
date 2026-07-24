from __future__ import annotations

from collections.abc import Mapping
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import ActorContext
from app.core.logging import get_logger, log_event
from app.db.models import (
    Order,
    PodProduct,
    ProductBlueprint,
    ProviderCredential,
    ProviderProductDraft,
    ProviderStoreConnection,
    SyncEvent,
)
from app.db.encryption import active_encryption_key_id, decrypt_value, encrypt_value
from app.models import (
    EtsyConnectedAccountSummary,
    EtsyConnectionStatus,
    EtsyOAuthStartResponse,
    EtsyShopSummary,
    ManualStoreSeed,
    PodProvider,
    ProviderCredentialEntry,
    ProviderCredentialStatus,
    ProviderCredentialsUpsertRequest,
    ProviderStoreConnection as ProviderStoreConnectionSchema,
    ProviderStoreConnectionUpdateRequest,
    ProviderStoreConnectionSyncResponse,
)
from app.providers import get_provider_adapter
from app.services.etsy import (
    build_etsy_oauth_authorization,
    exchange_etsy_authorization_code,
    fetch_etsy_shop,
    fetch_etsy_shops,
    get_cached_etsy_refresh_token,
    get_etsy_oauth_scopes,
    register_etsy_oauth_state_request,
    _refresh_access_token,
)
from app.services.serializers import (
    to_provider_store_connection,
)


PROVIDER_METADATA: dict[str, dict[str, Any]] = {
    "printify": {
        "name": "Printify",
        "required_keys": ["api_token"],
        "available_storefronts": ["etsy", "shopify", "unknown"],
    },
    "gelato": {
        "name": "Gelato",
        "required_keys": ["api_key"],
        "available_storefronts": ["etsy", "shopify", "unknown"],
    },
}

CREDENTIAL_DISPLAY_NAME_KEY = "credential_display_name"
MANUAL_STORE_SEEDS_KEY = "manual_store_seeds_json"
DEFAULT_CREDENTIAL_KEY = "default"
CREDENTIAL_KEY_SEPARATOR = "::"
ETSY_CONNECTION_PROVIDER = "etsy"
ETSY_REFRESH_TOKEN_KEY = "oauth_refresh_token"
ETSY_SELLER_USER_ID_KEY = "oauth_seller_user_id"
ETSY_SCOPES_KEY = "oauth_scopes_json"
ETSY_SHOPS_KEY = "oauth_shops_json"
ETSY_LAST_SYNC_AT_KEY = "oauth_last_sync_at"
MAX_ETSY_STORE_CONNECTIONS = 5
commerce_logger = get_logger("commerce")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _provider_metadata(provider: str) -> dict[str, Any]:
    metadata = PROVIDER_METADATA.get(provider)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Unsupported provider '{provider}'.")
    return metadata


def _serialize_manual_store_seeds(seeds: list[dict[str, Any]]) -> str:
    return json.dumps(seeds, separators=(",", ":"), sort_keys=True)


def _deserialize_manual_store_seeds(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
            return []
    return data if isinstance(data, list) else []


def _deserialize_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _deserialize_json_array(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _list_etsy_connection_values(
    db: Session,
    *,
    organization_id: str,
) -> dict[str, dict[str, Any]]:
    grouped = _group_provider_credentials(
        _list_credential_rows(db, organization_id, ETSY_CONNECTION_PROVIDER)
    )
    keyed_accounts_exist = any(
        credential_key != DEFAULT_CREDENTIAL_KEY for credential_key in grouped
    )
    values_by_key: dict[str, dict[str, Any]] = {}
    for credential_key, raw_values in grouped.items():
        if keyed_accounts_exist and credential_key == DEFAULT_CREDENTIAL_KEY:
            continue

        values: dict[str, Any] = {}
        scopes_value = raw_values.get(ETSY_SCOPES_KEY)
        if isinstance(scopes_value, str):
            values["scopes"] = [
                str(item).strip()
                for item in _deserialize_json_array(scopes_value)
                if str(item).strip()
            ]

        shops_value = raw_values.get(ETSY_SHOPS_KEY)
        if isinstance(shops_value, str):
            values["shops"] = [
                item for item in _deserialize_json_array(shops_value) if isinstance(item, dict)
            ]

        for source_key, target_key in (
            (ETSY_LAST_SYNC_AT_KEY, "last_synced_at"),
            (ETSY_REFRESH_TOKEN_KEY, "refresh_token"),
            (ETSY_SELLER_USER_ID_KEY, "seller_user_id"),
        ):
            raw_value = raw_values.get(source_key)
            if isinstance(raw_value, str) and raw_value.strip():
                values[target_key] = raw_value

        resolved_key = credential_key
        seller_user_id = _normalize_optional_string(values.get("seller_user_id"))
        if credential_key == DEFAULT_CREDENTIAL_KEY and seller_user_id:
            resolved_key = seller_user_id

        values_by_key[resolved_key] = values
    return dict(sorted(values_by_key.items(), key=lambda item: item[0]))


def _get_etsy_connection_values(db: Session, *, organization_id: str) -> dict[str, Any]:
    return next(iter(_list_etsy_connection_values(db, organization_id=organization_id).values()), {})


def _upsert_secret_provider_credential(
    db: Session,
    *,
    organization_id: str,
    provider: str,
    key_name: str,
    value: str,
) -> None:
    existing = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == organization_id,
            ProviderCredential.provider == provider,
            ProviderCredential.key_name == key_name,
        )
    )
    encrypted_value = encrypt_value(value)
    if existing:
        existing.encrypted_value = encrypted_value
        existing.encryption_key_id = active_encryption_key_id()
    else:
        db.add(
            ProviderCredential(
                organization_id=organization_id,
                provider=provider,
                key_name=key_name,
                encrypted_value=encrypted_value,
                encryption_key_id=active_encryption_key_id(),
            )
        )


def _save_etsy_connection_values(
    db: Session,
    *,
    organization_id: str,
    credential_key: str,
    refresh_token: str,
    seller_user_id: str,
    scopes: list[str],
    shops: list[dict[str, Any]],
    last_synced_at: datetime,
) -> None:
    _upsert_secret_provider_credential(
        db,
        organization_id=organization_id,
        provider=ETSY_CONNECTION_PROVIDER,
        key_name=_compose_provider_credential_row_key(credential_key, ETSY_REFRESH_TOKEN_KEY),
        value=refresh_token,
    )
    _upsert_secret_provider_credential(
        db,
        organization_id=organization_id,
        provider=ETSY_CONNECTION_PROVIDER,
        key_name=_compose_provider_credential_row_key(credential_key, ETSY_SELLER_USER_ID_KEY),
        value=seller_user_id,
    )
    _upsert_secret_provider_credential(
        db,
        organization_id=organization_id,
        provider=ETSY_CONNECTION_PROVIDER,
        key_name=_compose_provider_credential_row_key(credential_key, ETSY_SCOPES_KEY),
        value=json.dumps(scopes, separators=(",", ":")),
    )
    _upsert_secret_provider_credential(
        db,
        organization_id=organization_id,
        provider=ETSY_CONNECTION_PROVIDER,
        key_name=_compose_provider_credential_row_key(credential_key, ETSY_SHOPS_KEY),
        value=json.dumps(shops, separators=(",", ":")),
    )
    _upsert_secret_provider_credential(
        db,
        organization_id=organization_id,
        provider=ETSY_CONNECTION_PROVIDER,
        key_name=_compose_provider_credential_row_key(credential_key, ETSY_LAST_SYNC_AT_KEY),
        value=last_synced_at.isoformat(),
    )


def _split_store_label_for_matching(label: str | None) -> str | None:
    normalized = str(label or "").strip()
    if not normalized:
        return None
    return normalized.split("->", 1)[0].strip() or normalized


def _normalize_store_name(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return None
    collapsed = re.sub(r"[^a-z0-9]+", " ", normalized)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()
    return collapsed or None


def _store_connection_identity(
    *,
    provider: str,
    credential_key: str,
    provider_store_id: str,
) -> tuple[str, str, str]:
    return (provider, credential_key, provider_store_id)


def _manual_etsy_seed_identities(
    grouped_credentials: Mapping[str, dict[str, Any]],
) -> set[tuple[str, str, str]]:
    identities: set[tuple[str, str, str]] = set()
    for credential_key, values in grouped_credentials.items():
        for raw_seed in values.get("manual_store_seeds") or []:
            if not isinstance(raw_seed, dict):
                continue
            if str(raw_seed.get("storefront_type") or "").strip() != "etsy":
                continue
            provider_store_id = _normalize_optional_string(raw_seed.get("provider_store_id"))
            if not provider_store_id:
                continue
            identities.add(
                _store_connection_identity(
                    provider="gelato",
                    credential_key=credential_key,
                    provider_store_id=provider_store_id,
                )
            )
    return identities


def _projected_etsy_store_slot_count(
    db: Session,
    *,
    organization_id: str,
    manual_seed_overrides: Mapping[str, list[dict[str, Any]]] | None = None,
) -> int:
    actual_etsy_identities = {
        _store_connection_identity(
            provider=connection.provider,
            credential_key=connection.credential_key,
            provider_store_id=connection.provider_store_id,
        )
        for connection in db.scalars(
            select(ProviderStoreConnection).where(
                ProviderStoreConnection.organization_id == organization_id,
                ProviderStoreConnection.storefront_type == "etsy",
                ProviderStoreConnection.deleted_at.is_(None),
            )
        ).all()
    }
    grouped_credentials = _group_provider_credentials(_list_credential_rows(db, organization_id, "gelato"))
    if manual_seed_overrides:
        for credential_key, seeds_payload in manual_seed_overrides.items():
            values = dict(grouped_credentials.get(credential_key, {}))
            values["manual_store_seeds"] = seeds_payload
            grouped_credentials[credential_key] = values
    return len(actual_etsy_identities | _manual_etsy_seed_identities(grouped_credentials))


def _projected_etsy_store_connection_count_for_sync(
    db: Session,
    *,
    organization_id: str,
    provider: str,
    remote_connections_by_credential: Mapping[str, list[Any]],
) -> tuple[int, int]:
    rows = db.scalars(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.organization_id == organization_id,
            ProviderStoreConnection.deleted_at.is_(None),
        )
    ).all()
    projected_storefront_types = {
        _store_connection_identity(
            provider=row.provider,
            credential_key=row.credential_key,
            provider_store_id=row.provider_store_id,
        ): row.storefront_type
        for row in rows
    }
    for credential_key, remote_connections in remote_connections_by_credential.items():
        for remote in remote_connections:
            projected_storefront_types[
                _store_connection_identity(
                    provider=provider,
                    credential_key=credential_key,
                    provider_store_id=remote.provider_store_id,
                )
            ] = remote.storefront_type

    current_count = sum(1 for row in rows if row.storefront_type == "etsy")
    projected_count = sum(
        1 for storefront_type in projected_storefront_types.values() if storefront_type == "etsy"
    )
    return current_count, projected_count


def _ensure_etsy_store_limit(
    *,
    current_count: int,
    projected_count: int,
    action: str,
) -> None:
    if projected_count <= MAX_ETSY_STORE_CONNECTIONS or projected_count <= current_count:
        return

    raise HTTPException(
        status_code=409,
        detail=(
            f"Velora currently supports up to {MAX_ETSY_STORE_CONNECTIONS} Etsy stores per organization. "
            f"Remove an existing Etsy storefront row before {action}."
        ),
    )


def _validate_unique_gelato_manual_etsy_store_names(
    db: Session,
    *,
    organization_id: str,
    credential_key: str,
    seeds_payload: list[dict[str, Any]],
) -> None:
    incoming_names: dict[str, dict[str, str]] = {}
    for seed in seeds_payload:
        storefront_type = str(seed.get("storefront_type") or "").strip()
        if storefront_type != "etsy":
            continue

        provider_store_id = str(seed.get("provider_store_id") or "").strip()
        label = str(seed.get("label") or "").strip()
        if not label:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Each manual Gelato Etsy store needs a unique store name. "
                    f"Add a store name for '{provider_store_id or 'this store'}' before saving."
                ),
            )

        normalized_label = _normalize_store_name(label)
        if not normalized_label:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Each manual Gelato Etsy store needs a unique store name. "
                    f"The name for '{provider_store_id or 'this store'}' could not be normalized."
                ),
            )

        existing_incoming = incoming_names.get(normalized_label)
        if existing_incoming and existing_incoming["provider_store_id"] != provider_store_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Manual Gelato Etsy store names must be unique. "
                    f"'{label}' conflicts with '{existing_incoming['label']}'."
                ),
            )

        incoming_names[normalized_label] = {
            "label": label,
            "provider_store_id": provider_store_id,
        }

    if not incoming_names:
        return

    grouped_credentials = _group_provider_credentials(
        _list_credential_rows(db, organization_id, "gelato")
    )
    for other_credential_key, values in grouped_credentials.items():
        for raw_seed in values.get("manual_store_seeds") or []:
            if not isinstance(raw_seed, dict):
                continue
            if str(raw_seed.get("storefront_type") or "").strip() != "etsy":
                continue

            other_provider_store_id = str(raw_seed.get("provider_store_id") or "").strip()
            other_label = str(raw_seed.get("label") or "").strip()
            normalized_other_label = _normalize_store_name(other_label)
            if not normalized_other_label or normalized_other_label not in incoming_names:
                continue

            same_logical_seed = (
                other_credential_key == credential_key
                and other_provider_store_id == incoming_names[normalized_other_label]["provider_store_id"]
            )
            if same_logical_seed:
                continue

            raise HTTPException(
                status_code=409,
                detail=(
                    "Manual Gelato Etsy store names must be unique. "
                    f"'{incoming_names[normalized_other_label]['label']}' is already used by another saved Gelato Etsy store."
                ),
            )

    existing_connections = db.scalars(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.organization_id == organization_id,
            ProviderStoreConnection.storefront_type == "etsy",
            ProviderStoreConnection.deleted_at.is_(None),
        )
    ).all()
    for connection in existing_connections:
        candidate_names = _extract_candidate_store_names(connection)
        if not candidate_names:
            continue

        for normalized_label, incoming in incoming_names.items():
            if normalized_label not in candidate_names:
                continue

            same_logical_connection = (
                connection.provider == "gelato"
                and connection.credential_key == credential_key
                and connection.provider_store_id == incoming["provider_store_id"]
            )
            if same_logical_connection:
                continue
            if connection.provider != "gelato":
                continue

            raise HTTPException(
                status_code=409,
                detail=(
                    "Manual Gelato Etsy store names must be unique. "
                    f"'{incoming['label']}' matches the existing Etsy storefront '{connection.label}'."
                ),
            )


def _extract_candidate_store_names(connection: ProviderStoreConnection) -> set[str]:
    candidates: list[Any] = [_split_store_label_for_matching(connection.label)]

    return {
        normalized
        for normalized in (_normalize_store_name(candidate) for candidate in candidates)
        if normalized
    }


def _auto_map_etsy_shop_ids(
    db: Session,
    *,
    actor: ActorContext,
    shops: list[dict[str, Any]],
) -> None:
    connections = db.scalars(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.organization_id == actor.organization_id,
            ProviderStoreConnection.storefront_type == "etsy",
            ProviderStoreConnection.deleted_at.is_(None),
        )
    ).all()
    if not connections:
        return

    missing_name_index: dict[str, list[ProviderStoreConnection]] = {}
    for connection in connections:
        if connection.etsy_shop_id:
            continue
        for candidate_name in _extract_candidate_store_names(connection):
            missing_name_index.setdefault(candidate_name, []).append(connection)

    for shop in shops:
        shop_id = _normalize_optional_string(shop.get("shop_id"))
        if not shop_id:
            continue

        normalized_shop_name = _normalize_store_name(shop.get("shop_name"))
        if not normalized_shop_name:
            continue
        matches = missing_name_index.get(normalized_shop_name) or []
        for matched_connection in matches:
            if matched_connection.etsy_shop_id:
                continue
            matched_connection.etsy_shop_id = shop_id


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_epoch_datetime(value: Any) -> datetime | None:
    timestamp = _parse_optional_float(value)
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _normalize_etsy_shop_summaries(raw_shops: list[Any]) -> list[dict[str, str | None]]:
    shops: list[dict[str, str | None]] = []
    for raw_shop in raw_shops:
        if not isinstance(raw_shop, Mapping):
            continue
        shop_id = _normalize_optional_string(raw_shop.get("shop_id"))
        shop_name = _normalize_optional_string(raw_shop.get("shop_name"))
        if not shop_id or not shop_name:
            continue
        shops.append(
            {
                "shop_id": shop_id,
                "shop_name": shop_name,
                "shop_url": _normalize_optional_string(raw_shop.get("shop_url")),
            }
        )
    shops.sort(key=lambda shop: ((shop.get("shop_name") or "").casefold(), shop.get("shop_id") or ""))
    return shops


def _build_etsy_connection_status(
    db: Session,
    *,
    actor: ActorContext,
    values_by_key: Mapping[str, dict[str, Any]],
) -> EtsyConnectionStatus:
    connections = db.scalars(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.organization_id == actor.organization_id,
            ProviderStoreConnection.storefront_type == "etsy",
            ProviderStoreConnection.deleted_at.is_(None),
        )
    ).all()
    discovered_shop_ids: set[str] = set()
    shop_id_matches: dict[str, list[ProviderStoreConnection]] = {}
    for connection in connections:
        shop_id = str(connection.etsy_shop_id or "").strip()
        if not shop_id:
            continue
        shop_id_matches.setdefault(shop_id, []).append(connection)

    connected_accounts: list[EtsyConnectedAccountSummary] = []
    normalized_shops_by_id: dict[str, dict[str, str | None]] = {}
    scopes_union: list[str] = []
    seen_scopes: set[str] = set()
    latest_synced_at: datetime | None = None
    primary_seller_user_id: str | None = None

    for credential_key, values in values_by_key.items():
        account_scopes = [
            str(item).strip()
            for item in values.get("scopes", [])
            if str(item).strip()
        ]
        for scope in account_scopes:
            if scope not in seen_scopes:
                seen_scopes.add(scope)
                scopes_union.append(scope)

        normalized_account_shops = _normalize_etsy_shop_summaries(
            values.get("shops") if isinstance(values.get("shops"), list) else []
        )
        for shop in normalized_account_shops:
            shop_id = shop.get("shop_id")
            if isinstance(shop_id, str) and shop_id and shop_id not in normalized_shops_by_id:
                normalized_shops_by_id[shop_id] = shop

        last_synced_at = _parse_optional_datetime(values.get("last_synced_at"))
        if last_synced_at and (latest_synced_at is None or last_synced_at > latest_synced_at):
            latest_synced_at = last_synced_at

        seller_user_id = _normalize_optional_string(values.get("seller_user_id")) or credential_key
        if primary_seller_user_id is None:
            primary_seller_user_id = seller_user_id

        primary_shop = normalized_account_shops[0] if normalized_account_shops else {}
        connected_accounts.append(
            EtsyConnectedAccountSummary(
                credential_key=credential_key,
                seller_user_id=seller_user_id,
                shop_id=_normalize_optional_string(primary_shop.get("shop_id")),
                shop_name=_normalize_optional_string(primary_shop.get("shop_name")),
                shop_url=_normalize_optional_string(primary_shop.get("shop_url")),
                last_synced_at=last_synced_at,
                scopes=account_scopes,
            )
        )

    connected_accounts.sort(
        key=lambda account: (
            (account.shop_name or "").casefold(),
            account.shop_id or "",
            account.seller_user_id,
        )
    )

    connected_shops: list[EtsyShopSummary] = []
    discovered_shop_ids: set[str] = set()
    for shop_id, shop in normalized_shops_by_id.items():
        shop_name = _normalize_optional_string(shop.get("shop_name"))
        if not shop_name:
            continue
        discovered_shop_ids.add(shop_id)
        matched_connections = sorted(
            shop_id_matches.get(shop_id) or [],
            key=lambda connection: (connection.label.casefold(), connection.id),
        )
        primary_match = matched_connections[0] if matched_connections else None
        connected_shops.append(
            EtsyShopSummary(
                shop_id=shop_id,
                shop_name=shop_name,
                shop_url=_normalize_optional_string(shop.get("shop_url")),
                matched_connection_id=primary_match.id if primary_match else None,
                matched_connection_label=primary_match.label if primary_match else None,
                matched_connection_ids=[connection.id for connection in matched_connections],
                matched_connection_labels=[connection.label for connection in matched_connections],
            )
        )
    connected_shops.sort(key=lambda shop: (shop.shop_name.casefold(), shop.shop_id))

    return EtsyConnectionStatus(
        is_connected=any(
            bool(_normalize_optional_string(values.get("refresh_token")))
            for values in values_by_key.values()
        ),
        seller_user_id=primary_seller_user_id,
        last_synced_at=latest_synced_at,
        scopes=scopes_union,
        connected_account_count=len(connected_accounts),
        connected_accounts=connected_accounts,
        connected_shops=connected_shops,
        matched_connection_count=sum(
            1
            for connection in connections
            if connection.etsy_shop_id and connection.etsy_shop_id in discovered_shop_ids
        ),
        unmapped_connection_count=sum(
            1
            for connection in connections
            if not connection.etsy_shop_id or connection.etsy_shop_id not in discovered_shop_ids
        ),
    )


def _list_credential_rows(db: Session, organization_id: str, provider: str) -> list[ProviderCredential]:
    return list(
        db.scalars(
            select(ProviderCredential)
            .where(
                ProviderCredential.organization_id == organization_id,
                ProviderCredential.provider == provider,
            )
            .order_by(ProviderCredential.key_name.asc())
        )
    )


def _mask_credential_value(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return f"{normalized[:3]}..."


def _normalize_optional_string(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _resolve_remote_etsy_shop_id(*, etsy_shop_id: str | None) -> str | None:
    return _normalize_optional_string(etsy_shop_id)


def _compose_provider_credential_row_key(credential_key: str, key_name: str) -> str:
    if credential_key == DEFAULT_CREDENTIAL_KEY:
        return key_name
    return f"{credential_key}{CREDENTIAL_KEY_SEPARATOR}{key_name}"


def _split_provider_credential_row_key(key_name: str) -> tuple[str, str]:
    if CREDENTIAL_KEY_SEPARATOR not in key_name:
        return DEFAULT_CREDENTIAL_KEY, key_name
    credential_key, nested_key = key_name.split(CREDENTIAL_KEY_SEPARATOR, 1)
    return credential_key, nested_key


def _group_provider_credentials(rows: list[ProviderCredential]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        credential_key, nested_key = _split_provider_credential_row_key(row.key_name)
        credential_payload = grouped.setdefault(credential_key, {})
        decrypted = decrypt_value(row.encrypted_value, key_id=row.encryption_key_id)
        if nested_key == MANUAL_STORE_SEEDS_KEY:
            credential_payload["manual_store_seeds"] = _deserialize_manual_store_seeds(decrypted)
        else:
            credential_payload[nested_key] = decrypted
    return grouped


def _build_provider_credential_entry(
    *,
    provider: str,
    credential_key: str,
    values: dict[str, Any],
) -> ProviderCredentialEntry:
    required_keys = get_required_provider_keys(provider)
    configured_keys = sorted([key for key in required_keys if str(values.get(key) or "").strip()])
    missing_keys = [key for key in required_keys if not str(values.get(key) or "").strip()]
    manual_store_seeds = [
        ManualStoreSeed.model_validate(seed)
        for seed in (values.get("manual_store_seeds") or [])
        if isinstance(seed, dict)
    ]
    primary_credential_key = next((key for key in required_keys if key in configured_keys), None)
    return ProviderCredentialEntry(
        credential_key=credential_key,
        credential_display_name=str(values.get(CREDENTIAL_DISPLAY_NAME_KEY) or "").strip() or None,
        credential_masked_value=_mask_credential_value(values.get(primary_credential_key) if primary_credential_key else None),
        configured_keys=configured_keys,
        missing_keys=missing_keys,
        manual_store_seed_count=len(manual_store_seeds),
        manual_store_seeds=manual_store_seeds,
    )


def get_provider_credentials(
    db: Session,
    *,
    organization_id: str,
    provider: str,
    credential_key: str | None = None,
) -> dict[str, Any]:
    rows = _list_credential_rows(db, organization_id, provider)
    grouped = _group_provider_credentials(rows)
    if credential_key is None:
        if len(grouped) == 1:
            return dict(next(iter(grouped.values())))
        return dict(grouped.get(DEFAULT_CREDENTIAL_KEY, {}))
    return dict(grouped.get(credential_key, {}))


def get_required_provider_keys(provider: str) -> list[str]:
    return list(_provider_metadata(provider)["required_keys"])


def _ensure_etsy_connected_for_provider_setup(
    db: Session,
    *,
    organization_id: str,
    provider: str,
) -> None:
    if provider not in PROVIDER_METADATA:
        return

    if any(
        _normalize_optional_string(values.get("refresh_token"))
        for values in _list_etsy_connection_values(db, organization_id=organization_id).values()
    ):
        return

    raise HTTPException(
        status_code=409,
        detail=(
            "Connect Etsy first before authorizing Printify or Gelato or refreshing provider stores."
        ),
    )


def _ensure_provider_credentials_complete(provider: str, credentials: dict[str, Any]) -> None:
    missing_keys = [key for key in get_required_provider_keys(provider) if not str(credentials.get(key) or "").strip()]
    if missing_keys:
        raise HTTPException(status_code=400, detail=f"Credentials for '{provider}' are incomplete.")


def _extract_upstream_status_code(detail: str) -> int | None:
    for pattern in (r"status(?:_code)?=(\d{3})\b", r":\s*(\d{3})(?:\b|\s)"):
        match = re.search(pattern, detail)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _raise_provider_action_error(
    *,
    provider: str,
    action: str,
    exc: Exception,
) -> None:
    if isinstance(exc, HTTPException):
        raise exc

    provider_name = str(_provider_metadata(provider)["name"])
    detail = str(exc).strip() or f"{provider_name} failed while {action}."
    normalized = detail.casefold()
    upstream_status = _extract_upstream_status_code(detail)

    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=detail) from exc

    if "missing " in normalized and "credential" in normalized:
        raise HTTPException(
            status_code=409,
            detail=f"{provider_name} credentials are incomplete. Update them in Settings and try again.",
        ) from exc

    if "store binding" in normalized:
        raise HTTPException(
            status_code=409,
            detail=f"{provider_name} store connection is incomplete. Refresh the connected store in Settings and try again.",
        ) from exc

    if upstream_status in {401, 403}:
        raise HTTPException(
            status_code=409,
            detail=f"{provider_name} rejected the saved credentials while {action}. Reconnect {provider_name} in Settings and try again.",
        ) from exc

    if ("gelato template" in normalized or "failed to fetch gelato template" in normalized) and (
        upstream_status == 404 or "not found" in normalized
    ):
        raise HTTPException(
            status_code=422,
            detail="Gelato template id was not found. Enter a real Gelato template id and try again.",
        ) from exc

    if ("printify product" in normalized or "failed to fetch printify product" in normalized) and (
        upstream_status == 404 or "not found" in normalized
    ):
        raise HTTPException(
            status_code=422,
            detail="Printify product reference was not found. Enter a real Printify product URL or product id and try again.",
        ) from exc

    if upstream_status == 404:
        if provider == "gelato" and "template" in normalized:
            raise HTTPException(
                status_code=422,
                detail="Gelato template id was not found. Enter a real Gelato template id and try again.",
            ) from exc
        if provider == "printify" and "product" in normalized:
            raise HTTPException(
                status_code=422,
                detail="Printify product reference was not found. Enter a real Printify product URL or product id and try again.",
            ) from exc

    if upstream_status == 429:
        raise HTTPException(
            status_code=503,
            detail=f"{provider_name} is rate limiting requests right now. Try again in a moment.",
        ) from exc

    if "design placeholder" in normalized:
        raise HTTPException(
            status_code=422,
            detail=(
                "This Gelato template does not contain the configured design placeholder name. "
                "Update the placeholder field or choose a different template."
            ),
        ) from exc

    if any(
        token in normalized
        for token in (
            "no enabled variants",
            "no variants",
            "no print areas",
            "missing blueprint_id or print_provider_id",
        )
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{provider_name} could not use that source product. "
                f"Choose a different source product or fix it in {provider_name} first."
            ),
        ) from exc

    if upstream_status is not None and 400 <= upstream_status < 500:
        raise HTTPException(
            status_code=422,
            detail=f"{provider_name} rejected this request while {action}. Check the reference or store setup and try again.",
        ) from exc

    raise HTTPException(
        status_code=502,
        detail=f"{provider_name} failed while {action}. Try again in a moment.",
    ) from exc


def get_provider_credential_status(
    db: Session,
    *,
    organization_id: str,
    provider: str,
) -> ProviderCredentialStatus:
    metadata = _provider_metadata(provider)
    grouped = _group_provider_credentials(_list_credential_rows(db, organization_id, provider))
    credential_entries = [
        _build_provider_credential_entry(provider=provider, credential_key=credential_key, values=values)
        for credential_key, values in grouped.items()
    ]
    credential_entries.sort(key=lambda item: ((item.credential_display_name or "").lower(), item.credential_key))
    return ProviderCredentialStatus(
        provider=provider,  # type: ignore[arg-type]
        is_configured=any(not item.missing_keys for item in credential_entries),
        required_keys=metadata["required_keys"],
        credential_count=len(credential_entries),
        credentials=credential_entries,
    )


def upsert_provider_credentials(
    db: Session,
    *,
    actor: ActorContext,
    provider: str,
    payload: ProviderCredentialsUpsertRequest,
) -> ProviderCredentialStatus:
    _provider_metadata(provider)
    _ensure_etsy_connected_for_provider_setup(
        db,
        organization_id=actor.organization_id,
        provider=provider,
    )
    credential_key = payload.credential_key or uuid.uuid4().hex[:12]
    fields_set = payload.model_fields_set
    for key_name, value in payload.credentials.items():
        if not str(value or "").strip():
            continue
        row_key = _compose_provider_credential_row_key(credential_key, key_name)
        existing = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.organization_id == actor.organization_id,
                ProviderCredential.provider == provider,
                ProviderCredential.key_name == row_key,
            )
        )
        encrypted_value = encrypt_value(value)
        if existing:
            existing.encrypted_value = encrypted_value
            existing.encryption_key_id = active_encryption_key_id()
        else:
            db.add(
                ProviderCredential(
                    organization_id=actor.organization_id,
                    provider=provider,
                    key_name=row_key,
                    encrypted_value=encrypted_value,
                    encryption_key_id=active_encryption_key_id(),
                )
            )
    credential_display_name = None
    if "credential_display_name" in fields_set:
        display_name_value = (payload.credential_display_name or "").strip()
        display_name_row_key = _compose_provider_credential_row_key(credential_key, CREDENTIAL_DISPLAY_NAME_KEY)
        existing_display_name_row = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.organization_id == actor.organization_id,
                ProviderCredential.provider == provider,
                ProviderCredential.key_name == display_name_row_key,
            )
        )
        if display_name_value:
            credential_display_name = display_name_value
            encrypted_value = encrypt_value(display_name_value)
            if existing_display_name_row:
                existing_display_name_row.encrypted_value = encrypted_value
                existing_display_name_row.encryption_key_id = active_encryption_key_id()
            else:
                db.add(
                    ProviderCredential(
                        organization_id=actor.organization_id,
                        provider=provider,
                        key_name=display_name_row_key,
                        encrypted_value=encrypted_value,
                        encryption_key_id=active_encryption_key_id(),
                    )
                )
        elif existing_display_name_row:
            db.delete(existing_display_name_row)
    manual_store_seed_count = None
    if "manual_store_seeds" in fields_set:
        seeds_payload = [seed.model_dump() for seed in payload.manual_store_seeds]
        if provider == "gelato":
            _validate_unique_gelato_manual_etsy_store_names(
                db,
                organization_id=actor.organization_id,
                credential_key=credential_key,
                seeds_payload=seeds_payload,
            )
            current_projected_etsy_count = _projected_etsy_store_slot_count(
                db,
                organization_id=actor.organization_id,
            )
            projected_etsy_count = _projected_etsy_store_slot_count(
                db,
                organization_id=actor.organization_id,
                manual_seed_overrides={credential_key: seeds_payload},
            )
            _ensure_etsy_store_limit(
                current_count=current_projected_etsy_count,
                projected_count=projected_etsy_count,
                action="saving another Etsy store",
            )
        manual_store_seed_count = len(seeds_payload)
        seeds_json = _serialize_manual_store_seeds(seeds_payload)
        seeds_row_key = _compose_provider_credential_row_key(credential_key, MANUAL_STORE_SEEDS_KEY)
        existing_seed_row = db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.organization_id == actor.organization_id,
                ProviderCredential.provider == provider,
                ProviderCredential.key_name == seeds_row_key,
            )
        )
        if existing_seed_row:
            existing_seed_row.encrypted_value = encrypt_value(seeds_json)
            existing_seed_row.encryption_key_id = active_encryption_key_id()
        else:
            db.add(
                ProviderCredential(
                    organization_id=actor.organization_id,
                    provider=provider,
                    key_name=seeds_row_key,
                    encrypted_value=encrypt_value(seeds_json),
                    encryption_key_id=active_encryption_key_id(),
                )
            )
    db.commit()
    log_event(
        commerce_logger,
        "provider.credentials.upserted",
        verbose_only=True,
        organization_id=actor.organization_id,
        provider=provider,
        credential_key=credential_key,
        credential_display_name=credential_display_name,
        configured_key_count=len([key for key, value in payload.credentials.items() if str(value or "").strip()]),
        manual_store_seed_count=manual_store_seed_count,
    )
    return get_provider_credential_status(db, organization_id=actor.organization_id, provider=provider)


def delete_provider_credentials(
    db: Session,
    *,
    actor: ActorContext,
    provider: str,
    credential_key: str,
) -> ProviderCredentialStatus:
    _provider_metadata(provider)
    rows = [
        row
        for row in _list_credential_rows(db, actor.organization_id, provider)
        if _split_provider_credential_row_key(row.key_name)[0] == credential_key
    ]
    if not rows:
        raise HTTPException(status_code=404, detail="Provider credential not found.")
    scoped_connections = db.scalars(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.organization_id == actor.organization_id,
            ProviderStoreConnection.provider == provider,
            ProviderStoreConnection.credential_key == credential_key,
        )
    ).all()
    for connection in scoped_connections:
        has_blueprints = db.scalar(
            select(func.count(ProductBlueprint.id)).where(ProductBlueprint.provider_store_connection_id == connection.id)
        ) or 0
        has_drafts = db.scalar(
            select(func.count(ProviderProductDraft.id)).where(ProviderProductDraft.provider_store_connection_id == connection.id)
        ) or 0
        has_pod_products = db.scalar(
            select(func.count(PodProduct.id)).where(PodProduct.provider_store_connection_id == connection.id)
        ) or 0
        if has_blueprints or has_drafts or has_pod_products:
            raise HTTPException(
                status_code=409,
                detail="Provider credential is still referenced by synced storefronts used in blueprints, drafts, or provider products.",
            )
    for connection in scoped_connections:
        has_orders = db.scalar(
            select(func.count(Order.id)).where(Order.provider_store_connection_id == connection.id)
        ) or 0
        has_sync_events = db.scalar(
            select(func.count(SyncEvent.id)).where(SyncEvent.provider_store_connection_id == connection.id)
        ) or 0
        if has_orders or has_sync_events:
            connection.status = "disconnected"
            connection.deleted_at = connection.deleted_at or utc_now()
            connection.order_sync_cursor_json = None
        else:
            db.delete(connection)
    rows = _list_credential_rows(db, actor.organization_id, provider)
    for row in rows:
        if _split_provider_credential_row_key(row.key_name)[0] != credential_key:
            continue
        db.delete(row)
    db.commit()
    log_event(
        commerce_logger,
        "provider.credentials.deleted",
        verbose_only=True,
        organization_id=actor.organization_id,
        provider=provider,
        credential_key=credential_key,
        deleted_connection_count=len(scoped_connections),
    )
    return get_provider_credential_status(db, organization_id=actor.organization_id, provider=provider)


def list_pod_providers(db: Session, *, actor: ActorContext) -> list[PodProvider]:
    providers: list[PodProvider] = []
    for provider, metadata in PROVIDER_METADATA.items():
        store_count = db.scalar(
            select(func.count(ProviderStoreConnection.id)).where(
                ProviderStoreConnection.organization_id == actor.organization_id,
                ProviderStoreConnection.provider == provider,
                ProviderStoreConnection.deleted_at.is_(None),
            )
        ) or 0
        last_sync_at = db.scalar(
            select(func.max(ProviderStoreConnection.last_synced_at)).where(
                ProviderStoreConnection.organization_id == actor.organization_id,
                ProviderStoreConnection.provider == provider,
                ProviderStoreConnection.deleted_at.is_(None),
            )
        )
        status = get_provider_credential_status(db, organization_id=actor.organization_id, provider=provider)
        providers.append(
            PodProvider(
                id=provider,  # type: ignore[arg-type]
                name=metadata["name"],
                status="connected" if status.is_configured else "needs_credentials",
                connected_stores=int(store_count),
                credentials_configured=status.is_configured,
                required_keys=metadata["required_keys"],
                available_storefronts=metadata["available_storefronts"],
                last_sync_at=last_sync_at,
            )
        )
    return providers


def list_provider_store_connections(db: Session, *, actor: ActorContext) -> list[ProviderStoreConnectionSchema]:
    rows = db.scalars(
        select(ProviderStoreConnection)
        .where(
            ProviderStoreConnection.organization_id == actor.organization_id,
            ProviderStoreConnection.deleted_at.is_(None),
        )
        .order_by(
            ProviderStoreConnection.provider.asc(),
            ProviderStoreConnection.credential_key.asc(),
            ProviderStoreConnection.label.asc(),
        )
    ).all()
    return [to_provider_store_connection(row) for row in rows]


def get_etsy_connection_status(
    db: Session,
    *,
    actor: ActorContext,
) -> EtsyConnectionStatus:
    values_by_key = _list_etsy_connection_values(db, organization_id=actor.organization_id)
    return _build_etsy_connection_status(db, actor=actor, values_by_key=values_by_key)


def start_etsy_oauth_connection(
    db: Session,
    *,
    actor: ActorContext,
    expected_seller_user_id: str | None = None,
) -> EtsyOAuthStartResponse:
    payload = build_etsy_oauth_authorization(
        actor_id=actor.actor_id,
        organization_id=actor.organization_id,
        expected_seller_user_id=expected_seller_user_id,
    )
    register_etsy_oauth_state_request(
        db,
        actor_id=actor.actor_id,
        organization_id=actor.organization_id,
        state=str(payload["state"]),
        expires_at=payload["expires_at"],
    )
    return EtsyOAuthStartResponse(**payload)


def complete_etsy_oauth_connection(
    db: Session,
    *,
    actor: ActorContext,
    code: str,
    state: str,
) -> EtsyConnectionStatus:
    oauth_result = exchange_etsy_authorization_code(
        db=db,
        code=code,
        state=state,
        actor_id=actor.actor_id,
        organization_id=actor.organization_id,
    )
    synced_at = utc_now()
    shops = [
        {
            "shop_id": _normalize_optional_string(shop.get("shop_id")),
            "shop_name": _normalize_optional_string(shop.get("shop_name")),
            "shop_url": _normalize_optional_string(shop.get("shop_url")),
        }
        for shop in oauth_result.get("shops", [])
        if isinstance(shop, Mapping) and _normalize_optional_string(shop.get("shop_id"))
    ]
    seller_user_id = str(oauth_result["seller_user_id"])
    _save_etsy_connection_values(
        db,
        organization_id=actor.organization_id,
        credential_key=seller_user_id,
        refresh_token=str(oauth_result["refresh_token"]),
        seller_user_id=seller_user_id,
        scopes=[
            str(item).strip()
            for item in oauth_result.get("scopes", get_etsy_oauth_scopes())
            if str(item).strip()
        ],
        shops=shops,
        last_synced_at=synced_at,
    )
    _auto_map_etsy_shop_ids(db, actor=actor, shops=shops)
    db.commit()
    status_payload = _build_etsy_connection_status(
        db,
        actor=actor,
        values_by_key=_list_etsy_connection_values(db, organization_id=actor.organization_id),
    )
    log_event(
        commerce_logger,
        "etsy.oauth.connected",
        verbose_only=True,
        organization_id=actor.organization_id,
        seller_user_id=status_payload.seller_user_id,
        account_count=status_payload.connected_account_count,
        shop_count=len(status_payload.connected_shops),
        matched_connection_count=status_payload.matched_connection_count,
    )
    return status_payload


def sync_etsy_connection_shops(
    db: Session,
    *,
    actor: ActorContext,
) -> EtsyConnectionStatus:
    values_by_key = _list_etsy_connection_values(db, organization_id=actor.organization_id)
    if not values_by_key:
        raise HTTPException(
            status_code=409,
            detail="Connect Etsy first before refreshing shop discovery.",
        )
    synced_at = utc_now()
    aggregated_shops: list[dict[str, Any]] = []
    for credential_key, values in values_by_key.items():
        refresh_token = _normalize_optional_string(values.get("refresh_token"))
        if not refresh_token:
            continue

        access_token = _refresh_access_token(refresh_token)
        seller_user_id = _normalize_optional_string(values.get("seller_user_id")) or ""
        if not seller_user_id:
            seller_user_id = str(values.get("seller_user_id") or "").strip()
        if not seller_user_id:
            raise HTTPException(
                status_code=409,
                detail="Connected Etsy account is missing a seller user id. Reconnect Etsy from Settings.",
            )

        shops = fetch_etsy_shops(access_token=access_token, user_id=seller_user_id)
        aggregated_shops.extend(shops)
        next_refresh_token = get_cached_etsy_refresh_token(refresh_token) or refresh_token
        _save_etsy_connection_values(
            db,
            organization_id=actor.organization_id,
            credential_key=credential_key,
            refresh_token=next_refresh_token,
            seller_user_id=seller_user_id,
            scopes=[
                str(item).strip()
                for item in values.get("scopes", get_etsy_oauth_scopes())
                if str(item).strip()
            ],
            shops=shops,
            last_synced_at=synced_at,
        )
    _auto_map_etsy_shop_ids(db, actor=actor, shops=aggregated_shops)
    db.commit()
    status_payload = _build_etsy_connection_status(
        db,
        actor=actor,
        values_by_key=_list_etsy_connection_values(db, organization_id=actor.organization_id),
    )
    log_event(
        commerce_logger,
        "etsy.shops.synced",
        verbose_only=True,
        organization_id=actor.organization_id,
        seller_user_id=status_payload.seller_user_id,
        account_count=status_payload.connected_account_count,
        shop_count=len(status_payload.connected_shops),
        matched_connection_count=status_payload.matched_connection_count,
    )
    return status_payload


def _get_etsy_refresh_token_for_shop(
    db: Session,
    *,
    organization_id: str,
    etsy_shop_id: str | None,
) -> str | None:
    target_shop_id = _resolve_remote_etsy_shop_id(etsy_shop_id=etsy_shop_id)
    values_by_key = _list_etsy_connection_values(db, organization_id=organization_id)
    if target_shop_id:
        for values in values_by_key.values():
            raw_shops = values.get("shops") if isinstance(values.get("shops"), list) else []
            for shop in raw_shops:
                if not isinstance(shop, Mapping):
                    continue
                if _normalize_optional_string(shop.get("shop_id")) == target_shop_id:
                    matched_refresh_token = _normalize_optional_string(values.get("refresh_token"))
                    if matched_refresh_token:
                        return matched_refresh_token

    for values in values_by_key.values():
        fallback_refresh_token = _normalize_optional_string(values.get("refresh_token"))
        if fallback_refresh_token:
            return fallback_refresh_token
    return None


def update_provider_store_connection(
    db: Session,
    *,
    actor: ActorContext,
    connection_id: str,
    payload: ProviderStoreConnectionUpdateRequest,
) -> ProviderStoreConnectionSchema:
    row = _get_store_connection_or_404(db, actor=actor, connection_id=connection_id)
    fields_set = payload.model_fields_set

    if "etsy_shop_id" in fields_set:
        next_etsy_shop_id = _normalize_optional_string(payload.etsy_shop_id)
        if next_etsy_shop_id and row.storefront_type != "etsy":
            raise HTTPException(
                status_code=400,
                detail="Only Etsy store connections can store an Etsy shop id.",
            )
        row.etsy_shop_id = next_etsy_shop_id

    db.commit()
    db.refresh(row)
    return to_provider_store_connection(row)


def _build_scoped_provider_credentials(
    db: Session,
    *,
    organization_id: str,
    provider: str,
    store_connection: ProviderStoreConnection | None = None,
    credential_key: str | None = None,
) -> dict[str, Any]:
    scoped_credential_key = credential_key or (store_connection.credential_key if store_connection else None)
    credentials = get_provider_credentials(
        db,
        organization_id=organization_id,
        provider=provider,
        credential_key=scoped_credential_key,
    )
    if store_connection:
        if provider == "printify":
            credentials["shop_id"] = store_connection.provider_store_id
        elif provider == "gelato":
            credentials["store_id"] = store_connection.provider_store_id
    return credentials


async def sync_provider_store_connections(
    db: Session,
    *,
    actor: ActorContext,
    provider: str,
    credential_key: str | None = None,
) -> ProviderStoreConnectionSyncResponse:
    started_at = time.perf_counter()
    _ensure_etsy_connected_for_provider_setup(
        db,
        organization_id=actor.organization_id,
        provider=provider,
    )
    status_payload = get_provider_credential_status(db, organization_id=actor.organization_id, provider=provider)
    if credential_key:
        credential_entries = [item for item in status_payload.credentials if item.credential_key == credential_key]
        if not credential_entries:
            raise HTTPException(status_code=404, detail="Provider credential not found.")
    else:
        credential_entries = [item for item in status_payload.credentials if not item.missing_keys]
    if not credential_entries:
        raise HTTPException(status_code=400, detail=f"Credentials for '{provider}' are incomplete.")

    created_count = 0
    updated_count = 0
    upserted_ids: list[str] = []
    synced_count = 0
    last_synced_credential_key = credential_key or credential_entries[0].credential_key
    discovered_etsy_shops = [
        shop
        for values in _list_etsy_connection_values(db, organization_id=actor.organization_id).values()
        for shop in (values.get("shops") if isinstance(values.get("shops"), list) else [])
        if isinstance(shop, dict)
    ]
    remote_connections_by_credential: dict[str, list[Any]] = {}

    for credential_entry in credential_entries:
        credentials = _build_scoped_provider_credentials(
            db,
            organization_id=actor.organization_id,
            provider=provider,
            credential_key=credential_entry.credential_key,
        )
        _ensure_provider_credentials_complete(provider, credentials)
        adapter = get_provider_adapter(provider, credentials)  # type: ignore[arg-type]
        try:
            remote_connections = await adapter.discover_store_connections()
        except Exception as exc:
            _raise_provider_action_error(
                provider=provider,
                action="syncing stores",
                exc=exc,
            )
        remote_connections_by_credential[credential_entry.credential_key] = remote_connections
        synced_count += len(remote_connections)
        last_synced_credential_key = credential_entry.credential_key
    current_etsy_count, projected_etsy_count = _projected_etsy_store_connection_count_for_sync(
        db,
        organization_id=actor.organization_id,
        provider=provider,
        remote_connections_by_credential=remote_connections_by_credential,
    )
    _ensure_etsy_store_limit(
        current_count=current_etsy_count,
        projected_count=projected_etsy_count,
        action="syncing another Etsy store",
    )

    for credential_entry in credential_entries:
        remote_connections = remote_connections_by_credential[credential_entry.credential_key]
        for remote in remote_connections:
            remote_etsy_shop_id = _resolve_remote_etsy_shop_id(etsy_shop_id=remote.etsy_shop_id)
            existing = db.scalar(
                select(ProviderStoreConnection).where(
                    ProviderStoreConnection.organization_id == actor.organization_id,
                    ProviderStoreConnection.provider == provider,
                    ProviderStoreConnection.credential_key == credential_entry.credential_key,
                    ProviderStoreConnection.provider_store_id == remote.provider_store_id,
                )
            )
            if existing:
                existing.storefront_type = remote.storefront_type
                existing.storefront_display_name = remote.storefront_display_name
                existing.label = remote.label
                existing.etsy_shop_id = remote_etsy_shop_id or existing.etsy_shop_id
                existing.discovery_source = remote.discovery_source
                existing.status = "connected"
                existing.deleted_at = None
                existing.last_synced_at = utc_now()
                updated_count += 1
                upserted_ids.append(existing.id)
            else:
                row = ProviderStoreConnection(
                    organization_id=actor.organization_id,
                    provider=provider,
                    credential_key=credential_entry.credential_key,
                    provider_store_id=remote.provider_store_id,
                    storefront_type=remote.storefront_type,
                    storefront_display_name=remote.storefront_display_name,
                    label=remote.label,
                    etsy_shop_id=remote_etsy_shop_id,
                    status="connected",
                    discovery_source=remote.discovery_source,
                    last_synced_at=utc_now(),
                )
                db.add(row)
                db.flush()
                created_count += 1
                upserted_ids.append(row.id)
    if discovered_etsy_shops:
        _auto_map_etsy_shop_ids(db, actor=actor, shops=discovered_etsy_shops)
    db.commit()
    rows = db.scalars(
        select(ProviderStoreConnection)
        .where(ProviderStoreConnection.id.in_(upserted_ids))
        .order_by(
            ProviderStoreConnection.credential_key.asc(),
            ProviderStoreConnection.label.asc(),
        )
    ).all()
    log_event(
        commerce_logger,
        "provider.store_connections.synced",
        verbose_only=True,
        organization_id=actor.organization_id,
        provider=provider,
        credential_key=last_synced_credential_key,
        credential_count=len(credential_entries),
        synced_count=synced_count,
        created_count=created_count,
        updated_count=updated_count,
        duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
    )
    return ProviderStoreConnectionSyncResponse(
        provider=provider,  # type: ignore[arg-type]
        credential_key=last_synced_credential_key,
        synced_count=synced_count,
        created_count=created_count,
        updated_count=updated_count,
        connections=[to_provider_store_connection(row) for row in rows],
    )


def delete_provider_store_connection(db: Session, *, actor: ActorContext, connection_id: str) -> None:
    row = db.scalar(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.id == connection_id,
            ProviderStoreConnection.organization_id == actor.organization_id,
            ProviderStoreConnection.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Provider store connection not found.")
    has_blueprints = db.scalar(
        select(func.count(ProductBlueprint.id)).where(ProductBlueprint.provider_store_connection_id == row.id)
    ) or 0
    has_drafts = db.scalar(
        select(func.count(ProviderProductDraft.id)).where(ProviderProductDraft.provider_store_connection_id == row.id)
    ) or 0
    has_pod_products = db.scalar(
        select(func.count(PodProduct.id)).where(PodProduct.provider_store_connection_id == row.id)
    ) or 0
    if has_blueprints or has_drafts or has_pod_products:
        raise HTTPException(
            status_code=409,
            detail="Provider store connection is still referenced by blueprints, drafts, or provider products.",
        )
    has_orders = db.scalar(
        select(func.count(Order.id)).where(Order.provider_store_connection_id == row.id)
    ) or 0
    has_sync_events = db.scalar(
        select(func.count(SyncEvent.id)).where(SyncEvent.provider_store_connection_id == row.id)
    ) or 0
    if has_orders or has_sync_events:
        row.status = "disconnected"
        row.deleted_at = utc_now()
        row.order_sync_cursor_json = None
    else:
        db.delete(row)
    db.commit()


def _get_store_connection_or_404(db: Session, *, actor: ActorContext, connection_id: str) -> ProviderStoreConnection:
    row = db.scalar(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.id == connection_id,
            ProviderStoreConnection.organization_id == actor.organization_id,
            ProviderStoreConnection.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Provider store connection not found.")
    return row
