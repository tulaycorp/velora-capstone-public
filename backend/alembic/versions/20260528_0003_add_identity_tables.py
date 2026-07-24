"""add identity tables

Revision ID: 20260528_0003
Revises: 20260528_0002
Create Date: 2026-05-28 01:00:00.000000
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260528_0003"
down_revision = "20260528_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("auth_provider", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("auth_provider", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_organization_user"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    timestamp = datetime.now(timezone.utc)
    organization_table = sa.table(
        "organizations",
        sa.column("id", sa.String(length=64)),
        sa.column("auth_provider", sa.String(length=32)),
        sa.column("name", sa.String(length=255)),
        sa.column("slug", sa.String(length=255)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    user_table = sa.table(
        "users",
        sa.column("id", sa.String(length=64)),
        sa.column("auth_provider", sa.String(length=32)),
        sa.column("email", sa.String(length=255)),
        sa.column("first_name", sa.String(length=255)),
        sa.column("last_name", sa.String(length=255)),
        sa.column("image_url", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    membership_table = sa.table(
        "memberships",
        sa.column("id", sa.String(length=36)),
        sa.column("organization_id", sa.String(length=64)),
        sa.column("user_id", sa.String(length=64)),
        sa.column("role", sa.String(length=128)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    op.bulk_insert(
        organization_table,
        [
            {
                "id": "default-org",
                "auth_provider": "local",
                "name": "Default Organization",
                "slug": None,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
    )
    op.bulk_insert(
        user_table,
        [
            {
                "id": "default-user",
                "auth_provider": "local",
                "email": None,
                "first_name": None,
                "last_name": None,
                "image_url": None,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
    )
    op.bulk_insert(
        membership_table,
        [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "organization_id": "default-org",
                "user_id": "default-user",
                "role": "owner",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_organization_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
