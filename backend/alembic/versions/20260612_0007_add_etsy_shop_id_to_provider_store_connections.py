"""add etsy shop id to provider store connections

Revision ID: 20260612_0007
Revises: 5e7f1e4949c0
Create Date: 2026-06-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260612_0007"
down_revision = "5e7f1e4949c0"
branch_labels = None
depends_on = None


def _normalize_optional_string(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _extract_etsy_shop_id(*, storefront_type: str, raw_data: Mapping[str, Any] | None) -> str | None:
    if storefront_type != "etsy" or not isinstance(raw_data, Mapping):
        return None

    direct_candidates = (
        raw_data.get("etsy_shop_id"),
        raw_data.get("marketplace_shop_id"),
        raw_data.get("etsyShopId"),
        raw_data.get("marketplaceShopId"),
    )
    for candidate in direct_candidates:
        normalized = _normalize_optional_string(candidate)
        if normalized:
            return normalized

    nested_collections = [
        raw_data.get("sales_channel_properties"),
        raw_data.get("marketplace"),
        raw_data.get("marketplace_data"),
        raw_data.get("external"),
        raw_data.get("manual_seed"),
    ]
    for collection in nested_collections:
        mappings: list[Mapping[str, Any]] = []
        if isinstance(collection, Mapping):
            mappings.append(collection)
        elif isinstance(collection, list):
            mappings.extend(item for item in collection if isinstance(item, Mapping))
        for item in mappings:
            for candidate in (
                item.get("etsy_shop_id"),
                item.get("marketplace_shop_id"),
                item.get("shop_id"),
                item.get("shopId"),
                item.get("etsyShopId"),
                item.get("marketplaceShopId"),
            ):
                normalized = _normalize_optional_string(candidate)
                if normalized:
                    return normalized
    return None


def upgrade() -> None:
    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.add_column(sa.Column("etsy_shop_id", sa.String(length=255), nullable=True))

    provider_store_connections = sa.table(
        "provider_store_connections",
        sa.column("id", sa.String(length=36)),
        sa.column("storefront_type", sa.String(length=32)),
        sa.column("raw_data_json", sa.JSON()),
        sa.column("etsy_shop_id", sa.String(length=255)),
    )
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.select(
                provider_store_connections.c.id,
                provider_store_connections.c.storefront_type,
                provider_store_connections.c.raw_data_json,
            )
        ).mappings()
    )
    for row in rows:
        etsy_shop_id = _extract_etsy_shop_id(
            storefront_type=str(row["storefront_type"] or ""),
            raw_data=row["raw_data_json"],
        )
        if not etsy_shop_id:
            continue
        bind.execute(
            provider_store_connections.update()
            .where(provider_store_connections.c.id == row["id"])
            .values(etsy_shop_id=etsy_shop_id)
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.drop_column("etsy_shop_id")
