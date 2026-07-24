"""add durable provider analytics snapshots

Revision ID: 20260718_0016
Revises: 20260718_0015
Create Date: 2026-07-18 03:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260718_0016"
down_revision = "20260718_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "analytics_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("source_scope", sa.String(length=128), nullable=False),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at IS NULL OR fetched_at IS NOT NULL",
            name="ck_analytics_snapshots_expiry_requires_fetch",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_analytics_snapshots_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_analytics_snapshots_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "source_scope",
            name="uq_analytics_snapshots_org_provider_scope",
        ),
    )
    op.create_index(
        "ix_analytics_snapshots_organization_id",
        "analytics_snapshots",
        ["organization_id"],
        unique=False,
    )

    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE public.analytics_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.analytics_snapshots FORCE ROW LEVEL SECURITY")
    op.execute(
        "GRANT SELECT ON public.analytics_snapshots TO velora_runtime"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.analytics_snapshots TO velora_worker"
    )
    op.execute(
        "CREATE POLICY runtime_analytics_snapshots_select ON public.analytics_snapshots "
        "FOR SELECT TO velora_runtime USING ("
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), ''))"
    )
    op.execute(
        "CREATE POLICY worker_analytics_snapshots_access ON public.analytics_snapshots "
        "FOR ALL TO velora_worker USING ("
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), '')) "
        "WITH CHECK ("
        "organization_id = NULLIF(current_setting('app.current_organization_id', true), ''))"
    )
    op.execute(
        "CREATE POLICY deny_client_access ON public.analytics_snapshots "
        "FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_snapshots_organization_id",
        table_name="analytics_snapshots",
    )
    op.drop_table("analytics_snapshots")
