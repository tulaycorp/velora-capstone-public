"""add AI generation requester rate-limit scope

Revision ID: 20260718_0017
Revises: 20260718_0016
Create Date: 2026-07-18 04:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260718_0017"
down_revision = "20260718_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_generations") as batch_op:
        batch_op.add_column(
            sa.Column("requested_by_user_id", sa.String(length=64), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_ai_generations_org_requester_membership",
            "memberships",
            ["organization_id", "requested_by_user_id"],
            ["organization_id", "user_id"],
            ondelete="RESTRICT",
        )

    op.create_index(
        "ix_ai_generations_org_requester_created",
        "ai_generations",
        ["organization_id", "requested_by_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_generations_org_requester_created",
        table_name="ai_generations",
    )
    with op.batch_alter_table("ai_generations") as batch_op:
        batch_op.drop_constraint(
            "fk_ai_generations_org_requester_membership",
            type_="foreignkey",
        )
        batch_op.drop_column("requested_by_user_id")
