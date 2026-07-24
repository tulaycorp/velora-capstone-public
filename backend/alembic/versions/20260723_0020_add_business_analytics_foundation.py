"""add business analytics foundation

Revision ID: 20260723_0020
Revises: 20260723_0019
Create Date: 2026-07-23 22:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260723_0020"
down_revision = "20260723_0019"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table_name: str, *, runtime_write: bool, worker_write: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    runtime_permissions = "SELECT, INSERT, UPDATE, DELETE" if runtime_write else "SELECT"
    worker_permissions = "SELECT, INSERT, UPDATE, DELETE" if worker_write else "SELECT"
    op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT {runtime_permissions} ON public.{table_name} TO velora_runtime")
    op.execute(f"GRANT {worker_permissions} ON public.{table_name} TO velora_worker")
    op.execute(
        f"CREATE POLICY runtime_{table_name}_access ON public.{table_name} "
        "FOR ALL TO velora_runtime USING ("
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), '')) "
        "WITH CHECK ("
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), ''))"
    )
    op.execute(
        f"CREATE POLICY worker_{table_name}_access ON public.{table_name} "
        "FOR ALL TO velora_worker USING ("
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), '')) "
        "WITH CHECK ("
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), ''))"
    )
    op.execute(
        f"CREATE POLICY deny_client_access ON public.{table_name} "
        "FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
    )


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(
            sa.Column("reporting_currency", sa.String(length=8), nullable=False, server_default="PHP")
        )
        batch_op.add_column(
            sa.Column(
                "reporting_timezone",
                sa.String(length=64),
                nullable=False,
                server_default="Asia/Manila",
            )
        )
    with op.batch_alter_table("orders") as batch_op:
        batch_op.create_unique_constraint("uq_orders_org_id", ["organization_id", "id"])

    op.create_table(
        "order_line_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("external_line_id", sa.String(length=255), nullable=False),
        sa.Column("external_listing_id", sa.String(length=255), nullable=True),
        sa.Column("external_product_id", sa.String(length=255), nullable=True),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("revenue_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("production_cost_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("shipping_cost_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("provider_fee_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("mapping_status", sa.String(length=32), nullable=False),
        sa.Column("mapped_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("mapped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_line_items_quantity_positive"),
        sa.CheckConstraint(
            "mapping_status IN ('matched', 'unmatched', 'manual')",
            name="ck_order_line_items_mapping_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "order_id"],
            ["orders.organization_id", "orders.id"],
            name="fk_order_line_items_org_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_order_line_items_org_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["mapped_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "order_id",
            "external_line_id",
            name="uq_order_line_items_org_order_external",
        ),
    )
    for column_name in (
        "organization_id",
        "order_id",
        "product_id",
        "external_listing_id",
        "external_product_id",
        "sku",
    ):
        op.create_index(
            f"ix_order_line_items_{column_name}",
            "order_line_items",
            [column_name],
        )

    op.create_table(
        "expenses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider_store_connection_id", sa.String(length=36), nullable=True),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("incurred_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_expenses_amount_nonnegative"),
        sa.CheckConstraint(
            "source IN ('manual', 'etsy', 'printify', 'gelato', 'shopify', 'system')",
            name="ck_expenses_source",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_expenses_org_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_expenses_org_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "source",
            "external_id",
            name="uq_expenses_org_source_external",
        ),
    )
    for column_name in ("organization_id", "provider_store_connection_id", "product_id", "category"):
        op.create_index(f"ix_expenses_{column_name}", "expenses", [column_name])

    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("base_currency", sa.String(length=8), nullable=False),
        sa.Column("quote_currency", sa.String(length=8), nullable=False),
        sa.Column("effective_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rate > 0", name="ck_exchange_rates_rate_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "base_currency",
            "quote_currency",
            "effective_on",
            name="uq_exchange_rates_org_pair_date",
        ),
    )
    op.create_index("ix_exchange_rates_organization_id", "exchange_rates", ["organization_id"])

    _enable_tenant_rls("order_line_items", runtime_write=True, worker_write=True)
    _enable_tenant_rls("expenses", runtime_write=True, worker_write=True)
    _enable_tenant_rls("exchange_rates", runtime_write=False, worker_write=True)


def downgrade() -> None:
    op.drop_table("exchange_rates")
    op.drop_table("expenses")
    op.drop_table("order_line_items")
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("uq_orders_org_id", type_="unique")
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_column("reporting_timezone")
        batch_op.drop_column("reporting_currency")
