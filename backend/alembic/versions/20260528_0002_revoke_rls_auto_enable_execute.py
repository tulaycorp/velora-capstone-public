"""revoke rls auto enable execute

Revision ID: 20260528_0002
Revises: 20260528_0001
Create Date: 2026-05-28 00:30:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260528_0002"
down_revision = "20260528_0001"
branch_labels = None
depends_on = None


def _ensure_legacy_supabase_roles() -> None:
    """Keep the historical policy chain runnable on non-Supabase Postgres."""
    op.execute(
        """
        DO $$
        DECLARE role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
            LOOP
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format(
                        'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
                        role_name
                    );
                END IF;
            END LOOP;
        END
        $$
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _ensure_legacy_supabase_roles()
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regprocedure('public.rls_auto_enable()') IS NOT NULL THEN
                REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC, anon, authenticated;
                GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO service_role;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regprocedure('public.rls_auto_enable()') IS NOT NULL THEN
                GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO PUBLIC, anon, authenticated;
            END IF;
        END
        $$
        """
    )
