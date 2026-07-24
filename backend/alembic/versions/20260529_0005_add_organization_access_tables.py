"""add organization access tables

Revision ID: 20260529_0005
Revises: 20260528_0004
Create Date: 2026-05-29 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260529_0005"
down_revision = "20260528_0004"
branch_labels = None
depends_on = None


def _create_rejection_policy() -> None:
    op.execute("DROP POLICY IF EXISTS deny_client_access ON public.organization_join_requests")
    op.execute(
        """
        CREATE POLICY deny_client_access
        ON public.organization_join_requests
        FOR ALL
        TO anon, authenticated
        USING (false)
        WITH CHECK (false)
        """
    )


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("join_code", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_organizations_created_by_user_id",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_organizations_join_code", ["join_code"], unique=True)

    op.create_table(
        "organization_join_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_organization_join_requests_organization_id", "organization_join_requests", ["organization_id"])
    op.create_index("ix_organization_join_requests_requested_by_user_id", "organization_join_requests", ["requested_by_user_id"])
    op.create_index("ix_organization_join_requests_status", "organization_join_requests", ["status"])

    op.execute("UPDATE organizations SET created_by_user_id = 'default-user' WHERE id = 'default-org'")
    op.execute(
        """
        UPDATE organizations
        SET created_by_user_id = (
            SELECT memberships.user_id
            FROM memberships
            WHERE memberships.organization_id = organizations.id
            ORDER BY memberships.created_at ASC
            LIMIT 1
        )
        WHERE created_by_user_id IS NULL
        """
    )
    op.execute("UPDATE organizations SET join_code = 'VELORADEV' WHERE id = 'default-org'")
    op.execute(
        """
        UPDATE organizations
        SET join_code = UPPER(SUBSTR(REPLACE(id, '-', ''), 1, 8))
        WHERE join_code IS NULL
        """
    )

    op.execute("UPDATE memberships SET role = 'admin' WHERE role = 'owner'")
    op.execute("UPDATE memberships SET role = 'member' WHERE role IS NULL OR TRIM(role) = ''")
    op.execute(
        """
        UPDATE memberships
        SET role = 'admin'
        WHERE EXISTS (
            SELECT 1
            FROM organizations
            WHERE organizations.id = memberships.organization_id
              AND organizations.created_by_user_id = memberships.user_id
        )
        """
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _create_rejection_policy()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS deny_client_access ON public.organization_join_requests")

    op.drop_index("ix_organization_join_requests_status", table_name="organization_join_requests")
    op.drop_index("ix_organization_join_requests_requested_by_user_id", table_name="organization_join_requests")
    op.drop_index("ix_organization_join_requests_organization_id", table_name="organization_join_requests")
    op.drop_table("organization_join_requests")

    with op.batch_alter_table("organizations") as batch:
        batch.drop_index("ix_organizations_join_code")
        batch.drop_constraint("fk_organizations_created_by_user_id", type_="foreignkey")
        batch.drop_column("join_code")
        batch.drop_column("created_by_user_id")
