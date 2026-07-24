"""add durable publishing outbox

Revision ID: 20260716_0013
Revises: 20260716_0012
Create Date: 2026-07-16 00:00:00.000000
"""

from __future__ import annotations

import hashlib
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260716_0013"
down_revision = "20260716_0012"
branch_labels = None
depends_on = None


ACTIVE_PUBLISH_STATUS_PREDICATE = "status IN ('queued', 'leased', 'running')"


def _retire_legacy_jobs() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    publishing_jobs = sa.Table("publishing_jobs", metadata, autoload_with=bind)
    sync_jobs = sa.Table("sync_jobs", metadata, autoload_with=bind)
    drafts = sa.Table("provider_product_drafts", metadata, autoload_with=bind)

    rows = bind.execute(
        sa.select(
            publishing_jobs,
            drafts.c.revision.label("draft_revision"),
            drafts.c.provider_product_id.label("draft_provider_product_id"),
        ).select_from(
            publishing_jobs.join(
                drafts,
                publishing_jobs.c.provider_product_draft_id == drafts.c.id,
            )
        )
    ).mappings().all()
    for row in rows:
        legacy_status = str(row["status"] or "failed").lower()
        if legacy_status == "succeeded":
            publishing_status = "succeeded"
            sync_status = "completed"
        elif legacy_status == "cancelled":
            publishing_status = "cancelled"
            sync_status = "cancelled"
        else:
            publishing_status = "failed"
            sync_status = "failed"

        sync_job_id = str(uuid.uuid4())
        attempt_count = min(max(int(row["retry_count"] or 0), 1), 10)
        max_attempts = max(attempt_count, 3)
        completed_at = row["completed_at"] or row["updated_at"] or row["created_at"]
        bind.execute(
            sync_jobs.insert().values(
                id=sync_job_id,
                organization_id=row["organization_id"],
                provider=row["provider"],
                job_type="product_publish",
                scope_key=f"legacy-publish:{row['id']}",
                status=sync_status,
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=None,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
                available_at=row["created_at"],
                result_json=None,
                started_at=row["started_at"],
                completed_at=completed_at,
                error_message=row["error_message"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
        provider_product_id = row["draft_provider_product_id"]
        operation = "update" if provider_product_id else "create"
        idempotency_key = hashlib.sha256(
            f"legacy|{row['organization_id']}|{row['id']}".encode("utf-8")
        ).hexdigest()
        values = {
            "sync_job_id": sync_job_id,
            "operation": operation,
            "product_revision": max(int(row["draft_revision"] or 1), 1),
            "idempotency_key": idempotency_key,
            "submitted_snapshot_json": {
                "legacy": True,
                "retired_during_migration": publishing_status == "failed" and legacy_status not in {"failed"},
            },
            "provider_product_id": provider_product_id,
            "status": publishing_status,
        }
        if publishing_status == "failed" and legacy_status not in {"failed"}:
            values["error_message"] = "Legacy active publishing job retired during durable outbox migration."
            values["completed_at"] = completed_at
        bind.execute(
            publishing_jobs.update().where(publishing_jobs.c.id == row["id"]).values(**values)
        )


def upgrade() -> None:
    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.add_column(sa.Column("sync_job_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("operation", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("product_revision", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("submitted_snapshot_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("provider_product_id", sa.String(length=255), nullable=True))

    _retire_legacy_jobs()

    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.alter_column("sync_job_id", nullable=False)
        batch_op.alter_column("operation", nullable=False)
        batch_op.alter_column("product_revision", nullable=False)
        batch_op.alter_column("idempotency_key", nullable=False)
        batch_op.alter_column("submitted_snapshot_json", nullable=False)
        batch_op.create_foreign_key(
            "fk_publishing_job_sync_job",
            "sync_jobs",
            ["sync_job_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint("uq_publishing_job_sync_job", ["sync_job_id"])
        batch_op.create_unique_constraint("uq_publishing_job_idempotency_key", ["idempotency_key"])
        batch_op.create_check_constraint(
            "ck_publishing_jobs_operation",
            "operation IN ('create', 'update')",
        )
        batch_op.create_check_constraint(
            "ck_publishing_jobs_product_revision_positive",
            "product_revision >= 1",
        )
        batch_op.create_check_constraint(
            "ck_publishing_jobs_status",
            "status IN ('queued', 'leased', 'running', 'succeeded', 'failed', 'cancelled')",
        )
        batch_op.create_index("ix_publishing_jobs_sync_job_id", ["sync_job_id"])

    op.create_index(
        "uq_publishing_jobs_active_scope",
        "publishing_jobs",
        [
            "organization_id",
            "provider_product_draft_id",
            "provider_store_connection_id",
        ],
        unique=True,
        postgresql_where=sa.text(ACTIVE_PUBLISH_STATUS_PREDICATE),
        sqlite_where=sa.text(ACTIVE_PUBLISH_STATUS_PREDICATE),
    )

    op.create_table(
        "publishing_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("publishing_job_id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["publishing_job_id"],
            ["publishing_jobs.id"],
            name="fk_publishing_outbox_job",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("publishing_job_id", name="uq_publishing_outbox_job"),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatching', 'dispatched')",
            name="ck_publishing_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_publishing_outbox_attempt_count_nonnegative",
        ),
    )
    op.create_index(
        "ix_publishing_outbox_publishing_job_id",
        "publishing_outbox",
        ["publishing_job_id"],
    )
    op.create_index(
        "ix_publishing_outbox_status_available",
        "publishing_outbox",
        ["status", "available_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.publishing_outbox ENABLE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS deny_client_access ON public.publishing_outbox")
        op.execute(
            "CREATE POLICY deny_client_access ON public.publishing_outbox "
            "FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS deny_client_access ON public.publishing_outbox")

    op.drop_index("ix_publishing_outbox_status_available", table_name="publishing_outbox")
    op.drop_index("ix_publishing_outbox_publishing_job_id", table_name="publishing_outbox")
    op.drop_table("publishing_outbox")
    op.drop_index("uq_publishing_jobs_active_scope", table_name="publishing_jobs")

    with op.batch_alter_table("publishing_jobs") as batch_op:
        batch_op.drop_index("ix_publishing_jobs_sync_job_id")
        batch_op.drop_constraint("ck_publishing_jobs_status", type_="check")
        batch_op.drop_constraint("ck_publishing_jobs_product_revision_positive", type_="check")
        batch_op.drop_constraint("ck_publishing_jobs_operation", type_="check")
        batch_op.drop_constraint("uq_publishing_job_idempotency_key", type_="unique")
        batch_op.drop_constraint("uq_publishing_job_sync_job", type_="unique")
        batch_op.drop_constraint("fk_publishing_job_sync_job", type_="foreignkey")
        batch_op.drop_column("provider_product_id")
        batch_op.drop_column("submitted_snapshot_json")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("product_revision")
        batch_op.drop_column("operation")
        batch_op.drop_column("sync_job_id")

    op.execute("DELETE FROM sync_jobs WHERE job_type = 'product_publish'")
