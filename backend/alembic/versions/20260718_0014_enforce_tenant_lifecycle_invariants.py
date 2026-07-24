"""enforce tenant and lifecycle invariants

Revision ID: 20260718_0014
Revises: 20260716_0013
Create Date: 2026-07-18 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260718_0014"
down_revision = "20260716_0013"
branch_labels = None
depends_on = None


ORG_OWNED_TABLES = (
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

CLIENT_DENY_TABLES = (
    "ai_generations",
    "oauth_request_states",
    "orders",
    "sync_jobs",
    "sync_events",
)


def _scalar_count(sql: str) -> int:
    return int(op.get_bind().scalar(sa.text(sql)) or 0)


def _assert_clean_legacy_tenant_data() -> None:
    duplicate_memberships = _scalar_count(
        "SELECT COUNT(*) FROM ("
        "SELECT user_id FROM memberships GROUP BY user_id HAVING COUNT(*) > 1"
        ") duplicate_users"
    )
    if duplicate_memberships:
        raise RuntimeError(
            "Cannot enforce one organization per user while duplicate memberships exist."
        )

    for table_name in ORG_OWNED_TABLES:
        orphan_count = _scalar_count(
            f"SELECT COUNT(*) FROM {table_name} child "
            "LEFT JOIN organizations parent ON parent.id = child.organization_id "
            "WHERE parent.id IS NULL"
        )
        if orphan_count:
            raise RuntimeError(
                f"Cannot enforce organization ownership: {table_name} contains orphan rows."
            )

    tenant_links = (
        ("product_blueprints", "provider_store_connection_id", "provider_store_connections"),
        ("provider_product_drafts", "blueprint_id", "product_blueprints"),
        ("provider_product_drafts", "provider_store_connection_id", "provider_store_connections"),
        ("provider_product_drafts", "design_asset_id", "design_assets"),
        ("ai_generations", "provider_product_draft_id", "provider_product_drafts"),
        ("ai_generations", "provider_store_connection_id", "provider_store_connections"),
        ("mockups", "provider_product_draft_id", "provider_product_drafts"),
        ("pod_products", "provider_product_draft_id", "provider_product_drafts"),
        ("pod_products", "provider_store_connection_id", "provider_store_connections"),
        ("publishing_jobs", "blueprint_id", "product_blueprints"),
        ("publishing_jobs", "provider_product_draft_id", "provider_product_drafts"),
        ("publishing_jobs", "pod_product_id", "pod_products"),
        ("publishing_jobs", "provider_store_connection_id", "provider_store_connections"),
        ("publishing_jobs", "sync_job_id", "sync_jobs"),
        ("orders", "provider_store_connection_id", "provider_store_connections"),
        ("sync_events", "sync_job_id", "sync_jobs"),
        ("sync_events", "provider_store_connection_id", "provider_store_connections"),
    )
    for child_table, child_column, parent_table in tenant_links:
        mismatch_count = _scalar_count(
            f"SELECT COUNT(*) FROM {child_table} child "
            f"JOIN {parent_table} parent ON parent.id = child.{child_column} "
            f"WHERE child.{child_column} IS NOT NULL "
            "AND child.organization_id <> parent.organization_id"
        )
        if mismatch_count:
            raise RuntimeError(
                "Cannot enforce tenant link: "
                f"{child_table}.{child_column} contains cross-organization references."
            )

    last_generation_mismatches = _scalar_count(
        "SELECT COUNT(*) FROM provider_product_drafts draft "
        "JOIN ai_generations generation ON generation.id = draft.last_ai_generation_id "
        "WHERE draft.last_ai_generation_id IS NOT NULL AND ("
        "draft.organization_id <> generation.organization_id OR "
        "draft.id <> generation.provider_product_draft_id)"
    )
    if last_generation_mismatches:
        raise RuntimeError(
            "Cannot enforce the last AI generation link while cross-product references exist."
        )


def _normalize_lifecycle_values() -> None:
    op.execute(
        "UPDATE memberships SET role = 'member' "
        "WHERE role IS NULL OR role NOT IN ('admin', 'member')"
    )
    op.execute(
        "UPDATE organization_join_requests SET status = 'rejected' "
        "WHERE status NOT IN ('pending', 'approved', 'rejected')"
    )
    op.execute(
        "UPDATE provider_store_connections SET status = 'disconnected' "
        "WHERE status NOT IN ('connected', 'disconnected')"
    )
    op.execute(
        "UPDATE product_blueprints SET status = 'draft' "
        "WHERE status NOT IN ('draft', 'active', 'archived')"
    )
    op.execute(
        "UPDATE provider_product_drafts SET status = 'draft' "
        "WHERE status NOT IN ('draft', 'ready', 'published')"
    )
    op.execute(
        "UPDATE provider_product_drafts SET validation_status = 'validated' "
        "WHERE validation_status = 'valid'"
    )
    op.execute(
        "UPDATE provider_product_drafts SET validation_status = 'pending' "
        "WHERE validation_status NOT IN ('pending', 'validated')"
    )
    op.execute(
        "UPDATE provider_product_drafts SET publishing_status = 'failed' "
        "WHERE publishing_status NOT IN "
        "('not_started', 'queued', 'publishing', 'succeeded', 'failed')"
    )
    op.execute(
        "UPDATE provider_product_drafts SET revision = 1 WHERE revision < 1"
    )
    op.execute(
        "UPDATE ai_generations SET status = 'failed' "
        "WHERE status NOT IN ('pending', 'completed', 'failed', 'accepted')"
    )
    op.execute(
        "UPDATE ai_generations SET source_product_revision = 1 "
        "WHERE source_product_revision < 1"
    )
    op.execute("UPDATE design_assets SET size_bytes = 0 WHERE size_bytes < 0")
    op.execute("UPDATE mockups SET size_bytes = 0 WHERE size_bytes < 0")
    op.execute("UPDATE mockups SET position = 0 WHERE position < 0")
    op.execute("UPDATE publishing_jobs SET retry_count = 0 WHERE retry_count < 0")


def _add_organization_foreign_keys() -> None:
    for table_name in ORG_OWNED_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_foreign_key(
                f"fk_{table_name}_organization",
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="CASCADE",
            )


def _add_parent_keys_and_checks() -> None:
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.String(length=128),
            nullable=False,
        )
        batch_op.create_unique_constraint("uq_membership_user", ["user_id"])
        batch_op.create_check_constraint(
            "ck_memberships_role", "role IN ('admin', 'member')"
        )

    with op.batch_alter_table("organization_join_requests") as batch_op:
        batch_op.create_check_constraint(
            "ck_organization_join_requests_status",
            "status IN ('pending', 'approved', 'rejected')",
        )

    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_provider_store_connections_org_id", ["organization_id", "id"]
        )
        batch_op.create_check_constraint(
            "ck_provider_store_connections_status",
            "status IN ('connected', 'disconnected')",
        )

    with op.batch_alter_table("product_blueprints") as batch_op:
        batch_op.create_unique_constraint(
            "uq_product_blueprints_org_id", ["organization_id", "id"]
        )
        batch_op.create_check_constraint(
            "ck_product_blueprints_status",
            "status IN ('draft', 'active', 'archived')",
        )

    with op.batch_alter_table("design_assets") as batch_op:
        batch_op.create_unique_constraint(
            "uq_design_assets_org_id", ["organization_id", "id"]
        )
        batch_op.create_check_constraint(
            "ck_design_assets_size_nonnegative", "size_bytes >= 0"
        )

    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.create_unique_constraint(
            "uq_provider_product_drafts_org_id", ["organization_id", "id"]
        )
        batch_op.create_check_constraint(
            "ck_provider_product_drafts_status",
            "status IN ('draft', 'ready', 'published')",
        )
        batch_op.create_check_constraint(
            "ck_provider_product_drafts_validation_status",
            "validation_status IN ('pending', 'validated')",
        )
        batch_op.create_check_constraint(
            "ck_provider_product_drafts_publishing_status",
            "publishing_status IN "
            "('not_started', 'queued', 'publishing', 'succeeded', 'failed')",
        )
        batch_op.create_check_constraint(
            "ck_provider_product_drafts_revision_positive", "revision >= 1"
        )

    with op.batch_alter_table("ai_generations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_ai_generations_org_draft_id",
            ["organization_id", "provider_product_draft_id", "id"],
        )
        batch_op.create_foreign_key(
            "fk_ai_generations_accepted_by_user",
            "users",
            ["accepted_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_ai_generations_status",
            "status IN ('pending', 'completed', 'failed', 'accepted')",
        )
        batch_op.create_check_constraint(
            "ck_ai_generations_source_revision_positive",
            "source_product_revision >= 1",
        )

    with op.batch_alter_table("mockups") as batch_op:
        batch_op.create_check_constraint(
            "ck_mockups_size_nonnegative", "size_bytes >= 0"
        )
        batch_op.create_check_constraint(
            "ck_mockups_position_nonnegative", "position >= 0"
        )

    with op.batch_alter_table("pod_products") as batch_op:
        batch_op.create_unique_constraint(
            "uq_pod_products_org_id", ["organization_id", "id"]
        )

    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.create_check_constraint(
            "ck_publishing_jobs_retry_count_nonnegative", "retry_count >= 0"
        )

    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.create_unique_constraint(
            "uq_sync_jobs_org_id", ["organization_id", "id"]
        )


def _add_composite_tenant_foreign_keys() -> None:
    constraints = (
        (
            "product_blueprints",
            "fk_product_blueprints_org_store",
            "provider_store_connections",
            ["organization_id", "provider_store_connection_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "provider_product_drafts",
            "fk_provider_product_drafts_org_blueprint",
            "product_blueprints",
            ["organization_id", "blueprint_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "provider_product_drafts",
            "fk_provider_product_drafts_org_store",
            "provider_store_connections",
            ["organization_id", "provider_store_connection_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "provider_product_drafts",
            "fk_provider_product_drafts_org_design_asset",
            "design_assets",
            ["organization_id", "design_asset_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "ai_generations",
            "fk_ai_generations_org_draft",
            "provider_product_drafts",
            ["organization_id", "provider_product_draft_id"],
            ["organization_id", "id"],
            "CASCADE",
        ),
        (
            "ai_generations",
            "fk_ai_generations_org_store",
            "provider_store_connections",
            ["organization_id", "provider_store_connection_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "mockups",
            "fk_mockups_org_draft",
            "provider_product_drafts",
            ["organization_id", "provider_product_draft_id"],
            ["organization_id", "id"],
            "CASCADE",
        ),
        (
            "pod_products",
            "fk_pod_products_org_draft",
            "provider_product_drafts",
            ["organization_id", "provider_product_draft_id"],
            ["organization_id", "id"],
            "CASCADE",
        ),
        (
            "pod_products",
            "fk_pod_products_org_store",
            "provider_store_connections",
            ["organization_id", "provider_store_connection_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "publishing_jobs",
            "fk_publishing_jobs_org_blueprint",
            "product_blueprints",
            ["organization_id", "blueprint_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "publishing_jobs",
            "fk_publishing_jobs_org_draft",
            "provider_product_drafts",
            ["organization_id", "provider_product_draft_id"],
            ["organization_id", "id"],
            "CASCADE",
        ),
        (
            "publishing_jobs",
            "fk_publishing_jobs_org_pod_product",
            "pod_products",
            ["organization_id", "pod_product_id"],
            ["organization_id", "id"],
            None,
        ),
        (
            "publishing_jobs",
            "fk_publishing_jobs_org_store",
            "provider_store_connections",
            ["organization_id", "provider_store_connection_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "publishing_jobs",
            "fk_publishing_jobs_org_sync_job",
            "sync_jobs",
            ["organization_id", "sync_job_id"],
            ["organization_id", "id"],
            "CASCADE",
        ),
        (
            "orders",
            "fk_orders_org_store",
            "provider_store_connections",
            ["organization_id", "provider_store_connection_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
        (
            "sync_events",
            "fk_sync_events_org_sync_job",
            "sync_jobs",
            ["organization_id", "sync_job_id"],
            ["organization_id", "id"],
            "CASCADE",
        ),
        (
            "sync_events",
            "fk_sync_events_org_store",
            "provider_store_connections",
            ["organization_id", "provider_store_connection_id"],
            ["organization_id", "id"],
            "RESTRICT",
        ),
    )
    for table, name, parent, local_columns, remote_columns, ondelete in constraints:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(
                name,
                parent,
                local_columns,
                remote_columns,
                ondelete=ondelete,
            )

    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.create_foreign_key(
            "fk_provider_product_drafts_org_last_ai_generation",
            "ai_generations",
            ["organization_id", "id", "last_ai_generation_id"],
            ["organization_id", "provider_product_draft_id", "id"],
        )


def _add_client_rejection_policies() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in CLIENT_DENY_TABLES:
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"DROP POLICY IF EXISTS deny_client_access ON public.{table_name}"
        )
        op.execute(
            f"CREATE POLICY deny_client_access ON public.{table_name} "
            "FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
        )


def upgrade() -> None:
    _assert_clean_legacy_tenant_data()
    _normalize_lifecycle_values()
    _add_parent_keys_and_checks()
    _add_organization_foreign_keys()
    _add_composite_tenant_foreign_keys()
    _add_client_rejection_policies()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table_name in CLIENT_DENY_TABLES:
            op.execute(
                f"DROP POLICY IF EXISTS deny_client_access ON public.{table_name}"
            )

    composite_constraints = (
        ("provider_product_drafts", "fk_provider_product_drafts_org_last_ai_generation"),
        ("sync_events", "fk_sync_events_org_store"),
        ("sync_events", "fk_sync_events_org_sync_job"),
        ("orders", "fk_orders_org_store"),
        ("publishing_jobs", "fk_publishing_jobs_org_sync_job"),
        ("publishing_jobs", "fk_publishing_jobs_org_store"),
        ("publishing_jobs", "fk_publishing_jobs_org_pod_product"),
        ("publishing_jobs", "fk_publishing_jobs_org_draft"),
        ("publishing_jobs", "fk_publishing_jobs_org_blueprint"),
        ("pod_products", "fk_pod_products_org_store"),
        ("pod_products", "fk_pod_products_org_draft"),
        ("mockups", "fk_mockups_org_draft"),
        ("ai_generations", "fk_ai_generations_org_store"),
        ("ai_generations", "fk_ai_generations_org_draft"),
        ("provider_product_drafts", "fk_provider_product_drafts_org_design_asset"),
        ("provider_product_drafts", "fk_provider_product_drafts_org_store"),
        ("provider_product_drafts", "fk_provider_product_drafts_org_blueprint"),
        ("product_blueprints", "fk_product_blueprints_org_store"),
    )
    for table_name, constraint_name in composite_constraints:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")

    for table_name in reversed(ORG_OWNED_TABLES):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(
                f"fk_{table_name}_organization", type_="foreignkey"
            )

    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.drop_constraint("uq_sync_jobs_org_id", type_="unique")

    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.drop_constraint(
            "ck_publishing_jobs_retry_count_nonnegative", type_="check"
        )

    with op.batch_alter_table("pod_products") as batch_op:
        batch_op.drop_constraint("uq_pod_products_org_id", type_="unique")

    with op.batch_alter_table("mockups") as batch_op:
        batch_op.drop_constraint("ck_mockups_position_nonnegative", type_="check")
        batch_op.drop_constraint("ck_mockups_size_nonnegative", type_="check")

    with op.batch_alter_table("ai_generations") as batch_op:
        batch_op.drop_constraint(
            "ck_ai_generations_source_revision_positive", type_="check"
        )
        batch_op.drop_constraint("ck_ai_generations_status", type_="check")
        batch_op.drop_constraint(
            "fk_ai_generations_accepted_by_user", type_="foreignkey"
        )
        batch_op.drop_constraint("uq_ai_generations_org_draft_id", type_="unique")

    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_product_drafts_revision_positive", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_product_drafts_publishing_status", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_product_drafts_validation_status", type_="check"
        )
        batch_op.drop_constraint("ck_provider_product_drafts_status", type_="check")
        batch_op.drop_constraint("uq_provider_product_drafts_org_id", type_="unique")

    with op.batch_alter_table("design_assets") as batch_op:
        batch_op.drop_constraint("ck_design_assets_size_nonnegative", type_="check")
        batch_op.drop_constraint("uq_design_assets_org_id", type_="unique")

    with op.batch_alter_table("product_blueprints") as batch_op:
        batch_op.drop_constraint("ck_product_blueprints_status", type_="check")
        batch_op.drop_constraint("uq_product_blueprints_org_id", type_="unique")

    with op.batch_alter_table("provider_store_connections") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_store_connections_status", type_="check"
        )
        batch_op.drop_constraint(
            "uq_provider_store_connections_org_id", type_="unique"
        )
        batch_op.drop_column("deleted_at")

    with op.batch_alter_table("organization_join_requests") as batch_op:
        batch_op.drop_constraint(
            "ck_organization_join_requests_status", type_="check"
        )

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("ck_memberships_role", type_="check")
        batch_op.drop_constraint("uq_membership_user", type_="unique")
        batch_op.alter_column(
            "role",
            existing_type=sa.String(length=128),
            nullable=True,
        )
