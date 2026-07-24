"""add AI listing-generation workflow

Revision ID: 20260714_0010
Revises: 20260714_0009
Create Date: 2026-07-14 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260714_0010"
down_revision = "20260714_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=True, server_default="1"))
        batch_op.add_column(sa.Column("design_description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("seo_title", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("seo_description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("seo_keywords_json", sa.JSON(), nullable=True))
    op.execute("UPDATE provider_product_drafts SET revision = 1 WHERE revision IS NULL")
    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.alter_column("revision", nullable=False, server_default="1")

    op.create_table(
        "ai_generations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider_product_draft_id", sa.String(length=36), sa.ForeignKey("provider_product_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_store_connection_id", sa.String(length=36), sa.ForeignKey("provider_store_connections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_request_id", sa.String(length=64), nullable=False),
        sa.Column("source_product_revision", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("output_json", sa.JSON(), nullable=True), sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True), sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True), sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("accepted_output_json", sa.JSON(), nullable=True), sa.Column("accepted_fields_json", sa.JSON(), nullable=True),
        sa.Column("accepted_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "client_request_id", name="uq_ai_generation_org_client_request"),
    )
    op.create_index("ix_ai_generations_organization_id", "ai_generations", ["organization_id"])
    op.create_index("ix_ai_generations_product_created", "ai_generations", ["provider_product_draft_id", "created_at"])
    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.add_column(sa.Column("last_ai_generation_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_product_draft_last_ai_generation", "ai_generations", ["last_ai_generation_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.drop_constraint("fk_product_draft_last_ai_generation", type_="foreignkey")
        batch_op.drop_column("last_ai_generation_id")
    op.drop_index("ix_ai_generations_product_created", table_name="ai_generations")
    op.drop_index("ix_ai_generations_organization_id", table_name="ai_generations")
    op.drop_table("ai_generations")
    with op.batch_alter_table("provider_product_drafts") as batch_op:
        batch_op.drop_column("seo_keywords_json")
        batch_op.drop_column("seo_description")
        batch_op.drop_column("seo_title")
        batch_op.drop_column("design_description")
        batch_op.drop_column("revision")
