from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.models.schemas import DiscoverySource, PodProviderKey, StorefrontType


class ProviderStoreRecord(BaseModel):
    provider_store_id: str
    storefront_type: StorefrontType
    storefront_display_name: str
    label: str
    etsy_shop_id: str | None = None
    discovery_source: DiscoverySource = "legacy"


class ReferenceValidationResult(BaseModel):
    reference_type: str
    normalized_reference_value: str
    provider_resource_id: str
    provider_display_name: str | None = None


class ReferenceSnapshotResult(BaseModel):
    provider_resource_id: str
    provider_display_name: str | None = None
    provider_snapshot_json: dict[str, Any]
    product_type: str | None = None
    configuration_summary: str | None = None
    variant_count: int = 0
    base_cost_amount: float | None = None
    currency: str | None = None
    placement_config_json: dict[str, Any] | None = None
    base_title: str | None = None
    base_description: str | None = None
    base_tags: list[str] = Field(default_factory=list)


class ProviderProductCreateInput(BaseModel):
    product_id: str
    blueprint_id: str
    provider: PodProviderKey
    provider_store_id: str
    reference_type: str
    reference_value: str
    provider_resource_id: str
    provider_snapshot_json: dict[str, Any] | None = None
    placement_config_json: dict[str, Any] | None = None
    design_asset_url: str
    title: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    sku: str | None = None
    retail_price: float | None = None
    currency: str | None = None
    mockup_urls: list[str] = Field(default_factory=list)
    idempotency_key: str = ""
    source_revision: int = Field(default=1, ge=1)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProviderProductCreateResult(BaseModel):
    provider_product_id: str
    external_listing_id: str | None = None
    provider_product_url: str | None = None
    provider_fulfillment_url: str | None = None
    provider_status: str | None = None
    raw_provider_payload_json: dict[str, Any] | None = None


class ProviderPublishResult(BaseModel):
    provider_product_id: str
    external_listing_id: str | None = None
    provider_product_url: str | None = None
    provider_fulfillment_url: str | None = None
    provider_status: str | None = None
    raw_provider_payload_json: dict[str, Any] | None = None


class ProviderProductStatus(BaseModel):
    provider_product_id: str
    external_listing_id: str | None = None
    provider_product_url: str | None = None
    provider_fulfillment_url: str | None = None
    provider_status: str | None = None
    raw_provider_payload_json: dict[str, Any] | None = None


class ProviderOrderPage(BaseModel):
    orders: list[dict[str, Any]] = Field(default_factory=list)
    fetched_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    next_cursor: str | None = None
    observed_watermark_at: datetime | None = None


class BaseProviderAdapter(ABC):
    provider: PodProviderKey

    def __init__(self, credentials: dict[str, Any]):
        self.credentials = credentials

    @abstractmethod
    async def discover_store_connections(self) -> list[ProviderStoreRecord]:
        raise NotImplementedError

    @abstractmethod
    async def validate_reference(
        self,
        *,
        reference_type: str,
        reference_value: str,
    ) -> ReferenceValidationResult:
        raise NotImplementedError

    @abstractmethod
    async def fetch_reference_snapshot(
        self,
        *,
        reference_type: str,
        reference_value: str,
        provider_resource_id: str,
    ) -> ReferenceSnapshotResult:
        raise NotImplementedError

    @abstractmethod
    async def create_provider_product(
        self,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult:
        raise NotImplementedError

    async def update_provider_product(
        self,
        *,
        provider_product_id: str,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult:
        raise NotImplementedError

    async def reconcile_provider_product(
        self,
        *,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult | None:
        """Find a prior create after an ambiguous worker/provider failure when supported."""
        return None

    @abstractmethod
    async def publish_provider_product(
        self,
        *,
        provider_product_id: str,
    ) -> ProviderPublishResult:
        raise NotImplementedError

    @abstractmethod
    async def fetch_provider_product_status(
        self,
        *,
        provider_product_id: str,
    ) -> ProviderProductStatus:
        raise NotImplementedError

    @abstractmethod
    async def fetch_orders(
        self,
        *,
        provider_store_id: str,
        since: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ProviderOrderPage:
        raise NotImplementedError

    @abstractmethod
    def normalize_order(
        self,
        *,
        raw_order: dict[str, Any],
        organization_id: str,
        provider_store_connection_id: str,
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def get_order_url(self, *, provider_store_id: str, external_order_id: str) -> str:
        raise NotImplementedError
