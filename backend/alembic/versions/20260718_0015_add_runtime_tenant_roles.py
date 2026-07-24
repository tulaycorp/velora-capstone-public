"""add non-owner runtime tenant roles and policies

Revision ID: 20260718_0015
Revises: 20260718_0014
Create Date: 2026-07-18 00:30:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260718_0015"
down_revision = "20260718_0014"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "provider_credentials",
    "oauth_request_states",
    "provider_store_connections",
    "product_blueprints",
    "design_assets",
    "provider_product_drafts",
    "ai_generations",
    "mockups",
    "pod_products",
    "publishing_jobs",
    "orders",
    "sync_jobs",
    "sync_events",
)

RLS_TABLES = (
    "organizations",
    "users",
    "memberships",
    "organization_join_requests",
    *TENANT_TABLES,
    "publishing_outbox",
)

CURRENT_ACTOR = "NULLIF(current_setting('app.current_actor_id', true), '')"
CURRENT_ORGANIZATION = (
    "NULLIF(current_setting('app.current_organization_id', true), '')"
)
CURRENT_JOIN_CODE = "NULLIF(current_setting('app.current_join_code', true), '')"


def _create_roles_and_grants() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'velora_runtime') THEN "
        "CREATE ROLE velora_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'velora_worker') THEN "
        "CREATE ROLE velora_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; "
        "END IF; "
        "END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('velora_runtime', 'velora_worker') "
        "AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN "
        "RAISE EXCEPTION 'Velora runtime roles must remain NOLOGIN and unprivileged'; "
        "END IF; "
        "END $$"
    )
    op.execute("GRANT velora_runtime, velora_worker TO CURRENT_USER")
    op.execute("GRANT USAGE ON SCHEMA public TO velora_runtime, velora_worker")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "TO velora_runtime, velora_worker"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO velora_runtime, velora_worker"
    )


def _force_rls() -> None:
    for table_name in RLS_TABLES:
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table_name} FORCE ROW LEVEL SECURITY")


def _create_identity_policies() -> None:
    op.execute(
        "CREATE POLICY runtime_organizations_select ON public.organizations "
        "FOR SELECT TO velora_runtime USING ("
        f"id = {CURRENT_ORGANIZATION} OR created_by_user_id = {CURRENT_ACTOR} OR "
        f"join_code = {CURRENT_JOIN_CODE} OR EXISTS ("
        "SELECT 1 FROM public.memberships membership "
        "WHERE membership.organization_id = organizations.id "
        f"AND membership.user_id = {CURRENT_ACTOR}))"
    )
    op.execute(
        "CREATE POLICY runtime_organizations_insert ON public.organizations "
        "FOR INSERT TO velora_runtime WITH CHECK ("
        f"created_by_user_id = {CURRENT_ACTOR})"
    )
    op.execute(
        "CREATE POLICY runtime_organizations_update ON public.organizations "
        "FOR UPDATE TO velora_runtime "
        f"USING (id = {CURRENT_ORGANIZATION}) "
        f"WITH CHECK (id = {CURRENT_ORGANIZATION})"
    )
    op.execute(
        "CREATE POLICY runtime_organizations_delete ON public.organizations "
        "FOR DELETE TO velora_runtime "
        f"USING (id = {CURRENT_ORGANIZATION})"
    )

    op.execute(
        "CREATE POLICY runtime_users_access ON public.users "
        "FOR ALL TO velora_runtime "
        f"USING (id = {CURRENT_ACTOR}) WITH CHECK (id = {CURRENT_ACTOR})"
    )
    op.execute(
        "CREATE POLICY runtime_memberships_access ON public.memberships "
        "FOR ALL TO velora_runtime "
        f"USING (user_id = {CURRENT_ACTOR} OR organization_id = {CURRENT_ORGANIZATION}) "
        f"WITH CHECK (user_id = {CURRENT_ACTOR} OR organization_id = {CURRENT_ORGANIZATION})"
    )
    op.execute(
        "CREATE POLICY runtime_join_requests_access ON public.organization_join_requests "
        "FOR ALL TO velora_runtime "
        f"USING (requested_by_user_id = {CURRENT_ACTOR} OR "
        f"organization_id = {CURRENT_ORGANIZATION}) "
        f"WITH CHECK (requested_by_user_id = {CURRENT_ACTOR} OR "
        f"organization_id = {CURRENT_ORGANIZATION})"
    )


def _create_tenant_policies() -> None:
    tenant_predicate = f"organization_id = {CURRENT_ORGANIZATION}"
    for table_name in TENANT_TABLES:
        op.execute(
            f"CREATE POLICY runtime_tenant_access ON public.{table_name} "
            "FOR ALL TO velora_runtime "
            f"USING ({tenant_predicate}) WITH CHECK ({tenant_predicate})"
        )
        op.execute(
            f"CREATE POLICY worker_tenant_access ON public.{table_name} "
            "FOR ALL TO velora_worker "
            f"USING ({tenant_predicate}) WITH CHECK ({tenant_predicate})"
        )

    op.execute(
        "CREATE POLICY runtime_publishing_outbox_access ON public.publishing_outbox "
        "FOR ALL TO velora_runtime USING (EXISTS ("
        "SELECT 1 FROM public.publishing_jobs job "
        "WHERE job.id = publishing_outbox.publishing_job_id "
        f"AND job.organization_id = {CURRENT_ORGANIZATION}"
        ")) WITH CHECK (EXISTS ("
        "SELECT 1 FROM public.publishing_jobs job "
        "WHERE job.id = publishing_outbox.publishing_job_id "
        f"AND job.organization_id = {CURRENT_ORGANIZATION}"
        "))"
    )


def _create_worker_envelope_policies() -> None:
    for table_name in ("sync_jobs", "publishing_jobs"):
        op.execute(
            f"CREATE POLICY worker_job_envelope_access ON public.{table_name} "
            "FOR ALL TO velora_worker USING (true) WITH CHECK (true)"
        )
    op.execute(
        "CREATE POLICY worker_store_discovery ON public.provider_store_connections "
        "FOR SELECT TO velora_worker USING (true)"
    )
    op.execute(
        "CREATE POLICY worker_publishing_outbox_access ON public.publishing_outbox "
        "FOR ALL TO velora_worker USING (true) WITH CHECK (true)"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _create_roles_and_grants()
    _force_rls()
    _create_identity_policies()
    _create_tenant_policies()
    _create_worker_envelope_policies()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        "DROP POLICY IF EXISTS worker_publishing_outbox_access ON public.publishing_outbox"
    )
    op.execute(
        "DROP POLICY IF EXISTS worker_store_discovery ON public.provider_store_connections"
    )
    for table_name in ("publishing_jobs", "sync_jobs"):
        op.execute(
            f"DROP POLICY IF EXISTS worker_job_envelope_access ON public.{table_name}"
        )

    op.execute(
        "DROP POLICY IF EXISTS runtime_publishing_outbox_access ON public.publishing_outbox"
    )
    for table_name in reversed(TENANT_TABLES):
        op.execute(
            f"DROP POLICY IF EXISTS worker_tenant_access ON public.{table_name}"
        )
        op.execute(
            f"DROP POLICY IF EXISTS runtime_tenant_access ON public.{table_name}"
        )

    for table_name, policy_names in (
        (
            "organization_join_requests",
            ("runtime_join_requests_access",),
        ),
        ("memberships", ("runtime_memberships_access",)),
        ("users", ("runtime_users_access",)),
        (
            "organizations",
            (
                "runtime_organizations_delete",
                "runtime_organizations_update",
                "runtime_organizations_insert",
                "runtime_organizations_select",
            ),
        ),
    ):
        for policy_name in policy_names:
            op.execute(
                f"DROP POLICY IF EXISTS {policy_name} ON public.{table_name}"
            )

    for table_name in reversed(RLS_TABLES):
        op.execute(f"ALTER TABLE public.{table_name} NO FORCE ROW LEVEL SECURITY")

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES "
        "FROM velora_runtime, velora_worker"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "FROM velora_runtime, velora_worker"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM velora_runtime, velora_worker")
