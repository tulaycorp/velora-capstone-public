"""add provider credential keys to store connections

Revision ID: 20260603_0006
Revises: 20260529_0005
Create Date: 2026-06-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260603_0006"
down_revision = "20260529_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.add_column(
            sa.Column(
                "credential_key",
                sa.String(length=64),
                nullable=False,
                server_default="default",
            )
        )
        batch_op.drop_constraint("uq_provider_store_connection_org_provider_store", type_="unique")
        batch_op.create_unique_constraint(
            "uq_provider_store_connection_org_provider_store",
            ["organization_id", "provider", "credential_key", "provider_store_id"],
        )
        batch_op.create_index(
            "ix_provider_store_connections_credential_key",
            ["credential_key"],
            unique=False,
        )

    op.execute("UPDATE provider_store_connections SET credential_key = 'default' WHERE credential_key IS NULL")

    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.alter_column("credential_key", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.drop_index("ix_provider_store_connections_credential_key")
        batch_op.drop_constraint("uq_provider_store_connection_org_provider_store", type_="unique")
        batch_op.create_unique_constraint(
            "uq_provider_store_connection_org_provider_store",
            ["organization_id", "provider", "provider_store_id"],
        )
        batch_op.drop_column("credential_key")
