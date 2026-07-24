"""scrub legacy provider store metadata

Revision ID: 20260718_0018
Revises: 20260718_0017
Create Date: 2026-07-18 05:00:00.000000
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260718_0018"
down_revision = "20260718_0017"
branch_labels = None
depends_on = None


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


def _normalized_string(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _extract_safe_etsy_shop_id(metadata: Mapping[str, Any] | None) -> str | None:
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


def upgrade() -> None:
    provider_store_connections = sa.table(
        "provider_store_connections",
        sa.column("id", sa.String(length=36)),
        sa.column("storefront_type", sa.String(length=32)),
        sa.column("etsy_shop_id", sa.String(length=255)),
        sa.column("raw_data_json", sa.JSON()),
    )
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.select(
                provider_store_connections.c.id,
                provider_store_connections.c.storefront_type,
                provider_store_connections.c.etsy_shop_id,
                provider_store_connections.c.raw_data_json,
            ).where(provider_store_connections.c.raw_data_json.is_not(None))
        ).mappings()
    )

    for row in rows:
        values: dict[str, object] = {"raw_data_json": sa.null()}
        if row["storefront_type"] == "etsy" and not row["etsy_shop_id"]:
            safe_shop_id = _extract_safe_etsy_shop_id(row["raw_data_json"])
            if safe_shop_id:
                values["etsy_shop_id"] = safe_shop_id
        bind.execute(
            provider_store_connections.update()
            .where(provider_store_connections.c.id == row["id"])
            .values(**values)
        )

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.velora_clear_provider_store_raw_metadata()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY INVOKER
            SET search_path = ''
            AS $$
            BEGIN
                NEW.raw_data_json := NULL;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            "REVOKE ALL ON FUNCTION "
            "public.velora_clear_provider_store_raw_metadata() "
            "FROM PUBLIC, anon, authenticated"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS clear_provider_store_raw_metadata "
            "ON public.provider_store_connections"
        )
        op.execute(
            """
            CREATE TRIGGER clear_provider_store_raw_metadata
            BEFORE INSERT OR UPDATE OF raw_data_json
            ON public.provider_store_connections
            FOR EACH ROW
            WHEN (NEW.raw_data_json IS NOT NULL)
            EXECUTE FUNCTION public.velora_clear_provider_store_raw_metadata()
            """
        )


def downgrade() -> None:
    # The scrub intentionally cannot restore retired opaque provider payloads.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS clear_provider_store_raw_metadata "
            "ON public.provider_store_connections"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS "
            "public.velora_clear_provider_store_raw_metadata()"
        )
