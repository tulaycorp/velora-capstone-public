from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.services.provider_connections as commerce
from app.core.actor import ActorContext
from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.database import WorkerSessionLocal as SessionLocal
from app.db.models import (
    PodProduct,
    ProviderProductDraft,
    ProviderStoreConnection,
    PublishingJob,
    PublishingOutbox,
    SyncJob,
)
from app.db.tenant_context import set_database_request_context
from app.providers import ProviderProductCreateInput, get_provider_adapter
from app.providers.base import (
    ProviderProductCreateResult,
    ProviderProductStatus,
    ProviderPublishResult,
)
from app.services.publishing_policy import (
    PUBLISHED_PROVIDER_STATUSES,
    PublishingJobLeaseLostError,
    PublishingStageError,
    active_publishing_job_statement as _active_publishing_job_statement,
    build_publishing_snapshot as _build_publishing_snapshot,
    publishing_idempotency_key as _publishing_idempotency_key,
    publishing_scope_key as _publishing_scope_key,
    validate_publishing_readiness as _validate_publishing_readiness,
)
from app.services.etsy import (
    ETSY_LISTING_IMAGE_LIMIT,
    EtsyListingImageUpload,
    build_etsy_listing_edit_url,
    sync_product_listing_to_etsy,
    sync_product_listing_images_to_etsy,
)
from app.services.products import _get_product_or_404
from app.services.serializers import to_publishing_job
from app.storage import get_storage_service


publishing_logger = get_logger("publishing")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def list_publishing_jobs(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str | None = None,
) -> list[Any]:
    statement = (
        select(PublishingJob)
        .where(PublishingJob.organization_id == actor.organization_id)
        .order_by(PublishingJob.created_at.desc())
    )
    if product_id is not None:
        statement = statement.where(PublishingJob.provider_product_draft_id == product_id)
    rows = db.scalars(statement).all()
    return [to_publishing_job(row) for row in rows]


def get_publishing_job(db: Session, *, actor: ActorContext, job_id: str) -> Any:
    row = db.scalar(
        select(PublishingJob).where(
            PublishingJob.id == job_id,
            PublishingJob.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Publishing job not found.")
    return to_publishing_job(row)


def _persist_pod_product(
    db: Session,
    *,
    draft: ProviderProductDraft,
    job: PublishingJob,
    provider_status: str,
    provider_product_id: str,
    external_listing_id: str | None,
    provider_product_url: str | None,
    provider_fulfillment_url: str | None,
    raw_provider_payload_json: dict[str, Any] | None,
) -> PodProduct:
    pod_product = db.scalar(
        select(PodProduct).where(PodProduct.provider_product_draft_id == draft.id)
    )
    if pod_product is None:
        pod_product = PodProduct(
            organization_id=draft.organization_id,
            provider_product_draft_id=draft.id,
            provider=draft.provider,
            provider_store_connection_id=draft.provider_store_connection_id,
            provider_product_id=provider_product_id,
        )
        db.add(pod_product)
    pod_product.provider_product_id = provider_product_id
    pod_product.external_listing_id = external_listing_id
    pod_product.status = provider_status or "created"
    pod_product.provider_product_url = provider_product_url
    pod_product.provider_fulfillment_url = provider_fulfillment_url
    pod_product.raw_provider_payload_json = raw_provider_payload_json
    pod_product.last_synced_at = utc_now()
    db.flush()
    job.pod_product_id = pod_product.id
    return pod_product


def enqueue_publishing_job(
    db: Session,
    *,
    actor: ActorContext,
    product_id: str,
    expected_revision: int | None = None,
) -> Any:
    locked_id = db.scalar(
        select(ProviderProductDraft.id)
        .where(
            ProviderProductDraft.id == product_id,
            ProviderProductDraft.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if locked_id is None:
        raise HTTPException(status_code=404, detail="Product draft not found.")
    draft = _get_product_or_404(db, actor=actor, product_id=product_id)
    existing_active = db.execute(
        _active_publishing_job_statement(
            organization_id=actor.organization_id,
            product_id=product_id,
        )
    ).scalars().first()
    if existing_active is not None:
        return to_publishing_job(existing_active)
    if expected_revision is not None and expected_revision != draft.revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_product_revision",
                "message": "This product changed after the page loaded. Refresh it before sending.",
                "expected_revision": expected_revision,
                "current_revision": draft.revision,
            },
        )

    _validate_publishing_readiness(draft)

    operation = "update" if draft.provider_product_id else "create"
    idempotency_key = _publishing_idempotency_key(
        organization_id=actor.organization_id,
        product_id=draft.id,
        provider=draft.provider,
        provider_store_connection_id=draft.provider_store_connection_id,
        operation=operation,
        product_revision=draft.revision,
    )
    existing_idempotent = db.scalar(
        select(PublishingJob).where(PublishingJob.idempotency_key == idempotency_key)
    )
    if existing_idempotent is not None:
        if existing_idempotent.status == "failed":
            sync_job = db.scalar(
                select(SyncJob)
                .where(SyncJob.id == existing_idempotent.sync_job_id)
                .with_for_update()
            )
            outbox = db.scalar(
                select(PublishingOutbox)
                .where(PublishingOutbox.publishing_job_id == existing_idempotent.id)
                .with_for_update()
            )
            if sync_job is None or outbox is None:
                raise HTTPException(
                    status_code=409,
                    detail="The failed publishing job is missing its retry records. Save another edit before sending again.",
                )
            if existing_idempotent.stage == "queued":
                existing_idempotent.submitted_snapshot_json = _build_publishing_snapshot(
                    draft=draft,
                    idempotency_key=idempotency_key,
                    submitted_at=utc_now(),
                    media_urls=get_storage_service(),
                )
            retry_at = utc_now()
            sync_job.status = "queued"
            sync_job.lease_owner = None
            sync_job.lease_expires_at = None
            sync_job.heartbeat_at = None
            sync_job.attempt_count = 0
            sync_job.available_at = retry_at
            sync_job.result_json = None
            sync_job.started_at = None
            sync_job.completed_at = None
            sync_job.error_message = None
            existing_idempotent.status = "queued"
            existing_idempotent.retry_count = 0
            existing_idempotent.error_message = None
            existing_idempotent.started_at = None
            existing_idempotent.completed_at = None
            existing_idempotent.raw_result_json = None
            outbox.status = "pending"
            outbox.attempt_count = 0
            outbox.available_at = retry_at
            outbox.lease_owner = None
            outbox.lease_expires_at = None
            outbox.dispatched_at = None
            outbox.last_error = None
            draft.publishing_status = "queued"
            draft.status = "ready"
            db.commit()
            db.refresh(existing_idempotent)
        return to_publishing_job(existing_idempotent)

    submitted_at = utc_now()
    snapshot = _build_publishing_snapshot(
        draft=draft,
        idempotency_key=idempotency_key,
        submitted_at=submitted_at,
        media_urls=get_storage_service(),
    )
    sync_job_id = str(uuid.uuid4())
    publishing_job_id = str(uuid.uuid4())
    sync_job = SyncJob(
        id=sync_job_id,
        organization_id=actor.organization_id,
        provider=draft.provider,
        job_type="product_publish",
        scope_key=_publishing_scope_key(
            product_id=draft.id,
            provider_store_connection_id=draft.provider_store_connection_id,
        ),
        status="queued",
        max_attempts=settings.sync_job_max_attempts,
        available_at=submitted_at,
    )
    job = PublishingJob(
        id=publishing_job_id,
        organization_id=actor.organization_id,
        blueprint_id=draft.blueprint_id,
        provider_product_draft_id=draft.id,
        provider=draft.provider,
        provider_store_connection_id=draft.provider_store_connection_id,
        sync_job_id=sync_job_id,
        operation=operation,
        product_revision=draft.revision,
        idempotency_key=idempotency_key,
        submitted_snapshot_json=snapshot,
        provider_product_id=draft.provider_product_id,
        status="queued",
    )
    outbox = PublishingOutbox(
        publishing_job_id=publishing_job_id,
        topic="product_publish",
        payload_json={"publishing_job_id": publishing_job_id},
        status="pending",
        available_at=submitted_at,
    )
    draft.publishing_status = "queued"
    draft.status = "ready"
    db.add_all((sync_job, job, outbox))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            _active_publishing_job_statement(
                organization_id=actor.organization_id,
                product_id=product_id,
            )
        ).scalars().first()
        if existing is None:
            existing = db.scalar(
                select(PublishingJob).where(PublishingJob.idempotency_key == idempotency_key)
            )
        if existing is None:
            raise
        return to_publishing_job(existing)

    db.refresh(job)
    log_event(
        publishing_logger,
        "publishing_job.queued",
        organization_id=actor.organization_id,
        job_id=job.id,
        sync_job_id=sync_job_id,
        product_id=draft.id,
        product_revision=draft.revision,
        operation=operation,
        provider=draft.provider,
    )
    return to_publishing_job(job)


def _load_owned_publishing_rows(
    db: Session,
    *,
    publishing_job_id: str,
    lease_owner: str,
) -> tuple[SyncJob, PublishingJob, ProviderProductDraft]:
    sync_job = db.scalar(
        select(SyncJob)
        .join(PublishingJob, PublishingJob.sync_job_id == SyncJob.id)
        .where(
            PublishingJob.id == publishing_job_id,
            SyncJob.status == "running",
            SyncJob.lease_owner == lease_owner,
            SyncJob.lease_expires_at.is_not(None),
            SyncJob.lease_expires_at > utc_now(),
        )
        .with_for_update(skip_locked=True)
    )
    if sync_job is None:
        db.rollback()
        raise PublishingJobLeaseLostError("Publishing job lease is no longer owned by this worker.")
    job = db.scalar(
        select(PublishingJob).where(PublishingJob.id == publishing_job_id).with_for_update()
    )
    if job is None:
        db.rollback()
        raise PublishingJobLeaseLostError("Publishing job record no longer exists.")
    draft = db.scalar(
        select(ProviderProductDraft).where(ProviderProductDraft.id == job.provider_product_draft_id)
    )
    if draft is None:
        db.rollback()
        raise RuntimeError("Publishing product draft no longer exists.")
    return sync_job, job, draft


def _create_result_from_status(status: ProviderProductStatus) -> ProviderProductCreateResult:
    return ProviderProductCreateResult(
        provider_product_id=status.provider_product_id,
        external_listing_id=status.external_listing_id,
        provider_product_url=status.provider_product_url,
        provider_fulfillment_url=status.provider_fulfillment_url,
        provider_status=status.provider_status,
        raw_provider_payload_json=status.raw_provider_payload_json,
    )


def _stage_at_least(current_stage: str | None, expected_stage: str) -> bool:
    order = {
        "queued": 0,
        "provider_product_saved": 1,
        "etsy_listing_created": 2,
        "etsy_metadata_synced": 3,
        "etsy_images_synced": 4,
        "completed": 5,
    }
    return order.get(str(current_stage or "queued"), 0) >= order[expected_stage]


def _snapshot_etsy_images(
    snapshot: dict[str, Any],
    draft: ProviderProductDraft,
) -> list[dict[str, Any]]:
    raw_images = snapshot.get("etsy_listing_images")
    if isinstance(raw_images, list):
        return sorted(
            (dict(item) for item in raw_images if isinstance(item, dict)),
            key=lambda item: (int(item.get("position") or 0), str(item.get("mockup_id") or "")),
        )
    return [
        {
            "mockup_id": mockup.id,
            "file_name": mockup.file_name,
            "content_type": mockup.content_type,
            "size_bytes": mockup.size_bytes,
            "storage_key": mockup.storage_key,
            "position": mockup.position,
        }
        for mockup in sorted(draft.mockups or [], key=lambda item: (item.position, item.id))
    ]


def _read_etsy_listing_images(
    image_records: list[dict[str, Any]],
):
    storage = get_storage_service()
    for rank, image in enumerate(image_records, start=1):
        file_name = str(image.get("file_name") or f"listing-image-{rank}")
        storage_key = str(image.get("storage_key") or "").strip()
        if not storage_key:
            raise RuntimeError(f"Marketplace image {rank} '{file_name}' has no saved storage key.")
        try:
            content = storage.read_bytes_limited(
                storage_key,
                max_bytes=settings.etsy_max_listing_image_bytes,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Marketplace image {rank} '{file_name}' exceeds the Etsy upload limit configured in Velora."
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Marketplace image {rank} '{file_name}' could not be read from Velora storage."
            ) from exc
        yield EtsyListingImageUpload(
            file_name=file_name,
            content_type=str(image.get("content_type") or "application/octet-stream"),
            content=content,
        )


def _validate_etsy_image_records(image_records: list[dict[str, Any]]) -> None:
    if len(image_records) > ETSY_LISTING_IMAGE_LIMIT:
        raise RuntimeError(
            f"Velora saved {len(image_records)} marketplace images, but Etsy accepts at most "
            f"{ETSY_LISTING_IMAGE_LIMIT}."
        )
    allowed_content_types = {"image/jpeg", "image/png", "image/webp"}
    for rank, image in enumerate(image_records, start=1):
        file_name = str(image.get("file_name") or f"listing-image-{rank}")
        size_bytes = int(image.get("size_bytes") or 0)
        content_type = str(image.get("content_type") or "").lower()
        if size_bytes <= 0:
            raise RuntimeError(f"Marketplace image {rank} '{file_name}' is empty.")
        if size_bytes > settings.etsy_max_listing_image_bytes:
            raise RuntimeError(
                f"Marketplace image {rank} '{file_name}' exceeds the Etsy upload limit configured in Velora."
            )
        if content_type not in allowed_content_types:
            raise RuntimeError(
                f"Marketplace image {rank} '{file_name}' has unsupported type '{content_type or 'unknown'}'."
            )


async def execute_publishing_job(job_id: str, *, lease_owner: str) -> dict[str, Any]:
    started_at = time.perf_counter()
    with SessionLocal() as db:
        job = db.scalar(select(PublishingJob).where(PublishingJob.id == job_id))
        if job is None:
            raise RuntimeError("Publishing job does not exist.")
        if job.status == "succeeded":
            return {
                "publishing_job_id": job.id,
                "provider_product_id": job.provider_product_id,
                "product_revision": job.product_revision,
            }
        organization_id = job.organization_id
        set_database_request_context(
            db,
            actor_id=None,
            organization_id=organization_id,
        )
        sync_job = db.scalar(select(SyncJob).where(SyncJob.id == job.sync_job_id))
        store_connection = db.scalar(
            select(ProviderStoreConnection).where(
                ProviderStoreConnection.id == job.provider_store_connection_id,
                ProviderStoreConnection.organization_id == job.organization_id,
                ProviderStoreConnection.deleted_at.is_(None),
            )
        )
        draft = db.scalar(
            select(ProviderProductDraft).where(
                ProviderProductDraft.id == job.provider_product_draft_id,
                ProviderProductDraft.organization_id == job.organization_id,
            )
        )
        if sync_job is None or store_connection is None or draft is None:
            raise RuntimeError("Publishing job is missing its lease envelope or provider store connection.")
        snapshot = dict(job.submitted_snapshot_json or {})
        provider_input = ProviderProductCreateInput.model_validate(snapshot.get("provider_input"))
        operation = job.operation
        attempt_count = sync_job.attempt_count
        provider_product_id = job.provider_product_id or snapshot.get("existing_provider_product_id")
        external_listing_id = (
            draft.external_listing_id
            or snapshot.get("existing_external_listing_id")
        )
        provider_product_url = draft.provider_product_url
        provider_fulfillment_url = draft.provider_fulfillment_url
        current_stage = job.stage
        is_etsy_storefront = store_connection.storefront_type == "etsy"
        provider = job.provider
        etsy_shop_id = store_connection.etsy_shop_id
        image_records = _snapshot_etsy_images(snapshot, draft)

    direct_etsy_update = is_etsy_storefront and bool(external_listing_id)
    create_result: ProviderProductCreateResult
    publish_result: ProviderPublishResult

    if direct_etsy_update:
        if not provider_product_id:
            raise PublishingStageError(
                "etsy_listing_handoff",
                RuntimeError("The saved Etsy listing is missing its POD provider product id."),
            )
        create_result = ProviderProductCreateResult(
            provider_product_id=str(provider_product_id),
            external_listing_id=str(external_listing_id),
            provider_product_url=provider_product_url,
            provider_fulfillment_url=provider_fulfillment_url,
            provider_status="published",
        )
        publish_result = ProviderPublishResult(**create_result.model_dump())
    else:
        try:
            with SessionLocal() as db:
                set_database_request_context(
                    db,
                    actor_id=None,
                    organization_id=organization_id,
                )
                store_connection = db.scalar(
                    select(ProviderStoreConnection).where(
                        ProviderStoreConnection.id == job.provider_store_connection_id,
                        ProviderStoreConnection.organization_id == organization_id,
                        ProviderStoreConnection.deleted_at.is_(None),
                    )
                )
                credentials = commerce._build_scoped_provider_credentials(
                    db,
                    organization_id=organization_id,
                    provider=provider,
                    store_connection=store_connection,
                )
                commerce._ensure_provider_credentials_complete(provider, credentials)
            adapter = get_provider_adapter(provider, credentials)  # type: ignore[arg-type]
        except Exception as exc:
            raise PublishingStageError("provider_configuration", exc) from exc

        create_result_or_none: ProviderProductCreateResult | None = None
        try:
            if provider_product_id and operation == "update":
                update_provider_product = getattr(adapter, "update_provider_product", None)
                if callable(update_provider_product):
                    try:
                        create_result_or_none = await update_provider_product(
                            provider_product_id=str(provider_product_id),
                            payload=provider_input,
                        )
                    except (AttributeError, NotImplementedError):
                        create_result_or_none = None
            elif provider_product_id:
                provider_status = await adapter.fetch_provider_product_status(
                    provider_product_id=str(provider_product_id)
                )
                create_result_or_none = _create_result_from_status(provider_status)
            elif attempt_count > 1:
                reconcile = getattr(adapter, "reconcile_provider_product", None)
                if callable(reconcile):
                    create_result_or_none = await reconcile(payload=provider_input)

            if create_result_or_none is None:
                create_result_or_none = await adapter.create_provider_product(provider_input)
        except Exception as exc:
            raise PublishingStageError("provider_product_save", exc) from exc
        create_result = create_result_or_none

        with SessionLocal() as db:
            set_database_request_context(db, actor_id=None, organization_id=organization_id)
            _, owned_job, draft = _load_owned_publishing_rows(
                db,
                publishing_job_id=job_id,
                lease_owner=lease_owner,
            )
            owned_job.provider_product_id = create_result.provider_product_id
            owned_job.stage = "provider_product_saved"
            draft.provider_product_id = create_result.provider_product_id
            draft.external_listing_id = create_result.external_listing_id or draft.external_listing_id
            draft.provider_product_url = create_result.provider_product_url or draft.provider_product_url
            draft.provider_fulfillment_url = (
                create_result.provider_fulfillment_url or draft.provider_fulfillment_url
            )
            draft.provider_status = create_result.provider_status
            draft.last_provider_sync_at = utc_now()
            if draft.external_listing_id:
                owned_job.stage = "etsy_listing_created"
            _persist_pod_product(
                db,
                draft=draft,
                job=owned_job,
                provider_status=create_result.provider_status or "created",
                provider_product_id=create_result.provider_product_id,
                external_listing_id=draft.external_listing_id,
                provider_product_url=draft.provider_product_url,
                provider_fulfillment_url=draft.provider_fulfillment_url,
                raw_provider_payload_json=create_result.raw_provider_payload_json,
            )
            db.commit()
            current_stage = owned_job.stage
            external_listing_id = draft.external_listing_id

        provider_status_name = str(create_result.provider_status or "").lower()
        if external_listing_id or provider_status_name in PUBLISHED_PROVIDER_STATUSES:
            publish_result = ProviderPublishResult(
                provider_product_id=create_result.provider_product_id,
                external_listing_id=external_listing_id,
                provider_product_url=create_result.provider_product_url,
                provider_fulfillment_url=create_result.provider_fulfillment_url,
                provider_status=("published" if external_listing_id else create_result.provider_status),
                raw_provider_payload_json=create_result.raw_provider_payload_json,
            )
        else:
            try:
                publish_result = await adapter.publish_provider_product(
                    provider_product_id=create_result.provider_product_id,
                )
            except Exception as exc:
                raise PublishingStageError("provider_storefront_publish", exc) from exc

        external_listing_id = publish_result.external_listing_id or external_listing_id
        provider_product_url = publish_result.provider_product_url or provider_product_url
        provider_fulfillment_url = (
            publish_result.provider_fulfillment_url or provider_fulfillment_url
        )
        with SessionLocal() as db:
            set_database_request_context(db, actor_id=None, organization_id=organization_id)
            _, owned_job, draft = _load_owned_publishing_rows(
                db,
                publishing_job_id=job_id,
                lease_owner=lease_owner,
            )
            draft.external_listing_id = external_listing_id or draft.external_listing_id
            draft.provider_product_url = provider_product_url or draft.provider_product_url
            draft.provider_fulfillment_url = provider_fulfillment_url or draft.provider_fulfillment_url
            draft.provider_status = publish_result.provider_status or draft.provider_status
            draft.last_provider_sync_at = utc_now()
            if draft.external_listing_id:
                owned_job.stage = "etsy_listing_created"
            _persist_pod_product(
                db,
                draft=draft,
                job=owned_job,
                provider_status=publish_result.provider_status or "published",
                provider_product_id=create_result.provider_product_id,
                external_listing_id=draft.external_listing_id,
                provider_product_url=draft.provider_product_url,
                provider_fulfillment_url=draft.provider_fulfillment_url,
                raw_provider_payload_json=(
                    publish_result.raw_provider_payload_json or create_result.raw_provider_payload_json
                ),
            )
            db.commit()
            current_stage = owned_job.stage
            external_listing_id = draft.external_listing_id

    if is_etsy_storefront:
        if not external_listing_id:
            raise PublishingStageError(
                "etsy_listing_handoff",
                RuntimeError("The POD provider did not return the connected Etsy listing id."),
            )

        with SessionLocal() as db:
            set_database_request_context(db, actor_id=None, organization_id=organization_id)
            _, owned_job, draft = _load_owned_publishing_rows(
                db,
                publishing_job_id=job_id,
                lease_owner=lease_owner,
            )
            if not _stage_at_least(owned_job.stage, "etsy_listing_created"):
                owned_job.stage = "etsy_listing_created"
                db.commit()
            current_stage = owned_job.stage
            refresh_token = commerce._get_etsy_refresh_token_for_shop(
                db,
                organization_id=organization_id,
                etsy_shop_id=etsy_shop_id,
            )

        if not _stage_at_least(current_stage, "etsy_metadata_synced"):
            try:
                sync_product_listing_to_etsy(
                    listing_id=str(external_listing_id),
                    etsy_shop_id=etsy_shop_id,
                    refresh_token=refresh_token,
                    title=provider_input.title,
                    description=provider_input.description,
                    tags=list(provider_input.tags),
                    retail_price=provider_input.retail_price,
                    sku=provider_input.sku,
                )
            except Exception as exc:
                raise PublishingStageError("etsy_metadata_sync", exc) from exc
            with SessionLocal() as db:
                set_database_request_context(db, actor_id=None, organization_id=organization_id)
                _, owned_job, _ = _load_owned_publishing_rows(
                    db,
                    publishing_job_id=job_id,
                    lease_owner=lease_owner,
                )
                owned_job.stage = "etsy_metadata_synced"
                db.commit()
                current_stage = owned_job.stage

        if not _stage_at_least(current_stage, "etsy_images_synced"):
            try:
                _validate_etsy_image_records(image_records)
                sync_product_listing_images_to_etsy(
                    listing_id=str(external_listing_id),
                    etsy_shop_id=etsy_shop_id,
                    refresh_token=refresh_token,
                    images=_read_etsy_listing_images(image_records),
                )
            except Exception as exc:
                raise PublishingStageError("etsy_image_sync", exc) from exc
            with SessionLocal() as db:
                set_database_request_context(db, actor_id=None, organization_id=organization_id)
                _, owned_job, _ = _load_owned_publishing_rows(
                    db,
                    publishing_job_id=job_id,
                    lease_owner=lease_owner,
                )
                owned_job.stage = "etsy_images_synced"
                db.commit()
        provider_product_url = build_etsy_listing_edit_url(str(external_listing_id))

    with SessionLocal() as db:
        set_database_request_context(db, actor_id=None, organization_id=organization_id)
        _, owned_job, draft = _load_owned_publishing_rows(
            db,
            publishing_job_id=job_id,
            lease_owner=lease_owner,
        )
        draft.status = "published"
        draft.publishing_status = "succeeded"
        draft.provider_status = publish_result.provider_status or draft.provider_status
        draft.external_listing_id = str(external_listing_id) if external_listing_id else None
        draft.provider_product_url = provider_product_url or draft.provider_product_url
        draft.provider_fulfillment_url = provider_fulfillment_url or draft.provider_fulfillment_url
        draft.last_provider_sync_at = utc_now()
        _persist_pod_product(
            db,
            draft=draft,
            job=owned_job,
            provider_status=publish_result.provider_status or "published",
            provider_product_id=create_result.provider_product_id,
            external_listing_id=draft.external_listing_id,
            provider_product_url=draft.provider_product_url,
            provider_fulfillment_url=draft.provider_fulfillment_url,
            raw_provider_payload_json=(
                publish_result.raw_provider_payload_json or create_result.raw_provider_payload_json
            ),
        )
        owned_job.status = "succeeded"
        owned_job.stage = "completed"
        owned_job.error_message = None
        owned_job.raw_result_json = (
            publish_result.raw_provider_payload_json or create_result.raw_provider_payload_json
        )
        owned_job.completed_at = utc_now()
        db.commit()

    log_event(
        publishing_logger,
        "publishing_job.succeeded",
        job_id=job_id,
        provider=provider,
        provider_product_id=create_result.provider_product_id,
        product_revision=provider_input.source_revision,
        attempt_count=attempt_count,
        duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
    )
    return {
        "publishing_job_id": job_id,
        "provider_product_id": create_result.provider_product_id,
        "product_revision": provider_input.source_revision,
    }


def run_publishing_job_background(job_id: str) -> None:
    from app.jobs.publishing import run_publishing_job

    run_publishing_job(job_id)
