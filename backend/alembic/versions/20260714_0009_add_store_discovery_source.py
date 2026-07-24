"""add safe store discovery source

Revision ID: 20260714_0009
Revises: 20260623_0008
Create Date: 2026-07-14 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260714_0009"
down_revision = "20260623_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.add_column(sa.Column("encryption_key_id", sa.String(length=64), nullable=True))
    op.execute("UPDATE provider_credentials SET encryption_key_id = 'v1' WHERE encryption_key_id IS NULL")
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.alter_column("encryption_key_id", nullable=False, server_default="v1")

    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.add_column(sa.Column("discovery_source", sa.String(length=32), nullable=True))

    op.execute(
        "UPDATE provider_store_connections "
        "SET discovery_source = 'legacy' "
        "WHERE discovery_source IS NULL"
    )

    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.alter_column("discovery_source", nullable=False, server_default="legacy")


def downgrade() -> None:
    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.drop_column("discovery_source")
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.drop_column("encryption_key_id")
