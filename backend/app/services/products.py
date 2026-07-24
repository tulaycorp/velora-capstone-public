from __future__ import annotations

from decimal import Decimal
from typing import Any
import logging
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.actor import ActorContext
from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.models import (
    DesignAsset,
    Mockup,
    ProductBlueprint,
    ProviderProductDraft,
    ProviderStoreConnection,
)
from app.models import (
    MockupOrderRequest,
    Product,
    ProductCreateRequest,
    ProductStudioState,
    ProductUpdateRequest,
)
from app.services.media_uploads import read_validated_media_upload
from app.services.blueprints import _get_blueprint_or_404
from app.services.serializers import (
    to_design_asset,
    to_mockup,
    to_product,
)
from app.storage import get_storage_service
from app.storage.paths import build_design_asset_storage_key, build_mockup_storage_key


product_logger = get_logger("products")


def _to_design_asset_response(row: DesignAsset):
    return to_design_asset(row, media_url_builder=get_storage_service().build_public_url)


def _to_mockup_response(row: Mockup):
    return to_mockup(row, media_url_builder=get_storage_service().build_public_url)


def _to_product_response(row: ProviderProductDraft) -> Product:
    return to_product(row, media_url_builder=get_storage_service().build_public_url)


def _raise_storage_action_error(*, action: str, exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc

    normalized = str(exc).strip().casefold()
    if "s3-compatible storage is not configured" in normalized:
        raise HTTPException(
            status_code=503,
            detail="Asset storage is not configured in this environment. Add the storage settings before uploading files.",
        ) from exc

    raise HTTPException(
        status_code=502,
        detail=f"Asset storage failed while {action}. Try again in a moment.",
    ) from exc


def _persist_uploaded_media(db: Session, row: DesignAsset | Mockup) -> None:
    db.add(row)
    db.commit()
    db.refresh(row)


async def store_design_asset(
    db: Session,
    *,
    actor: ActorContext,
    file: UploadFile,
) -> Any:
    upload = await read_validated_media_upload(file)
    storage = get_storage_service()
    design_asset_id = str(uuid.uuid4())
    storage_key = build_design_asset_storage_key(
        organization_id=actor.organization_id,
        design_asset_id=design_asset_id,
        file_name=f"source{upload.canonical_extension}",
    )
    try:
        stored = storage.upload_file(
            storage_key=storage_key,
            file=upload.file,
            size_bytes=upload.size_bytes,
            checksum=upload.checksum,
            content_type=upload.content_type,
            file_name=upload.file_name,
            metadata={
                "organization-id": actor.organization_id,
                "design-asset-id": design_asset_id,
                "uploaded-by": actor.actor_id,
            },
        )
    except Exception as exc:
        upload.close()
        _raise_storage_action_error(action="uploading this design asset", exc=exc)
    row = DesignAsset(
        id=design_asset_id,
        organization_id=actor.organization_id,
        file_name=upload.file_name,
        content_type=upload.content_type,
        size_bytes=upload.size_bytes,
        storage_key=stored.storage_key,
        public_url=stored.public_url,
        checksum=stored.checksum,
    )
    try:
        _persist_uploaded_media(db, row)
    except Exception as exc:
        db.rollback()
        try:
            storage.delete_object(stored.storage_key)
        except Exception as cleanup_exc:
            log_event(
                product_logger,
                "design_asset.compensation_failed",
                level=logging.ERROR,
                organization_id=actor.organization_id,
                design_asset_id=design_asset_id,
                storage_key=stored.storage_key,
                error=str(cleanup_exc),
            )
        raise HTTPException(
            status_code=500,
            detail="The design image could not be saved. The upload was rolled back.",
        ) from exc
    finally:
        upload.close()
    log_event(
        product_logger,
        "design_asset.stored",
        verbose_only=True,
        organization_id=actor.organization_id,
        design_asset_id=row.id,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
    )
    return _to_design_asset_response(row)


def _get_design_asset_or_404(db: Session, *, actor: ActorContext, design_asset_id: str) -> DesignAsset:
    row = db.scalar(
        select(DesignAsset).where(
            DesignAsset.id == design_asset_id,
            DesignAsset.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Design asset not found.")
    return row


def _get_product_or_404(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str,
    for_update: bool = False,
) -> ProviderProductDraft:
    statement = (
        select(ProviderProductDraft)
        .options(
            selectinload(ProviderProductDraft.provider_store_connection),
            selectinload(ProviderProductDraft.blueprint).selectinload(ProductBlueprint.provider_store_connection),
            selectinload(ProviderProductDraft.design_asset),
            selectinload(ProviderProductDraft.mockups),
            selectinload(ProviderProductDraft.pod_product),
            selectinload(ProviderProductDraft.publishing_jobs),
        )
        .where(
            ProviderProductDraft.id == product_id,
            ProviderProductDraft.organization_id == actor.organization_id,
        )
    )
    if for_update:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="Product draft not found.")
    return row


def create_product_draft(
    db: Session,
    *,
    actor: ActorContext,
    payload: ProductCreateRequest,
) -> Product:
    blueprint = _get_blueprint_or_404(db, actor=actor, blueprint_id=payload.blueprint_id)
    design_asset = _get_design_asset_or_404(db, actor=actor, design_asset_id=payload.design_asset_id)
    title = (payload.title or blueprint.base_title or blueprint.name).strip()
    description = (payload.description if payload.description is not None else blueprint.base_description) or None
    tags = payload.tags or blueprint.base_tags_json or []
    retail_price = Decimal(str(payload.retail_price)) if payload.retail_price is not None else None
    cost_amount = blueprint.base_cost_amount
    margin_amount = retail_price - cost_amount if retail_price is not None and cost_amount is not None else None
    row = ProviderProductDraft(
        organization_id=actor.organization_id,
        blueprint_id=blueprint.id,
        provider=blueprint.provider,
        provider_store_connection_id=blueprint.provider_store_connection_id,
        design_asset_id=design_asset.id,
        status="draft",
        validation_status="validated" if blueprint.validated_at else "pending",
        publishing_status="not_started",
        title=title,
        sku=(payload.sku or blueprint.product_code or "").strip() or None,
        description=description,
        tags_json=tags,
        retail_price=retail_price,
        cost_amount=cost_amount,
        margin_amount=margin_amount,
        currency=payload.currency or blueprint.currency or "USD",
        design_description=(payload.design_description or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_event(
        product_logger,
        "product_draft.created",
        verbose_only=True,
        organization_id=actor.organization_id,
        product_id=row.id,
        blueprint_id=row.blueprint_id,
        provider=row.provider,
        provider_store_connection_id=row.provider_store_connection_id,
        status=row.status,
    )
    return _to_product_response(_get_product_or_404(db, actor=actor, product_id=row.id))


def list_products(db: Session, *, actor: ActorContext) -> list[Product]:
    rows = db.scalars(
        select(ProviderProductDraft)
        .options(
            selectinload(ProviderProductDraft.provider_store_connection),
            selectinload(ProviderProductDraft.blueprint),
            selectinload(ProviderProductDraft.design_asset),
            selectinload(ProviderProductDraft.mockups),
            selectinload(ProviderProductDraft.pod_product),
        )
        .where(ProviderProductDraft.organization_id == actor.organization_id)
        .order_by(ProviderProductDraft.created_at.desc())
    ).all()
    return [_to_product_response(row) for row in rows]


def get_product(db: Session, *, actor: ActorContext, product_id: str) -> Product:
    return _to_product_response(_get_product_or_404(db, actor=actor, product_id=product_id))


def _normalize_tags_for_compare(tags: list[str] | None) -> list[str]:
    return [str(tag) for tag in (tags or [])]


def update_product(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str,
    payload: ProductUpdateRequest,
) -> Product:
    row = _get_product_or_404(db, actor=actor, product_id=product_id)
    if payload.expected_revision is not None and payload.expected_revision != row.revision:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This product changed. Refresh and try again.")
    next_title = row.title if payload.title is None else payload.title.strip()
    next_description = (
        row.description
        if payload.description is None
        else payload.description.strip() or None
    )
    next_tags = row.tags_json or []
    if payload.tags is not None:
        next_tags = payload.tags
    next_retail_price = row.retail_price
    if payload.retail_price is not None:
        next_retail_price = Decimal(str(payload.retail_price))
    next_currency = row.currency if payload.currency is None else payload.currency
    next_sku = row.sku if payload.sku is None else payload.sku.strip() or None
    next_design_description = row.design_description if payload.design_description is None else payload.design_description.strip() or None

    changed_title = next_title != row.title
    changed_description = next_description != row.description
    changed_tags = _normalize_tags_for_compare(next_tags) != _normalize_tags_for_compare(row.tags_json)
    changed_retail_price = next_retail_price != row.retail_price
    changed_sku = next_sku != row.sku
    changed_design_description = next_design_description != row.design_description

    if payload.design_asset_id is not None:
        design_asset = _get_design_asset_or_404(
            db,
            actor=actor,
            design_asset_id=payload.design_asset_id,
        )
        row.design_asset_id = design_asset.id
    if payload.title is not None:
        row.title = next_title
    if payload.description is not None:
        row.description = next_description
    if payload.tags is not None:
        row.tags_json = next_tags
    if payload.retail_price is not None:
        row.retail_price = next_retail_price
        row.margin_amount = row.retail_price - row.cost_amount if row.cost_amount is not None else None
    if payload.currency is not None:
        row.currency = next_currency
    if payload.sku is not None:
        row.sku = next_sku
    if payload.design_description is not None:
        row.design_description = next_design_description
    if payload.seo_title is not None:
        row.seo_title = payload.seo_title.strip() or None
    if payload.seo_description is not None:
        row.seo_description = payload.seo_description.strip() or None
    if payload.seo_keywords is not None:
        row.seo_keywords_json = payload.seo_keywords
    if payload.status is not None:
        row.status = payload.status
    if payload.validation_status is not None:
        row.validation_status = payload.validation_status
    if any((changed_title, changed_description, changed_tags, changed_retail_price, changed_sku, changed_design_description, payload.design_asset_id is not None, payload.seo_title is not None, payload.seo_description is not None, payload.seo_keywords is not None, payload.status is not None, payload.validation_status is not None)):
        row.revision += 1
    db.commit()
    db.refresh(row)
    log_event(
        product_logger,
        "product_draft.updated",
        verbose_only=True,
        organization_id=actor.organization_id,
        product_id=row.id,
        status=row.status,
        validation_status=row.validation_status,
    )
    return _to_product_response(_get_product_or_404(db, actor=actor, product_id=product_id))


def delete_product(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str,
) -> None:
    row = _get_product_or_404(db, actor=actor, product_id=product_id)
    if row.publishing_status in {"queued", "publishing"}:
        raise HTTPException(
            status_code=409,
            detail="Products cannot be deleted while sending is still in progress.",
        )

    storage = get_storage_service()
    design_asset = row.design_asset
    delete_design_asset = bool(
        design_asset is not None
        and (
            db.scalar(
                select(func.count(ProviderProductDraft.id)).where(
                    ProviderProductDraft.design_asset_id == row.design_asset_id,
                    ProviderProductDraft.id != row.id,
                )
            )
            or 0
        )
        == 0
    )
    deleted_mockup_count = 0
    try:
        for mockup in list(row.mockups or []):
            storage.delete_object(mockup.storage_key)
            deleted_mockup_count += 1
    except Exception as exc:
        _raise_storage_action_error(action="deleting saved mockups", exc=exc)

    publishing_sync_jobs = [
        publishing_job.sync_job
        for publishing_job in list(row.publishing_jobs or [])
        if publishing_job.sync_job is not None
    ]
    for publishing_job in list(row.publishing_jobs or []):
        db.delete(publishing_job)

    if row.pod_product is not None:
        db.delete(row.pod_product)

    db.delete(row)
    db.flush()
    for publishing_sync_job in publishing_sync_jobs:
        db.delete(publishing_sync_job)
    db.flush()

    deleted_design_asset = False
    if delete_design_asset and design_asset is not None:
        try:
            storage.delete_object(design_asset.storage_key)
        except Exception as exc:
            _raise_storage_action_error(action="deleting the saved design asset", exc=exc)
        db.delete(design_asset)
        deleted_design_asset = True

    db.commit()
    log_event(
        product_logger,
        "product_draft.deleted",
        verbose_only=True,
        organization_id=actor.organization_id,
        product_id=product_id,
        provider=row.provider,
        deleted_mockup_count=deleted_mockup_count,
        deleted_design_asset=deleted_design_asset,
        had_provider_product=bool(row.provider_product_id),
        had_external_listing=bool(row.external_listing_id),
    )


async def store_mockup(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str,
    file: UploadFile,
    position: int | None,
) -> Any:
    draft = _get_product_or_404(db, actor=actor, product_id=product_id, for_update=True)
    if len(draft.mockups or []) >= settings.upload_max_mockups_per_product:
        raise HTTPException(
            status_code=409,
            detail=f"This product already has the maximum of {settings.upload_max_mockups_per_product} images.",
        )
    upload = await read_validated_media_upload(file)
    storage = get_storage_service()
    mockup_id = str(uuid.uuid4())
    storage_key = build_mockup_storage_key(
        organization_id=draft.organization_id,
        draft_id=draft.id,
        mockup_id=mockup_id,
        file_name=f"source{upload.canonical_extension}",
    )
    try:
        stored = storage.upload_file(
            storage_key=storage_key,
            file=upload.file,
            size_bytes=upload.size_bytes,
            checksum=upload.checksum,
            content_type=upload.content_type,
            file_name=upload.file_name,
            metadata={
                "organization-id": draft.organization_id,
                "draft-id": draft.id,
                "mockup-id": mockup_id,
                "uploaded-by": actor.actor_id,
            },
        )
    except Exception as exc:
        upload.close()
        _raise_storage_action_error(action="uploading this mockup", exc=exc)
    next_position = position if position is not None else len(draft.mockups or [])
    row = Mockup(
        id=mockup_id,
        organization_id=actor.organization_id,
        provider_product_draft_id=draft.id,
        file_name=upload.file_name,
        content_type=upload.content_type,
        size_bytes=upload.size_bytes,
        storage_key=stored.storage_key,
        public_url=stored.public_url,
        checksum=stored.checksum,
        position=next_position,
    )
    try:
        draft.revision += 1
        _persist_uploaded_media(db, row)
    except Exception as exc:
        db.rollback()
        try:
            storage.delete_object(stored.storage_key)
        except Exception as cleanup_exc:
            log_event(
                product_logger,
                "product_mockup.compensation_failed",
                level=logging.ERROR,
                organization_id=actor.organization_id,
                product_id=draft.id,
                mockup_id=mockup_id,
                storage_key=stored.storage_key,
                error=str(cleanup_exc),
            )
        raise HTTPException(
            status_code=500,
            detail="The product image could not be saved. The upload was rolled back.",
        ) from exc
    finally:
        upload.close()
    log_event(
        product_logger,
        "product_mockup.stored",
        verbose_only=True,
        organization_id=actor.organization_id,
        product_id=draft.id,
        mockup_id=row.id,
        position=row.position,
        size_bytes=row.size_bytes,
    )
    return _to_mockup_response(row)


def _reindex_mockups(mockups: list[Mockup]) -> None:
    for index, mockup in enumerate(mockups):
        mockup.position = index


def reorder_mockups(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str,
    payload: MockupOrderRequest,
) -> Product:
    draft = _get_product_or_404(db, actor=actor, product_id=product_id)
    mockups = list(draft.mockups or [])
    current_mockup_ids = [
        mockup.id
        for mockup in sorted(mockups, key=lambda item: (item.position, item.id))
    ]
    mockups_by_id = {mockup.id: mockup for mockup in mockups}
    ordered_mockups = [
        mockups_by_id[mockup_id]
        for mockup_id in payload.mockup_ids
        if mockup_id in mockups_by_id
    ]
    ordered_ids = {mockup.id for mockup in ordered_mockups}
    ordered_mockups.extend(
        mockup
        for mockup in sorted(mockups, key=lambda item: (item.position, item.id))
        if mockup.id not in ordered_ids
    )

    _reindex_mockups(ordered_mockups)
    order_changed = [mockup.id for mockup in ordered_mockups] != current_mockup_ids
    if order_changed:
        draft.revision += 1
    db.commit()
    log_event(
        product_logger,
        "product_mockup.reordered",
        verbose_only=True,
        organization_id=actor.organization_id,
        product_id=draft.id,
        mockup_count=len(ordered_mockups),
    )
    return _to_product_response(_get_product_or_404(db, actor=actor, product_id=product_id))


def delete_mockup(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str,
    mockup_id: str,
) -> Product:
    draft = _get_product_or_404(db, actor=actor, product_id=product_id)
    mockup = next((item for item in draft.mockups or [] if item.id == mockup_id), None)
    if mockup is None:
        raise HTTPException(status_code=404, detail="Product mockup not found.")

    storage = get_storage_service()
    try:
        storage.delete_object(mockup.storage_key)
    except Exception as exc:
        _raise_storage_action_error(action="deleting this mockup", exc=exc)
    db.delete(mockup)
    remaining_mockups = [
        item
        for item in sorted(draft.mockups or [], key=lambda row: (row.position, row.id))
        if item.id != mockup_id
    ]
    _reindex_mockups(remaining_mockups)
    draft.revision += 1
    db.commit()
    log_event(
        product_logger,
        "product_mockup.deleted",
        verbose_only=True,
        organization_id=actor.organization_id,
        product_id=draft.id,
        mockup_id=mockup_id,
        storage_key=mockup.storage_key,
    )
    return _to_product_response(_get_product_or_404(db, actor=actor, product_id=product_id))


def get_product_studio_state(db: Session, *, actor: ActorContext) -> ProductStudioState:
    blueprint_count = db.scalar(
        select(func.count(ProductBlueprint.id)).where(
            ProductBlueprint.organization_id == actor.organization_id
        )
    ) or 0
    draft_count = db.scalar(
        select(func.count(ProviderProductDraft.id)).where(
            ProviderProductDraft.organization_id == actor.organization_id
        )
    ) or 0
    connection_ids = db.scalars(
        select(ProviderStoreConnection.id)
        .where(
            ProviderStoreConnection.organization_id == actor.organization_id,
            ProviderStoreConnection.deleted_at.is_(None),
        )
        .order_by(
            ProviderStoreConnection.provider.asc(),
            ProviderStoreConnection.label.asc(),
        )
    ).all()
    return ProductStudioState(
        steps=[
            "Blueprint",
            "Design Asset",
            "Draft Listing",
            "Mockups",
            "Pricing",
            "Review",
            "Publish",
        ],
        selected_provider=None,
        selected_store_connection_ids=connection_ids,
        requires_blueprint=True,
        blueprint_count=int(blueprint_count),
        draft_count=int(draft_count),
    )
