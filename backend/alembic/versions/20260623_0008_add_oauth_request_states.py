"""add oauth request state ledger

Revision ID: 20260623_0008
Revises: 20260612_0007
Create Date: 2026-06-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260623_0008"
down_revision = "20260612_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_request_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("state_digest", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "state_digest", name="uq_oauth_request_state_provider_digest"),
    )
    op.create_index(
        "ix_oauth_request_states_org_provider",
        "oauth_request_states",
        ["organization_id", "provider"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_request_states_actor_provider",
        "oauth_request_states",
        ["actor_id", "provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_request_states_actor_id"),
        "oauth_request_states",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_request_states_organization_id"),
        "oauth_request_states",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_oauth_request_states_provider"),
        "oauth_request_states",
        ["provider"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_request_states_provider"), table_name="oauth_request_states")
    op.drop_index(op.f("ix_oauth_request_states_organization_id"), table_name="oauth_request_states")
    op.drop_index(op.f("ix_oauth_request_states_actor_id"), table_name="oauth_request_states")
    op.drop_index("ix_oauth_request_states_actor_provider", table_name="oauth_request_states")
    op.drop_index("ix_oauth_request_states_org_provider", table_name="oauth_request_states")
    op.drop_table("oauth_request_states")
