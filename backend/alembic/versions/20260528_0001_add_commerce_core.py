"""add commerce core

Revision ID: 20260528_0001
Revises: None
Create Date: 2026-05-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260528_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("key_name", sa.String(length=128), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "provider", "key_name", name="uq_provider_credential_org_provider_key"),
    )
    op.create_index("ix_provider_credentials_organization_id", "provider_credentials", ["organization_id"])
    op.create_index("ix_provider_credentials_provider", "provider_credentials", ["provider"])

    op.create_table(
        "provider_store_connections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_store_id", sa.String(length=255), nullable=False),
        sa.Column("storefront_type", sa.String(length=32), nullable=False),
        sa.Column("storefront_display_name", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_data_json", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "provider_store_id",
            name="uq_provider_store_connection_org_provider_store",
        ),
    )
    op.create_index("ix_provider_store_connections_organization_id", "provider_store_connections", ["organization_id"])
    op.create_index("ix_provider_store_connections_provider", "provider_store_connections", ["provider"])

    op.create_table(
        "product_blueprints",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_store_connection_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=False),
        sa.Column("reference_value", sa.Text(), nullable=False),
        sa.Column("provider_resource_id", sa.String(length=255), nullable=True),
        sa.Column("provider_display_name", sa.String(length=255), nullable=True),
        sa.Column("product_code", sa.String(length=128), nullable=True),
        sa.Column("placement_config_json", sa.JSON(), nullable=True),
        sa.Column("provider_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("product_type", sa.String(length=255), nullable=True),
        sa.Column("configuration_summary", sa.Text(), nullable=True),
        sa.Column("variant_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_cost_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("base_title", sa.String(length=255), nullable=True),
        sa.Column("base_description", sa.Text(), nullable=True),
        sa.Column("base_tags_json", sa.JSON(), nullable=True),
        sa.Column("basic_design_info_json", sa.JSON(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_store_connection_id"], ["provider_store_connections.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_product_blueprints_organization_id", "product_blueprints", ["organization_id"])
    op.create_index("ix_product_blueprints_provider", "product_blueprints", ["provider"])
    op.create_index("ix_product_blueprints_provider_store_connection_id", "product_blueprints", ["provider_store_connection_id"])

    op.create_table(
        "design_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_design_assets_organization_id", "design_assets", ["organization_id"])

    op.create_table(
        "provider_product_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("blueprint_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_store_connection_id", sa.String(length=36), nullable=False),
        sa.Column("design_asset_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("publishing_status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("retail_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("cost_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("margin_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("provider_product_id", sa.String(length=255), nullable=True),
        sa.Column("external_listing_id", sa.String(length=255), nullable=True),
        sa.Column("provider_product_url", sa.Text(), nullable=True),
        sa.Column("provider_fulfillment_url", sa.Text(), nullable=True),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("last_provider_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["blueprint_id"], ["product_blueprints.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_store_connection_id"], ["provider_store_connections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["design_asset_id"], ["design_assets.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_provider_product_drafts_organization_id", "provider_product_drafts", ["organization_id"])
    op.create_index("ix_provider_product_drafts_blueprint_id", "provider_product_drafts", ["blueprint_id"])
    op.create_index("ix_provider_product_drafts_provider", "provider_product_drafts", ["provider"])
    op.create_index("ix_provider_product_drafts_provider_store_connection_id", "provider_product_drafts", ["provider_store_connection_id"])
    op.create_index("ix_provider_product_drafts_design_asset_id", "provider_product_drafts", ["design_asset_id"])
    op.create_index("ix_provider_product_drafts_org_status", "provider_product_drafts", ["organization_id", "status"])

    op.create_table(
        "mockups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider_product_draft_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_product_draft_id"], ["provider_product_drafts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_mockups_organization_id", "mockups", ["organization_id"])
    op.create_index("ix_mockups_provider_product_draft_id", "mockups", ["provider_product_draft_id"])

    op.create_table(
        "pod_products",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("provider_product_draft_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_store_connection_id", sa.String(length=36), nullable=False),
        sa.Column("provider_product_id", sa.String(length=255), nullable=False),
        sa.Column("external_listing_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_product_url", sa.Text(), nullable=True),
        sa.Column("provider_fulfillment_url", sa.Text(), nullable=True),
        sa.Column("raw_provider_payload_json", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_product_draft_id"], ["provider_product_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_store_connection_id"], ["provider_store_connections.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("provider_product_draft_id", name="uq_pod_product_draft"),
    )
    op.create_index("ix_pod_products_organization_id", "pod_products", ["organization_id"])
    op.create_index("ix_pod_products_provider_product_draft_id", "pod_products", ["provider_product_draft_id"])
    op.create_index("ix_pod_products_provider", "pod_products", ["provider"])
    op.create_index("ix_pod_products_provider_store_connection_id", "pod_products", ["provider_store_connection_id"])

    op.create_table(
        "publishing_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("blueprint_id", sa.String(length=36), nullable=False),
        sa.Column("provider_product_draft_id", sa.String(length=36), nullable=False),
        sa.Column("pod_product_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_store_connection_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["blueprint_id"], ["product_blueprints.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_product_draft_id"], ["provider_product_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pod_product_id"], ["pod_products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["provider_store_connection_id"], ["provider_store_connections.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_publishing_jobs_organization_id", "publishing_jobs", ["organization_id"])
    op.create_index("ix_publishing_jobs_blueprint_id", "publishing_jobs", ["blueprint_id"])
    op.create_index("ix_publishing_jobs_provider_product_draft_id", "publishing_jobs", ["provider_product_draft_id"])
    op.create_index("ix_publishing_jobs_pod_product_id", "publishing_jobs", ["pod_product_id"])
    op.create_index("ix_publishing_jobs_provider", "publishing_jobs", ["provider"])
    op.create_index("ix_publishing_jobs_provider_store_connection_id", "publishing_jobs", ["provider_store_connection_id"])
    op.create_index("ix_publishing_jobs_org_status", "publishing_jobs", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_publishing_jobs_org_status", table_name="publishing_jobs")
    op.drop_index("ix_publishing_jobs_provider_store_connection_id", table_name="publishing_jobs")
    op.drop_index("ix_publishing_jobs_provider", table_name="publishing_jobs")
    op.drop_index("ix_publishing_jobs_pod_product_id", table_name="publishing_jobs")
    op.drop_index("ix_publishing_jobs_provider_product_draft_id", table_name="publishing_jobs")
    op.drop_index("ix_publishing_jobs_blueprint_id", table_name="publishing_jobs")
    op.drop_index("ix_publishing_jobs_organization_id", table_name="publishing_jobs")
    op.drop_table("publishing_jobs")

    op.drop_index("ix_pod_products_provider_store_connection_id", table_name="pod_products")
    op.drop_index("ix_pod_products_provider", table_name="pod_products")
    op.drop_index("ix_pod_products_provider_product_draft_id", table_name="pod_products")
    op.drop_index("ix_pod_products_organization_id", table_name="pod_products")
    op.drop_table("pod_products")

    op.drop_index("ix_mockups_provider_product_draft_id", table_name="mockups")
    op.drop_index("ix_mockups_organization_id", table_name="mockups")
    op.drop_table("mockups")

    op.drop_index("ix_provider_product_drafts_org_status", table_name="provider_product_drafts")
    op.drop_index("ix_provider_product_drafts_design_asset_id", table_name="provider_product_drafts")
    op.drop_index("ix_provider_product_drafts_provider_store_connection_id", table_name="provider_product_drafts")
    op.drop_index("ix_provider_product_drafts_provider", table_name="provider_product_drafts")
    op.drop_index("ix_provider_product_drafts_blueprint_id", table_name="provider_product_drafts")
    op.drop_index("ix_provider_product_drafts_organization_id", table_name="provider_product_drafts")
    op.drop_table("provider_product_drafts")

    op.drop_index("ix_design_assets_organization_id", table_name="design_assets")
    op.drop_table("design_assets")

    op.drop_index("ix_product_blueprints_provider_store_connection_id", table_name="product_blueprints")
    op.drop_index("ix_product_blueprints_provider", table_name="product_blueprints")
    op.drop_index("ix_product_blueprints_organization_id", table_name="product_blueprints")
    op.drop_table("product_blueprints")

    op.drop_index("ix_provider_store_connections_provider", table_name="provider_store_connections")
    op.drop_index("ix_provider_store_connections_organization_id", table_name="provider_store_connections")
    op.drop_table("provider_store_connections")

    op.drop_index("ix_provider_credentials_provider", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_organization_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
