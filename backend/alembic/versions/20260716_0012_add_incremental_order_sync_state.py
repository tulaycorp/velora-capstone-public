"""add incremental order sync state

Revision ID: 20260716_0012
Revises: 20260716_0011
Create Date: 2026-07-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260716_0012"
down_revision = "20260716_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.add_column(sa.Column("order_sync_cursor_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("order_sync_watermark_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("order_sync_last_success_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.drop_column("order_sync_last_success_at")
        batch_op.drop_column("order_sync_watermark_at")
        batch_op.drop_column("order_sync_cursor_json")
