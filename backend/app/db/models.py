import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


json_type = JSON().with_variant(JSONB, "postgresql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=True, unique=True)
    created_by_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    join_code: Mapped[str] = mapped_column(String(32), nullable=True, unique=True)
    reporting_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="PHP")
    reporting_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Manila")

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    join_requests: Mapped[list["OrganizationJoinRequest"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by_user_id])


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str] = mapped_column(Text, nullable=True)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    requested_join_records: Mapped[list["OrganizationJoinRequest"]] = relationship(
        foreign_keys="OrganizationJoinRequest.requested_by_user_id",
        back_populates="requested_by_user",
        cascade="all, delete-orphan",
    )
    reviewed_join_records: Mapped[list["OrganizationJoinRequest"]] = relationship(
        foreign_keys="OrganizationJoinRequest.reviewed_by_user_id",
        back_populates="reviewed_by_user",
    )


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_organization_user"),
        UniqueConstraint("user_id", name="uq_membership_user"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_memberships_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(128), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")


class OrganizationJoinRequest(Base, TimestampMixin):
    __tablename__ = "organization_join_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_organization_join_requests_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    reviewed_by_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="join_requests")
    requested_by_user: Mapped["User"] = relationship(
        foreign_keys=[requested_by_user_id],
        back_populates="requested_join_records",
    )
    reviewed_by_user: Mapped["User"] = relationship(
        foreign_keys=[reviewed_by_user_id],
        back_populates="reviewed_join_records",
    )


class ProviderCredential(Base, TimestampMixin):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "key_name",
            name="uq_provider_credential_org_provider_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    key_name: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")


class OAuthRequestState(Base, TimestampMixin):
    __tablename__ = "oauth_request_states"
    __table_args__ = (
        UniqueConstraint("provider", "state_digest", name="uq_oauth_request_state_provider_digest"),
        Index("ix_oauth_request_states_org_provider", "organization_id", "provider"),
        Index("ix_oauth_request_states_actor_provider", "actor_id", "provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    state_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderStoreConnection(Base, TimestampMixin):
    __tablename__ = "provider_store_connections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "credential_key",
            "provider_store_id",
            name="uq_provider_store_connection_org_provider_store",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_provider_store_connections_org_id",
        ),
        CheckConstraint(
            "status IN ('connected', 'disconnected')",
            name="ck_provider_store_connections_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    credential_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="default")
    provider_store_id: Mapped[str] = mapped_column(String(255), nullable=False)
    storefront_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    storefront_display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    etsy_shop_id: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy")
    raw_data_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    order_sync_cursor_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    order_sync_watermark_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    order_sync_last_success_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    blueprints: Mapped[list["ProductBlueprint"]] = relationship(
        back_populates="provider_store_connection",
        foreign_keys="ProductBlueprint.provider_store_connection_id",
    )
    drafts: Mapped[list["ProviderProductDraft"]] = relationship(
        back_populates="provider_store_connection",
        foreign_keys="ProviderProductDraft.provider_store_connection_id",
    )


class ProductBlueprint(Base, TimestampMixin):
    __tablename__ = "product_blueprints"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_product_blueprints_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_product_blueprints_org_store",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_product_blueprints_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    provider_store_connection_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_value: Mapped[str] = mapped_column(Text, nullable=False)
    provider_resource_id: Mapped[str] = mapped_column(String(255), nullable=True)
    provider_display_name: Mapped[str] = mapped_column(String(255), nullable=True)
    product_code: Mapped[str] = mapped_column(String(128), nullable=True)
    placement_config_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    provider_snapshot_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    product_type: Mapped[str] = mapped_column(String(255), nullable=True)
    configuration_summary: Mapped[str] = mapped_column(Text, nullable=True)
    variant_count: Mapped[int] = mapped_column(nullable=False, default=0)
    base_cost_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=True)
    base_title: Mapped[str] = mapped_column(String(255), nullable=True)
    base_description: Mapped[str] = mapped_column(Text, nullable=True)
    base_tags_json: Mapped[list[str]] = mapped_column(json_type, nullable=True)
    basic_design_info_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    provider_store_connection: Mapped["ProviderStoreConnection"] = relationship(
        back_populates="blueprints",
        foreign_keys=[provider_store_connection_id],
    )
    drafts: Mapped[list["ProviderProductDraft"]] = relationship(
        back_populates="blueprint",
        foreign_keys="ProviderProductDraft.blueprint_id",
    )


class DesignAsset(Base, TimestampMixin):
    __tablename__ = "design_assets"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_design_assets_org_id"),
        CheckConstraint("size_bytes >= 0", name="ck_design_assets_size_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    public_url: Mapped[str] = mapped_column(Text, nullable=True)
    checksum: Mapped[str] = mapped_column(String(128), nullable=True)

    drafts: Mapped[list["ProviderProductDraft"]] = relationship(
        back_populates="design_asset",
        foreign_keys="ProviderProductDraft.design_asset_id",
    )


class ProviderProductDraft(Base, TimestampMixin):
    __tablename__ = "provider_product_drafts"
    __table_args__ = (
        Index("ix_provider_product_drafts_org_status", "organization_id", "status"),
        UniqueConstraint("organization_id", "id", name="uq_provider_product_drafts_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "blueprint_id"],
            ["product_blueprints.organization_id", "product_blueprints.id"],
            name="fk_provider_product_drafts_org_blueprint",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_provider_product_drafts_org_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "design_asset_id"],
            ["design_assets.organization_id", "design_assets.id"],
            name="fk_provider_product_drafts_org_design_asset",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "id", "last_ai_generation_id"],
            [
                "ai_generations.organization_id",
                "ai_generations.provider_product_draft_id",
                "ai_generations.id",
            ],
            name="fk_provider_product_drafts_org_last_ai_generation",
            use_alter=True,
        ),
        CheckConstraint(
            "status IN ('draft', 'ready', 'published')",
            name="ck_provider_product_drafts_status",
        ),
        CheckConstraint(
            "validation_status IN ('pending', 'validated')",
            name="ck_provider_product_drafts_validation_status",
        ),
        CheckConstraint(
            "publishing_status IN ('not_started', 'queued', 'publishing', 'succeeded', 'failed')",
            name="ck_provider_product_drafts_publishing_status",
        ),
        CheckConstraint("revision >= 1", name="ck_provider_product_drafts_revision_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    blueprint_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    provider_store_connection_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    design_asset_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    publishing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(json_type, nullable=True)
    retail_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    margin_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=True)
    provider_product_id: Mapped[str] = mapped_column(String(255), nullable=True)
    external_listing_id: Mapped[str] = mapped_column(String(255), nullable=True)
    provider_product_url: Mapped[str] = mapped_column(Text, nullable=True)
    provider_fulfillment_url: Mapped[str] = mapped_column(Text, nullable=True)
    provider_status: Mapped[str] = mapped_column(String(64), nullable=True)
    last_provider_sync_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(nullable=False, default=1)
    design_description: Mapped[str] = mapped_column(Text, nullable=True)
    seo_title: Mapped[str] = mapped_column(String(255), nullable=True)
    seo_description: Mapped[str] = mapped_column(Text, nullable=True)
    seo_keywords_json: Mapped[list[str]] = mapped_column(json_type, nullable=True)
    last_ai_generation_id: Mapped[str] = mapped_column(
        String(36), nullable=True
    )

    blueprint: Mapped["ProductBlueprint"] = relationship(
        back_populates="drafts",
        foreign_keys=[blueprint_id],
    )
    provider_store_connection: Mapped["ProviderStoreConnection"] = relationship(
        back_populates="drafts",
        foreign_keys=[provider_store_connection_id],
    )
    design_asset: Mapped["DesignAsset"] = relationship(
        back_populates="drafts",
        foreign_keys=[design_asset_id],
    )
    mockups: Mapped[list["Mockup"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="Mockup.provider_product_draft_id",
    )
    pod_product: Mapped["PodProduct"] = relationship(
        back_populates="draft",
        foreign_keys="PodProduct.provider_product_draft_id",
        uselist=False,
    )
    publishing_jobs: Mapped[list["PublishingJob"]] = relationship(
        back_populates="draft",
        foreign_keys="PublishingJob.provider_product_draft_id",
    )
    ai_generations: Mapped[list["AIGeneration"]] = relationship(
        back_populates="draft", foreign_keys="AIGeneration.provider_product_draft_id", cascade="all, delete-orphan"
    )
    last_ai_generation: Mapped["AIGeneration"] = relationship(
        foreign_keys=[last_ai_generation_id], post_update=True
    )


class AIGeneration(Base, TimestampMixin):
    __tablename__ = "ai_generations"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_request_id", name="uq_ai_generation_org_client_request"),
        UniqueConstraint(
            "organization_id",
            "provider_product_draft_id",
            "id",
            name="uq_ai_generations_org_draft_id",
        ),
        Index("ix_ai_generations_product_created", "provider_product_draft_id", "created_at"),
        Index(
            "ix_ai_generations_org_requester_created",
            "organization_id",
            "requested_by_user_id",
            "created_at",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_product_draft_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_ai_generations_org_draft",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_ai_generations_org_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "requested_by_user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_ai_generations_org_requester_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'accepted')",
            name="ck_ai_generations_status",
        ),
        CheckConstraint(
            "source_product_revision >= 1",
            name="ck_ai_generations_source_revision_positive",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_product_draft_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    provider_store_connection_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    client_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(String(64), nullable=True)
    source_product_revision: Mapped[int] = mapped_column(nullable=False)
    provider_key: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    output_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    warnings_json: Mapped[list[str]] = mapped_column(json_type, nullable=True)
    usage_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    provider_request_id: Mapped[str] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    accepted_output_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    accepted_fields_json: Mapped[list[str]] = mapped_column(json_type, nullable=True)
    accepted_by_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    draft: Mapped["ProviderProductDraft"] = relationship(
        back_populates="ai_generations", foreign_keys=[provider_product_draft_id]
    )


class Mockup(Base, TimestampMixin):
    __tablename__ = "mockups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "provider_product_draft_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_mockups_org_draft",
            ondelete="CASCADE",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_mockups_size_nonnegative"),
        CheckConstraint("position >= 0", name="ck_mockups_position_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_product_draft_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    public_url: Mapped[str] = mapped_column(Text, nullable=True)
    checksum: Mapped[str] = mapped_column(String(128), nullable=True)
    position: Mapped[int] = mapped_column(nullable=False, default=0)

    draft: Mapped["ProviderProductDraft"] = relationship(
        back_populates="mockups",
        foreign_keys=[provider_product_draft_id],
    )


class PodProduct(Base, TimestampMixin):
    __tablename__ = "pod_products"
    __table_args__ = (
        UniqueConstraint("provider_product_draft_id", name="uq_pod_product_draft"),
        UniqueConstraint("organization_id", "id", name="uq_pod_products_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "provider_product_draft_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_pod_products_org_draft",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_pod_products_org_store",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_product_draft_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    provider_store_connection_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    provider_product_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_listing_id: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    provider_product_url: Mapped[str] = mapped_column(Text, nullable=True)
    provider_fulfillment_url: Mapped[str] = mapped_column(Text, nullable=True)
    raw_provider_payload_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    draft: Mapped["ProviderProductDraft"] = relationship(
        back_populates="pod_product",
        foreign_keys=[provider_product_draft_id],
    )


class PublishingJob(Base, TimestampMixin):
    __tablename__ = "publishing_jobs"
    __table_args__ = (
        Index("ix_publishing_jobs_org_status", "organization_id", "status"),
        Index(
            "uq_publishing_jobs_active_scope",
            "organization_id",
            "provider_product_draft_id",
            "provider_store_connection_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'leased', 'running')"),
            sqlite_where=text("status IN ('queued', 'leased', 'running')"),
        ),
        UniqueConstraint("sync_job_id", name="uq_publishing_job_sync_job"),
        UniqueConstraint("idempotency_key", name="uq_publishing_job_idempotency_key"),
        CheckConstraint("operation IN ('create', 'update')", name="ck_publishing_jobs_operation"),
        CheckConstraint("product_revision >= 1", name="ck_publishing_jobs_product_revision_positive"),
        CheckConstraint(
            "status IN ('queued', 'leased', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_publishing_jobs_status",
        ),
        ForeignKeyConstraint(
            ["organization_id", "blueprint_id"],
            ["product_blueprints.organization_id", "product_blueprints.id"],
            name="fk_publishing_jobs_org_blueprint",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_product_draft_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_publishing_jobs_org_draft",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "pod_product_id"],
            ["pod_products.organization_id", "pod_products.id"],
            name="fk_publishing_jobs_org_pod_product",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_publishing_jobs_org_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "sync_job_id"],
            ["sync_jobs.organization_id", "sync_jobs.id"],
            name="fk_publishing_jobs_org_sync_job",
            ondelete="CASCADE",
        ),
        CheckConstraint("retry_count >= 0", name="ck_publishing_jobs_retry_count_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    blueprint_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    provider_product_draft_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    pod_product_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    provider_store_connection_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    sync_job_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    product_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_snapshot_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    provider_product_id: Mapped[str] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_result_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)

    draft: Mapped["ProviderProductDraft"] = relationship(
        back_populates="publishing_jobs",
        foreign_keys=[provider_product_draft_id],
    )
    sync_job: Mapped["SyncJob"] = relationship(foreign_keys=[sync_job_id])
    outbox: Mapped["PublishingOutbox"] = relationship(
        back_populates="publishing_job",
        cascade="all, delete-orphan",
        uselist=False,
    )


class PublishingOutbox(Base, TimestampMixin):
    __tablename__ = "publishing_outbox"
    __table_args__ = (
        Index("ix_publishing_outbox_status_available", "status", "available_at"),
        UniqueConstraint("publishing_job_id", name="uq_publishing_outbox_job"),
        CheckConstraint(
            "status IN ('pending', 'dispatching', 'dispatched')",
            name="ck_publishing_outbox_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_publishing_outbox_attempt_count_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    publishing_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("publishing_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(64), nullable=False, default="product_publish")
    payload_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    lease_owner: Mapped[str] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)

    publishing_job: Mapped["PublishingJob"] = relationship(back_populates="outbox")


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_org_provider", "organization_id", "provider"),
        UniqueConstraint("organization_id", "provider", "external_order_id", name="uq_order_org_provider_external"),
        UniqueConstraint("organization_id", "id", name="uq_orders_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_orders_org_store",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_store_connection_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    display_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    marketplace_order_id: Mapped[str] = mapped_column(String(255), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=True)
    product_summary: Mapped[str] = mapped_column(Text, nullable=True)
    fulfillment_status: Mapped[str] = mapped_column(String(64), nullable=False)
    production_status: Mapped[str] = mapped_column(String(64), nullable=True)
    financial_status: Mapped[str] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0.0)
    order_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_to_production_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    tracking_url: Mapped[str] = mapped_column(Text, nullable=True)
    tracking_code: Mapped[str] = mapped_column(String(255), nullable=True)
    destination_city: Mapped[str] = mapped_column(String(255), nullable=True)
    destination_country: Mapped[str] = mapped_column(String(128), nullable=True)
    retail_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True)
    provider_order_url: Mapped[str] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    provider_store_connection: Mapped["ProviderStoreConnection"] = relationship(
        primaryjoin="Order.provider_store_connection_id == ProviderStoreConnection.id",
        foreign_keys=[provider_store_connection_id]
    )
    line_items: Mapped[list["OrderLineItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderLineItem(Base, TimestampMixin):
    __tablename__ = "order_line_items"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "order_id",
            "external_line_id",
            name="uq_order_line_items_org_order_external",
        ),
        ForeignKeyConstraint(
            ["organization_id", "order_id"],
            ["orders.organization_id", "orders.id"],
            name="fk_order_line_items_org_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_order_line_items_org_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="ck_order_line_items_quantity_positive"),
        CheckConstraint(
            "mapping_status IN ('matched', 'unmatched', 'manual')",
            name="ck_order_line_items_mapping_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    order_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True)
    external_line_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_listing_id: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    external_product_id: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    sku: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(8), nullable=True)
    revenue_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    production_cost_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    shipping_cost_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    provider_fee_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unmatched")
    mapped_by_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    mapped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)

    order: Mapped["Order"] = relationship(back_populates="line_items")


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source",
            "external_id",
            name="uq_expenses_org_source_external",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_expenses_org_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["provider_product_drafts.organization_id", "provider_product_drafts.id"],
            name="fk_expenses_org_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount >= 0", name="ck_expenses_amount_nonnegative"),
        CheckConstraint(
            "source IN ('manual', 'etsy', 'printify', 'gelato', 'shopify', 'system')",
            name="ck_expenses_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_store_connection_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True)
    product_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True)
    incurred_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    external_id: Mapped[str] = mapped_column(String(255), nullable=True)


class ExchangeRate(Base, TimestampMixin):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "base_currency",
            "quote_currency",
            "effective_on",
            name="uq_exchange_rates_org_pair_date",
        ),
        CheckConstraint("rate > 0", name="ck_exchange_rates_rate_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    effective_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")


class SyncJob(Base, TimestampMixin):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        Index("ix_sync_jobs_org_type_status", "organization_id", "job_type", "status"),
        Index(
            "uq_sync_jobs_active_scope",
            "organization_id",
            "job_type",
            "scope_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'leased', 'running')"),
            sqlite_where=text("status IN ('queued', 'leased', 'running')"),
        ),
        CheckConstraint(
            "status IN ('queued', 'leased', 'running', 'completed', 'partial', 'failed', 'cancelled')",
            name="ck_sync_jobs_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_sync_jobs_attempt_count_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="ck_sync_jobs_max_attempts_positive"),
        CheckConstraint("max_attempts <= 10", name="ck_sync_jobs_max_attempts_bounded"),
        CheckConstraint("attempt_count <= max_attempts", name="ck_sync_jobs_attempt_count_within_limit"),
        CheckConstraint(
            "status != 'queued' OR attempt_count < max_attempts",
            name="ck_sync_jobs_queued_retryable",
        ),
        CheckConstraint(
            "(status IN ('leased', 'running') AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL) "
            "OR (status NOT IN ('leased', 'running') AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_sync_jobs_lease_fields",
        ),
        UniqueConstraint("organization_id", "id", name="uq_sync_jobs_org_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, default="organization")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    lease_owner: Mapped[str] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    result_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)


class AnalyticsSnapshot(Base, TimestampMixin):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "source_scope",
            name="uq_analytics_snapshots_org_provider_scope",
        ),
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_analytics_snapshots_status",
        ),
        CheckConstraint(
            "expires_at IS NULL OR fetched_at IS NOT NULL",
            name="ck_analytics_snapshots_expiry_requires_fetch",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_scope: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="failed")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_summary: Mapped[str] = mapped_column(Text, nullable=True)


class SyncEvent(Base, TimestampMixin):
    __tablename__ = "sync_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "sync_job_id"],
            ["sync_jobs.organization_id", "sync_jobs.id"],
            name="fk_sync_events_org_sync_job",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "provider_store_connection_id"],
            ["provider_store_connections.organization_id", "provider_store_connections.id"],
            name="fk_sync_events_org_store",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sync_job_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=True)
    provider_store_connection_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(json_type, nullable=True)

    sync_job: Mapped["SyncJob"] = relationship(foreign_keys=[sync_job_id])
