"""add public rls rejection policies

Revision ID: 20260528_0004
Revises: 20260528_0003
Create Date: 2026-05-28 02:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260528_0004"
down_revision = "20260528_0003"
branch_labels = None
depends_on = None


PUBLIC_TABLES = (
    "alembic_version",
    "design_assets",
    "memberships",
    "mockups",
    "organizations",
    "pod_products",
    "product_blueprints",
    "provider_credentials",
    "provider_product_drafts",
    "provider_store_connections",
    "publishing_jobs",
    "users",
)


def _create_rejection_policy(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS deny_client_access ON public.{table_name}")
    op.execute(
        f"""
        CREATE POLICY deny_client_access
        ON public.{table_name}
        FOR ALL
        TO anon, authenticated
        USING (false)
        WITH CHECK (false)
        """
    )


def _drop_rejection_policy(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS deny_client_access ON public.{table_name}")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table_name in PUBLIC_TABLES:
        _create_rejection_policy(table_name)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table_name in PUBLIC_TABLES:
        _drop_rejection_policy(table_name)
