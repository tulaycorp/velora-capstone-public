from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import ProviderProductDraft, PublishingJob
from app.providers import ProviderProductCreateInput
from app.services.serializers import decimal_to_float


ACTIVE_PUBLISHING_JOB_STATUSES = ("queued", "leased", "running")
PUBLISHED_PROVIDER_STATUSES = {"active", "published", "succeeded"}


class PublishingJobLeaseLostError(RuntimeError):
    pass


class PublishingStageError(RuntimeError):
    def __init__(self, stage: str, cause: Exception):
        self.stage = stage
        self.cause = cause
        super().__init__(str(cause) or type(cause).__name__)


class PublishMediaUrlBuilder(Protocol):
    def build_public_url(self, storage_key: str) -> str | None: ...


def publishing_idempotency_key(
    *,
    organization_id: str,
    product_id: str,
    provider: str,
    provider_store_connection_id: str,
    operation: str,
    product_revision: int,
) -> str:
    source = "|".join(
        (
            organization_id,
            product_id,
            provider,
            provider_store_connection_id,
            operation,
            str(product_revision),
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def publishing_scope_key(*, product_id: str, provider_store_connection_id: str) -> str:
    digest = hashlib.sha256(
        f"{product_id}|{provider_store_connection_id}".encode("utf-8")
    ).hexdigest()
    return f"publish:{digest}"


def active_publishing_job_statement(*, organization_id: str, product_id: str):
    return (
        select(PublishingJob)
        .where(
            PublishingJob.organization_id == organization_id,
            PublishingJob.provider_product_draft_id == product_id,
            PublishingJob.status.in_(ACTIVE_PUBLISHING_JOB_STATUSES),
        )
        .order_by(PublishingJob.created_at.desc())
    )


def build_publishing_snapshot(
    *,
    draft: ProviderProductDraft,
    idempotency_key: str,
    submitted_at: datetime,
    media_urls: PublishMediaUrlBuilder,
) -> dict[str, Any]:
    if draft.blueprint is None or draft.provider_store_connection is None or draft.design_asset is None:
        raise HTTPException(
            status_code=400,
            detail="Publishing requires a blueprint, provider store connection, and design asset.",
        )
    if not draft.blueprint.provider_resource_id:
        raise HTTPException(
            status_code=400,
            detail="Blueprint reference must be validated before publishing.",
        )
    design_asset_url = media_urls.build_public_url(draft.design_asset.storage_key)
    if not design_asset_url:
        raise HTTPException(status_code=400, detail="Design asset does not have a publishable URL.")
    provider_input = ProviderProductCreateInput(
        product_id=draft.id,
        blueprint_id=draft.blueprint_id,
        provider=draft.provider,  # type: ignore[arg-type]
        provider_store_id=draft.provider_store_connection.provider_store_id,
        reference_type=draft.blueprint.reference_type,
        reference_value=draft.blueprint.reference_value,
        provider_resource_id=draft.blueprint.provider_resource_id,
        provider_snapshot_json=draft.blueprint.provider_snapshot_json,
        placement_config_json=draft.blueprint.placement_config_json,
        design_asset_url=design_asset_url,
        title=draft.title,
        description=draft.description,
        tags=list(draft.tags_json or []),
        sku=draft.sku,
        retail_price=decimal_to_float(draft.retail_price),
        currency=draft.currency,
        # Marketplace mockups are Etsy listing media, not POD product inputs.
        # They are read from Velora storage after the provider returns the Etsy
        # listing id and uploaded through the direct Etsy API path.
        mockup_urls=[],
        idempotency_key=idempotency_key,
        source_revision=draft.revision,
        submitted_at=submitted_at,
    )
    return {
        "provider_input": provider_input.model_dump(mode="json"),
        "existing_provider_product_id": draft.provider_product_id,
        "existing_external_listing_id": draft.external_listing_id,
        "etsy_listing_images": [
            {
                "mockup_id": mockup.id,
                "file_name": mockup.file_name,
                "content_type": mockup.content_type,
                "size_bytes": mockup.size_bytes,
                "storage_key": mockup.storage_key,
                "position": mockup.position,
            }
            for mockup in sorted(draft.mockups or [], key=lambda item: (item.position, item.id))
        ],
    }


def _readiness_issue(*, field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


def validate_publishing_readiness(draft: ProviderProductDraft) -> None:
    issues: list[dict[str, str]] = []
    blueprint = draft.blueprint
    store_connection = draft.provider_store_connection

    if blueprint is None or not blueprint.validated_at or not blueprint.provider_resource_id:
        issues.append(_readiness_issue(
            field="blueprint_id",
            code="provider_reference_missing",
            message="Validate the selected blueprint before sending this product.",
        ))
    elif blueprint.variant_count < 1:
        issues.append(_readiness_issue(
            field="blueprint_id",
            code="variants_missing",
            message="The selected blueprint needs at least one validated variant.",
        ))
    if store_connection is None or store_connection.status != "connected":
        issues.append(_readiness_issue(
            field="provider_store_connection_id",
            code="store_connection_unavailable",
            message="Reconnect the selected store before sending this product.",
        ))
    if not draft.title.strip():
        issues.append(_readiness_issue(
            field="title",
            code="title_missing",
            message="Add a product title before sending.",
        ))
    if draft.retail_price is None or draft.retail_price <= 0:
        issues.append(_readiness_issue(
            field="retail_price",
            code="retail_price_invalid",
            message="Add a retail price greater than zero before sending.",
        ))
    if not str(draft.currency or "").strip():
        issues.append(_readiness_issue(
            field="currency",
            code="currency_missing",
            message="Choose a currency before sending.",
        ))
    if draft.design_asset is None or not draft.design_asset.storage_key:
        issues.append(_readiness_issue(
            field="design_asset_id",
            code="design_asset_missing",
            message="Upload and save the product design before sending.",
        ))
    if not any(mockup.storage_key for mockup in draft.mockups or []):
        issues.append(_readiness_issue(
            field="mockups",
            code="listing_image_missing",
            message="Upload at least one product image before sending.",
        ))

    if issues:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "publish_not_ready",
                "message": "Finish the highlighted product requirements before sending.",
                "fields": issues,
            },
        )
