from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from app.db.models import (
    DesignAsset as DesignAssetModel,
    Mockup as MockupModel,
    PodProduct as PodProductModel,
    ProductBlueprint as ProductBlueprintModel,
    ProviderProductDraft as ProviderProductDraftModel,
    ProviderStoreConnection as ProviderStoreConnectionModel,
    PublishingJob as PublishingJobModel,
)
from app.models import Blueprint, DesignAsset, Mockup, Product, ProviderStoreConnection, PublishingJob


def decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def to_provider_store_connection(model: ProviderStoreConnectionModel) -> ProviderStoreConnection:
    return ProviderStoreConnection(
        id=model.id,
        provider=model.provider,
        credential_key=model.credential_key,
        provider_store_id=model.provider_store_id,
        label=model.label,
        storefront_type=model.storefront_type,
        storefront_display_name=model.storefront_display_name,
        etsy_shop_id=model.etsy_shop_id,
        status=model.status,
        discovery_source=model.discovery_source,
        last_sync_at=model.last_synced_at,
        order_sync_last_success_at=model.order_sync_last_success_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_blueprint(model: ProductBlueprintModel) -> Blueprint:
    store = model.provider_store_connection
    return Blueprint(
        id=model.id,
        name=model.name,
        category=model.category,
        provider=model.provider,
        provider_store_connection_id=model.provider_store_connection_id,
        provider_store_label=store.label if store else "",
        provider_storefront_type=(store.storefront_type if store else "unknown"),
        reference_type=model.reference_type,
        reference_value=model.reference_value,
        provider_resource_id=model.provider_resource_id,
        provider_display_name=model.provider_display_name,
        product_code=model.product_code,
        placement_config_json=model.placement_config_json,
        provider_snapshot_json=model.provider_snapshot_json,
        product_type=model.product_type,
        configuration_summary=model.configuration_summary,
        variant_count=model.variant_count,
        base_cost_amount=decimal_to_float(model.base_cost_amount),
        currency=model.currency,
        base_title=model.base_title,
        base_description=model.base_description,
        base_tags=model.base_tags_json or [],
        basic_design_info_json=model.basic_design_info_json,
        draft_count=len(model.drafts or []),
        status=model.status,
        validated_at=model.validated_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


MediaUrlBuilder = Callable[[str], str | None]


def _media_url(model: DesignAssetModel | MockupModel, builder: MediaUrlBuilder | None) -> str | None:
    if builder is None:
        return model.public_url
    try:
        return builder(model.storage_key) or model.public_url
    except Exception:
        return model.public_url


def to_design_asset(
    model: DesignAssetModel,
    *,
    media_url_builder: MediaUrlBuilder | None = None,
) -> DesignAsset:
    return DesignAsset(
        id=model.id,
        file_name=model.file_name,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        storage_key=model.storage_key,
        public_url=_media_url(model, media_url_builder),
        checksum=model.checksum,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_mockup(
    model: MockupModel,
    *,
    media_url_builder: MediaUrlBuilder | None = None,
) -> Mockup:
    return Mockup(
        id=model.id,
        provider_product_draft_id=model.provider_product_draft_id,
        file_name=model.file_name,
        content_type=model.content_type,
        size_bytes=model.size_bytes,
        storage_key=model.storage_key,
        public_url=_media_url(model, media_url_builder),
        checksum=model.checksum,
        position=model.position,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_product(
    model: ProviderProductDraftModel,
    *,
    media_url_builder: MediaUrlBuilder | None = None,
) -> Product:
    store = model.provider_store_connection
    blueprint = model.blueprint
    return Product(
        id=model.id,
        name=model.title,
        product_type=blueprint.product_type or blueprint.name if blueprint else "Product",
        provider=model.provider,
        provider_store_connection_id=model.provider_store_connection_id,
        provider_store_label=store.label if store else "",
        provider_storefront_type=(store.storefront_type if store else "unknown"),
        status=model.status,
        publishing_status=model.publishing_status,
        validation_status=model.validation_status,
        retail_price=decimal_to_float(model.retail_price),
        cost_amount=decimal_to_float(model.cost_amount),
        margin=decimal_to_float(model.margin_amount),
        currency=model.currency,
        blueprint_id=model.blueprint_id,
        design_asset_id=model.design_asset_id,
        provider_product_id=model.provider_product_id,
        external_listing_id=model.external_listing_id,
        provider_product_url=model.provider_product_url,
        provider_fulfillment_url=model.provider_fulfillment_url,
        provider_status=model.provider_status,
        title=model.title,
        description=model.description,
        tags=model.tags_json or [],
        sku=model.sku,
        revision=model.revision,
        design_description=model.design_description,
        seo_title=model.seo_title,
        seo_description=model.seo_description,
        seo_keywords=model.seo_keywords_json or [],
        last_ai_generation_id=model.last_ai_generation_id,
        mockup_count=len(model.mockups or []),
        design_asset=(
            to_design_asset(model.design_asset, media_url_builder=media_url_builder)
            if model.design_asset
            else None
        ),
        mockups=[
            to_mockup(item, media_url_builder=media_url_builder)
            for item in sorted(model.mockups or [], key=lambda mockup: (mockup.position, mockup.id))
        ],
        last_provider_sync_at=model.last_provider_sync_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_publishing_job(model: PublishingJobModel) -> PublishingJob:
    return PublishingJob(
        id=model.id,
        product_id=model.provider_product_draft_id,
        provider=model.provider,
        provider_store_connection_id=model.provider_store_connection_id,
        status=model.status,
        stage=model.stage,
        retry_count=model.retry_count,
        operation=model.operation,
        product_revision=model.product_revision,
        provider_product_id=model.provider_product_id,
        error_message=model.error_message,
        blueprint_id=model.blueprint_id,
        pod_product_id=model.pod_product_id,
        raw_result_json=model.raw_result_json,
        started_at=model.started_at,
        completed_at=model.completed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
