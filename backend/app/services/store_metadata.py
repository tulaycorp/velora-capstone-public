from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderStoreConnection


SAFE_DISCOVERY_SOURCES = {"provider_api", "orders", "manual", "merged", "legacy"}
SAFE_ETSY_SHOP_ID_KEYS = (
    "etsy_shop_id",
    "marketplace_shop_id",
    "shop_id",
    "shopId",
    "etsyShopId",
    "marketplaceShopId",
)
SAFE_ETSY_SHOP_ID_CONTAINERS = (
    "sales_channel_properties",
    "marketplace",
    "marketplace_data",
    "external",
    "manual_seed",
)


@dataclass(frozen=True)
class StoreMetadataScrubSummary:
    scanned_count: int
    metadata_cleared_count: int
    etsy_shop_id_backfilled_count: int


def _normalized_string(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def extract_safe_etsy_shop_id(metadata: Mapping[str, Any] | None) -> str | None:
    if not isinstance(metadata, Mapping):
        return None

    candidates: list[Mapping[str, Any]] = [metadata]
    for key in SAFE_ETSY_SHOP_ID_CONTAINERS:
        nested = metadata.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
        elif isinstance(nested, list):
            candidates.extend(item for item in nested if isinstance(item, Mapping))

    for candidate in candidates:
        for key in SAFE_ETSY_SHOP_ID_KEYS:
            shop_id = _normalized_string(candidate.get(key))
            if shop_id:
                return shop_id
    return None


def normalize_discovery_source(metadata: Mapping[str, Any] | None) -> str:
    if not isinstance(metadata, Mapping):
        return "legacy"
    discovery = metadata.get("discovery")
    source = discovery.get("source") if isinstance(discovery, Mapping) else None
    return source if source in SAFE_DISCOVERY_SOURCES else "legacy"


def scrub_provider_store_metadata(db: Session, *, apply: bool) -> StoreMetadataScrubSummary:
    rows = db.scalars(select(ProviderStoreConnection)).all()
    cleared = 0
    backfilled = 0

    for row in rows:
        metadata = row.raw_data_json if isinstance(row.raw_data_json, Mapping) else None
        if row.discovery_source not in SAFE_DISCOVERY_SOURCES:
            row.discovery_source = normalize_discovery_source(metadata)
        if not row.etsy_shop_id and row.storefront_type == "etsy":
            safe_shop_id = extract_safe_etsy_shop_id(metadata)
            if safe_shop_id:
                row.etsy_shop_id = safe_shop_id
                backfilled += 1
        if row.raw_data_json is not None:
            row.raw_data_json = None
            cleared += 1

    if not apply:
        db.rollback()
    else:
        db.commit()

    return StoreMetadataScrubSummary(
        scanned_count=len(rows),
        metadata_cleared_count=cleared,
        etsy_shop_id_backfilled_count=backfilled,
    )
