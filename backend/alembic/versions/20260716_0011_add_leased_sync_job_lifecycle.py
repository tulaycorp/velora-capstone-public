"""add leased sync job lifecycle

Revision ID: 20260716_0011
Revises: 20260714_0010
Create Date: 2026-07-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260716_0011"
down_revision = "20260714_0010"
branch_labels = None
depends_on = None


ACTIVE_STATUS_PREDICATE = "status IN ('queued', 'leased', 'running')"


def upgrade() -> None:
    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.add_column(sa.Column("scope_key", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("lease_owner", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=True, server_default="0"))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), nullable=True, server_default="3"))
        batch_op.add_column(
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.add_column(sa.Column("result_json", sa.JSON(), nullable=True))

    op.execute(
        "UPDATE sync_jobs "
        "SET scope_key = 'legacy:' || id, "
        "status = 'leased', "
        "lease_owner = 'legacy-migration', "
        "lease_expires_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP), "
        "heartbeat_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP), "
        "attempt_count = 1, max_attempts = 1, "
        "available_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
        "WHERE status = 'running'"
    )
    op.execute(
        "UPDATE sync_jobs "
        "SET scope_key = 'legacy:' || id, "
        "status = 'failed', "
        "completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), "
        "error_message = COALESCE(error_message, 'Queued job retired during leased lifecycle migration.'), "
        "available_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
        "WHERE status = 'pending'"
    )
    op.execute(
        "UPDATE sync_jobs "
        "SET scope_key = COALESCE(scope_key, 'organization'), "
        "available_at = COALESCE(available_at, created_at, CURRENT_TIMESTAMP), "
        "attempt_count = COALESCE(attempt_count, 0), "
        "max_attempts = COALESCE(max_attempts, 3)"
    )
    op.execute(
        "UPDATE sync_jobs "
        "SET status = 'failed', "
        "completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), "
        "error_message = COALESCE(error_message, 'Unsupported legacy status retired during migration.') "
        "WHERE status NOT IN ('queued', 'leased', 'running', 'completed', 'partial', 'failed', 'cancelled')"
    )

    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.alter_column("scope_key", nullable=False)
        batch_op.alter_column("attempt_count", nullable=False, server_default=None)
        batch_op.alter_column("max_attempts", nullable=False, server_default=None)
        batch_op.alter_column("available_at", nullable=False, server_default=None)
        batch_op.create_check_constraint(
            "ck_sync_jobs_status",
            "status IN ('queued', 'leased', 'running', 'completed', 'partial', 'failed', 'cancelled')",
        )
        batch_op.create_check_constraint("ck_sync_jobs_attempt_count_nonnegative", "attempt_count >= 0")
        batch_op.create_check_constraint("ck_sync_jobs_max_attempts_positive", "max_attempts >= 1")
        batch_op.create_check_constraint("ck_sync_jobs_max_attempts_bounded", "max_attempts <= 10")
        batch_op.create_check_constraint(
            "ck_sync_jobs_attempt_count_within_limit",
            "attempt_count <= max_attempts",
        )
        batch_op.create_check_constraint(
            "ck_sync_jobs_queued_retryable",
            "status != 'queued' OR attempt_count < max_attempts",
        )
        batch_op.create_check_constraint(
            "ck_sync_jobs_lease_fields",
            "(status IN ('leased', 'running') AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL) "
            "OR (status NOT IN ('leased', 'running') AND lease_owner IS NULL AND lease_expires_at IS NULL)",
        )

    op.create_index(
        "uq_sync_jobs_active_scope",
        "sync_jobs",
        ["organization_id", "job_type", "scope_key"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATUS_PREDICATE),
        sqlite_where=sa.text(ACTIVE_STATUS_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_sync_jobs_active_scope", table_name="sync_jobs")
    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.drop_constraint("ck_sync_jobs_lease_fields", type_="check")
        batch_op.drop_constraint("ck_sync_jobs_queued_retryable", type_="check")
        batch_op.drop_constraint("ck_sync_jobs_attempt_count_within_limit", type_="check")
        batch_op.drop_constraint("ck_sync_jobs_max_attempts_bounded", type_="check")
        batch_op.drop_constraint("ck_sync_jobs_max_attempts_positive", type_="check")
        batch_op.drop_constraint("ck_sync_jobs_attempt_count_nonnegative", type_="check")
        batch_op.drop_constraint("ck_sync_jobs_status", type_="check")

    op.execute("UPDATE sync_jobs SET status = 'pending' WHERE status = 'queued'")
    op.execute("UPDATE sync_jobs SET status = 'running' WHERE status = 'leased'")
    op.execute("UPDATE sync_jobs SET status = 'completed' WHERE status = 'partial'")
    op.execute("UPDATE sync_jobs SET status = 'failed' WHERE status = 'cancelled'")
    with op.batch_alter_table("sync_jobs") as batch_op:
        batch_op.drop_column("result_json")
        batch_op.drop_column("available_at")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_owner")
        batch_op.drop_column("scope_key")
