"""add resumable publishing job stage

Revision ID: 20260723_0019
Revises: 20260718_0018
Create Date: 2026-07-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260723_0019"
down_revision = "20260718_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.add_column(
            sa.Column("stage", sa.String(length=64), nullable=False, server_default="queued")
        )
    op.execute(
        "UPDATE publishing_jobs SET stage = 'completed' WHERE status = 'succeeded'"
    )
    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.alter_column("stage", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.drop_column("stage")
