from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.ai.compliance import EtsyComplianceError, normalize_generated_output, validate_etsy_output
from app.ai.media import prepare_ai_image_data_url
from app.ai.openrouter import OpenRouterProvider, OpenRouterResponseError
from app.ai.prompts import (
    PROMPT_VERSION,
    build_listing_fresh_quality_retry_prompt,
    build_listing_prompt,
    build_listing_repair_prompt,
    build_listing_structure_retry_prompt,
    normalized_input_hash,
)
from app.ai.schemas import ListingOutput
from app.core.actor import ActorContext
from app.core.config import settings
from app.core.distributed_rate_limit import (
    RateLimiterUnavailable,
    try_acquire_redis_sliding_window_slots,
)
from app.core.logging import get_logger, log_event
from app.db.models import AIGeneration, ProviderProductDraft
from app.models import AICapabilities, AIGenerationApplyRequest, AIGenerationRequest, AIGenerationSummary, Product
from app.services.serializers import to_product
from app.storage import get_storage_service


logger = get_logger(__name__)

_GENERATED_FIELDS = [
    "title",
    "description",
    "tags",
    "seo_title",
    "seo_description",
    "seo_keywords",
]


def get_ai_capabilities() -> AICapabilities:
    return AICapabilities(enabled=settings.ai_provider == "openrouter", model=settings.openrouter_model if settings.ai_provider == "openrouter" else None)


def _product(db: Session, actor: ActorContext, product_id: str) -> ProviderProductDraft:
    row = db.scalar(
        select(ProviderProductDraft)
        .options(selectinload(ProviderProductDraft.blueprint), selectinload(ProviderProductDraft.design_asset), selectinload(ProviderProductDraft.provider_store_connection))
        .where(ProviderProductDraft.id == product_id, ProviderProductDraft.organization_id == actor.organization_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Product draft not found.")
    return row


def _summary(row: AIGeneration) -> AIGenerationSummary:
    return AIGenerationSummary(
        id=row.id, product_id=row.provider_product_draft_id, source_product_revision=row.source_product_revision,
        status=row.status, output=row.output_json if row.status in {"completed", "accepted"} else None,
        warnings=row.warnings_json or [], error_code=row.error_code, error_message=row.error_message,
        created_at=row.created_at, completed_at=row.completed_at, accepted_at=row.accepted_at,
    )


def _safe_generation_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, EtsyComplianceError):
        return "quality_requirements_not_met", "AI could not meet the Etsy listing and SEO requirements. Regenerate to try again."
    if isinstance(exc, httpx.TimeoutException):
        return "provider_timeout", "AI generation timed out. Try again in a moment."
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            return "provider_rate_limited", "AI generation is temporarily rate-limited. Try again shortly."
        return "provider_rejected", "The AI provider could not process this generation. Try again in a moment."
    if isinstance(exc, httpx.RequestError):
        return "provider_unavailable", "AI generation is temporarily unavailable. Try again in a moment."
    if isinstance(exc, (OpenRouterResponseError, ValidationError)):
        return "provider_invalid_response", "AI returned an unreadable listing response. Regenerate to try again."
    if isinstance(exc, ValueError):
        return "design_image_invalid", "The saved design image could not be validated for AI generation. Re-upload a PNG, JPEG, or WebP and try again."
    return "generation_failed", "AI generation could not complete. Try again in a moment."


def _context(row: ProviderProductDraft) -> dict[str, Any]:
    blueprint = row.blueprint
    store = row.provider_store_connection
    return {
        "design_description": row.design_description,
        "current_listing": {"title": row.title, "description": row.description or "", "tags": row.tags_json or []},
        "blueprint": {"name": blueprint.name, "category": blueprint.category, "product_type": blueprint.product_type or "", "configuration": blueprint.configuration_summary or ""},
        "storefront": {"type": store.storefront_type, "label": store.label},
    }


def _without_generation_anchors(
    context: dict[str, Any],
    generation_fields: set[str],
) -> dict[str, Any]:
    clean = dict(context)
    current_listing = dict(context.get("current_listing") or {})
    if "title" in generation_fields:
        current_listing["title"] = ""
    if "tags" in generation_fields:
        current_listing["tags"] = []
    clean["current_listing"] = current_listing

    previous_suggestion = dict(context.get("previous_suggestion") or {})
    for field in ("title", "tags"):
        if field in generation_fields:
            previous_suggestion.pop(field, None)
    if previous_suggestion:
        clean["previous_suggestion"] = previous_suggestion
    else:
        clean.pop("previous_suggestion", None)
    return clean


def _previous_output(
    db: Session,
    *,
    row: ProviderProductDraft,
) -> dict[str, Any]:
    previous = db.scalar(
        select(AIGeneration)
        .where(
            AIGeneration.organization_id == row.organization_id,
            AIGeneration.provider_product_draft_id == row.id,
            AIGeneration.status.in_(["completed", "accepted"]),
            AIGeneration.output_json.is_not(None),
        )
        .order_by(AIGeneration.created_at.desc())
    )
    if previous is None or not previous.output_json:
        return {}
    return previous.output_json


def _baseline_output(
    row: ProviderProductDraft,
    previous_output: dict[str, Any],
) -> ListingOutput:
    values: dict[str, Any] = {
        "title": row.title,
        "description": row.description or "",
        "tags": row.tags_json or [],
        "seo_title": row.seo_title or "",
        "seo_description": row.seo_description or "",
        "seo_keywords": row.seo_keywords_json or [],
    }
    for field in ListingOutput.model_fields:
        if field in previous_output:
            values[field] = previous_output[field]
    return ListingOutput.model_validate(values)


def _merge_targeted_output(
    baseline: ListingOutput,
    targeted_output: dict[str, Any],
) -> ListingOutput:
    return ListingOutput.model_validate(
        {**baseline.model_dump(), **targeted_output}
    )


def _require_targeted_variation(
    output: ListingOutput,
    previous_suggestion: dict[str, Any],
) -> None:
    unchanged = [
        field
        for field, previous_value in previous_suggestion.items()
        if getattr(output, field) == previous_value
    ]
    if unchanged:
        raise EtsyComplianceError(
            "regenerated fields must be meaningfully different from the previous suggestion: "
            + ", ".join(unchanged)
        )


def _quality_repair_fields(validation_error: EtsyComplianceError) -> list[str]:
    fields: set[str] = set()
    for violation in str(validation_error).split("; "):
        normalized = violation.casefold()
        if normalized.startswith("title "):
            fields.add("title")
        elif normalized.startswith("description "):
            fields.add("description")
        elif normalized.startswith("tags ") or normalized.startswith("each tag "):
            fields.add("tags")
        elif normalized.startswith("seo title "):
            fields.add("seo_title")
        elif normalized.startswith("seo description "):
            fields.add("seo_description")
        elif normalized.startswith("seo keywords ") or normalized.startswith("each seo keyword "):
            fields.add("seo_keywords")
        elif normalized.startswith("seo content "):
            fields.update({"seo_title", "seo_description"})
    return [field for field in _GENERATED_FIELDS if field in fields]


def _rate_limit_error(*, retry_after_seconds: int) -> HTTPException:
    retry_after = max(1, retry_after_seconds)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="AI generation limit reached. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


def _enforce_generation_limits(
    db: Session,
    *,
    actor: ActorContext,
    now: datetime,
) -> None:
    window_start = now - timedelta(hours=1)
    organization_count = db.scalar(
        select(func.count())
        .select_from(AIGeneration)
        .where(
            AIGeneration.organization_id == actor.organization_id,
            AIGeneration.created_at >= window_start,
        )
    ) or 0
    if organization_count >= settings.ai_generation_limit_per_hour:
        raise _rate_limit_error(retry_after_seconds=3600)

    requester_count = db.scalar(
        select(func.count())
        .select_from(AIGeneration)
        .where(
            AIGeneration.organization_id == actor.organization_id,
            AIGeneration.requested_by_user_id == actor.actor_id,
            AIGeneration.created_at >= window_start,
        )
    ) or 0
    if requester_count >= settings.ai_generation_limit_per_user_per_hour:
        raise _rate_limit_error(retry_after_seconds=3600)

    try:
        allowed, retry_after = try_acquire_redis_sliding_window_slots(
            redis_keys=[
                f"ratelimit:ai:generation:organization:{actor.organization_id}",
                (
                    "ratelimit:ai:generation:user:"
                    f"{actor.organization_id}:{actor.actor_id}"
                ),
            ],
            limit=settings.ai_generation_burst_limit,
            window_seconds=settings.ai_generation_burst_window_seconds,
        )
    except RateLimiterUnavailable:
        log_event(
            logger,
            "ai_generation.burst_limiter_unavailable",
            organization_id=actor.organization_id,
            actor_id=actor.actor_id,
        )
        return
    if not allowed:
        raise _rate_limit_error(retry_after_seconds=math.ceil(retry_after))


def generate_listing(db: Session, *, actor: ActorContext, product_id: str, payload: AIGenerationRequest) -> AIGenerationSummary:
    if settings.ai_provider != "openrouter":
        raise HTTPException(status_code=503, detail="AI listing generation is not configured in this environment.")
    row = _product(db, actor, product_id)
    if payload.expected_product_revision != row.revision:
        raise HTTPException(status_code=409, detail="This product changed. Save or refresh before generating.")
    if row.provider_store_connection.storefront_type != "etsy":
        raise HTTPException(status_code=422, detail="AI listing generation currently supports Etsy stores only.")
    if not (row.design_description or "").strip():
        raise HTTPException(status_code=422, detail="Add a design description before generating a listing.")
    now = datetime.now(timezone.utc)
    existing = db.scalar(select(AIGeneration).where(AIGeneration.organization_id == actor.organization_id, AIGeneration.client_request_id == payload.client_request_id))
    if existing is not None:
        if existing.provider_product_draft_id != row.id:
            raise HTTPException(status_code=409, detail="That AI request id is already in use.")
        pending_cutoff = now - timedelta(
            seconds=settings.ai_generation_pending_timeout_seconds
        )
        existing_started_at = existing.started_at
        if (
            existing_started_at is not None
            and existing_started_at.tzinfo is None
        ):
            existing_started_at = existing_started_at.replace(
                tzinfo=timezone.utc
            )
        if (
            existing.status == "pending"
            and existing_started_at is not None
            and existing_started_at <= pending_cutoff
        ):
            existing.status = "failed"
            existing.error_code = "generation_abandoned"
            existing.error_message = (
                "The previous AI request did not finish. Generate again to retry."
            )
            existing.completed_at = now
            db.commit()
        return _summary(existing)
    _enforce_generation_limits(db, actor=actor, now=now)
    if not row.design_asset or row.design_asset.size_bytes > settings.ai_max_source_image_bytes:
        raise HTTPException(status_code=422, detail="The primary design image is missing or exceeds the AI source-image limit.")
    context = _context(row)
    previous_output: dict[str, Any] = {}
    previous_suggestion: dict[str, Any] = {}
    if payload.regenerate_fields:
        context["regenerate_fields"] = payload.regenerate_fields
        previous_output = _previous_output(db, row=row)
        previous_suggestion = {
            field: previous_output[field]
            for field in payload.regenerate_fields
            if field in previous_output
        }
        if previous_suggestion:
            context["previous_suggestion"] = previous_suggestion
    context = _without_generation_anchors(
        context,
        set(payload.regenerate_fields or _GENERATED_FIELDS),
    )
    generation = AIGeneration(
        organization_id=actor.organization_id, provider_product_draft_id=row.id, provider_store_connection_id=row.provider_store_connection_id,
        client_request_id=payload.client_request_id, requested_by_user_id=actor.actor_id,
        source_product_revision=row.revision, provider_key="openrouter",
        model=settings.openrouter_model or "", prompt_version=PROMPT_VERSION,
        input_hash=normalized_input_hash(context, row.design_asset.checksum), status="pending", started_at=datetime.now(timezone.utc),
    )
    db.add(generation)
    db.commit()
    started_monotonic = time.monotonic()
    log_event(
        logger,
        "ai_generation.started",
        organization_id=actor.organization_id,
        actor_id=actor.actor_id,
        product_id=row.id,
        generation_id=generation.id,
        provider=generation.provider_key,
        model=generation.model,
        prompt_version=generation.prompt_version,
        status=generation.status,
    )
    result = None
    retry_count = 0
    image: bytes | None = None
    try:
        image = get_storage_service().read_bytes_limited(
            row.design_asset.storage_key,
            max_bytes=settings.ai_max_source_image_bytes,
        )
        ai_image_data_url = prepare_ai_image_data_url(
            image,
            row.design_asset.content_type,
            max_bytes=settings.ai_max_image_bytes,
            max_dimension=settings.ai_max_image_dimension,
            max_source_pixels=settings.ai_max_source_image_pixels,
            max_full_decode_pixels=settings.ai_max_full_decode_pixels,
        )
        provider = OpenRouterProvider()
        targeted_fields = set(payload.regenerate_fields)
        baseline = _baseline_output(row, previous_output)
        try:
            prompt = build_listing_prompt(
                context, regenerate_fields=payload.regenerate_fields
            )
            if payload.regenerate_fields:
                result = provider.generate_targeted(
                    prompt=prompt,
                    fields=payload.regenerate_fields,
                    image_data_url=ai_image_data_url,
                )
            else:
                result = provider.generate(
                    prompt=prompt,
                    image_data_url=ai_image_data_url,
                )
            retry_count += result.retry_count
        except (OpenRouterResponseError, ValidationError) as exc:
            retry_count += 1
            log_event(
                logger,
                "ai_generation.structure_retry",
                organization_id=actor.organization_id,
                product_id=row.id,
                generation_id=generation.id,
                model=generation.model,
                failure_type=type(exc).__name__,
            )
            retry_prompt = build_listing_structure_retry_prompt(
                context, regenerate_fields=payload.regenerate_fields
            )
            if payload.regenerate_fields:
                result = provider.generate_targeted(
                    prompt=retry_prompt,
                    fields=payload.regenerate_fields,
                )
            else:
                result = provider.generate(prompt=retry_prompt)
            retry_count += result.retry_count
        output = (
            _merge_targeted_output(baseline, result.output)
            if payload.regenerate_fields
            else result.output
        )
        for quality_attempt in range(3):
            try:
                output = validate_etsy_output(
                    normalize_generated_output(
                        output,
                        generation_fields=targeted_fields or None,
                    ),
                    generation_fields=targeted_fields or None,
                )
                _require_targeted_variation(output, previous_suggestion)
                break
            except EtsyComplianceError as validation_error:
                if quality_attempt == 2:
                    raise
                log_event(
                    logger,
                    "ai_generation.quality_repair",
                    organization_id=actor.organization_id,
                    product_id=row.id,
                    generation_id=generation.id,
                    model=generation.model,
                    repair_attempt=quality_attempt + 1,
                )
                repair_fields = payload.regenerate_fields or _quality_repair_fields(
                    validation_error
                )
                focused_repair = bool(repair_fields) and set(repair_fields) != set(
                    _GENERATED_FIELDS
                )
                clean_focused_retry = focused_repair and set(repair_fields).issubset(
                    {"title", "tags"}
                )
                previous_repair_output = (
                    {}
                    if clean_focused_retry
                    else {
                        field: getattr(output, field)
                        for field in repair_fields
                    }
                    if focused_repair
                    else result.output
                    if payload.regenerate_fields
                    else result.output.model_dump()
                )
                repair_prompt = (
                    build_listing_fresh_quality_retry_prompt(
                        context,
                        regenerate_fields=repair_fields,
                    )
                    if clean_focused_retry
                    else build_listing_repair_prompt(
                        previous_repair_output,
                        validation_error=str(validation_error),
                        regenerate_fields=repair_fields if focused_repair else None,
                    )
                )
                if focused_repair:
                    result = provider.generate_targeted(
                        prompt=repair_prompt,
                        fields=repair_fields,
                    )
                    output = _merge_targeted_output(output, result.output)
                else:
                    result = provider.generate(prompt=repair_prompt)
                    output = result.output
                retry_count += 1 + result.retry_count
        generation.output_json = output.model_dump()
        generation.warnings_json = output.warnings
        generation.usage_json = {**result.usage, "retry_count": retry_count}
        generation.provider_request_id = result.provider_request_id
        generation.status = "completed"
        generation.completed_at = datetime.now(timezone.utc)
        db.commit()
        log_event(
            logger,
            "ai_generation.completed",
            organization_id=actor.organization_id,
            actor_id=actor.actor_id,
            product_id=row.id,
            generation_id=generation.id,
            provider=generation.provider_key,
            model=generation.model,
            prompt_version=generation.prompt_version,
            status=generation.status,
            latency_ms=round((time.monotonic() - started_monotonic) * 1000),
            prompt_tokens=(generation.usage_json or {}).get("prompt_tokens"),
            completion_tokens=(generation.usage_json or {}).get(
                "completion_tokens"
            ),
            total_tokens=(generation.usage_json or {}).get("total_tokens"),
            retry_count=retry_count,
        )
    except Exception as exc:
        db.rollback()
        generation = db.get(AIGeneration, generation.id)
        if generation is None:
            raise
        error_code, error_message = _safe_generation_failure(exc)
        generation.status = "failed"
        generation.error_code = error_code
        generation.error_message = error_message
        if result is not None:
            generation.usage_json = {**result.usage, "retry_count": retry_count}
            generation.provider_request_id = result.provider_request_id
        generation.completed_at = datetime.now(timezone.utc)
        db.commit()
        log_event(
            logger,
            "ai_generation.failed",
            organization_id=actor.organization_id,
            actor_id=actor.actor_id,
            product_id=row.id,
            generation_id=generation.id,
            provider=generation.provider_key,
            model=generation.model,
            prompt_version=generation.prompt_version,
            status=generation.status,
            latency_ms=round((time.monotonic() - started_monotonic) * 1000),
            retry_count=retry_count,
            error_code=generation.error_code,
        )
    finally:
        image = None
    return _summary(generation)


def list_generations(db: Session, *, actor: ActorContext, product_id: str) -> list[AIGenerationSummary]:
    _product(db, actor, product_id)
    rows = db.scalars(select(AIGeneration).where(AIGeneration.organization_id == actor.organization_id, AIGeneration.provider_product_draft_id == product_id).order_by(AIGeneration.created_at.desc())).all()
    return [_summary(row) for row in rows]


def apply_generation(db: Session, *, actor: ActorContext, product_id: str, generation_id: str, payload: AIGenerationApplyRequest) -> tuple[Product, AIGenerationSummary]:
    product = _product(db, actor, product_id)
    generation = db.scalar(select(AIGeneration).where(AIGeneration.id == generation_id, AIGeneration.organization_id == actor.organization_id, AIGeneration.provider_product_draft_id == product.id))
    if generation is None:
        raise HTTPException(status_code=404, detail="AI generation not found.")
    if generation.status not in {"completed", "accepted"}:
        raise HTTPException(status_code=409, detail="This AI generation cannot be applied.")
    if payload.expected_product_revision != product.revision or generation.source_product_revision != product.revision:
        raise HTTPException(status_code=409, detail="This product changed. Refresh and regenerate the listing.")
    fields = payload.model_dump(exclude={"expected_product_revision"}, exclude_none=True)
    try:
        output = validate_etsy_output(
            ListingOutput(
                title=fields.get("title", product.title), description=fields.get("description", product.description or ""),
                tags=fields.get("tags", product.tags_json or []), seo_title=fields.get("seo_title", product.seo_title or ""),
                seo_description=fields.get("seo_description", product.seo_description or ""), seo_keywords=fields.get("seo_keywords", product.seo_keywords_json or []),
            ),
            require_generation_quality=False,
        )
    except EtsyComplianceError as exc:
        raise HTTPException(status_code=422, detail="Selected listing content is outside Etsy limits.") from exc
    for field in fields:
        value = getattr(output, field)
        setattr(product, "tags_json" if field == "tags" else "seo_keywords_json" if field == "seo_keywords" else field, value)
    product.revision += 1
    product.last_ai_generation_id = generation.id
    generation.status = "accepted"
    generation.accepted_output_json = {key: getattr(output, key) for key in fields}
    generation.accepted_fields_json = list(fields)
    generation.accepted_by_user_id = actor.actor_id
    generation.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(product)
    return to_product(product), _summary(generation)


def prune_unaccepted_generations(db: Session, *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=30)
    rows = db.scalars(select(AIGeneration).where(AIGeneration.status.in_(["completed", "failed"]), AIGeneration.completed_at < cutoff)).all()
    for row in rows:
        row.output_json = row.warnings_json = row.usage_json = None
        row.error_message = None
    db.commit()
    return len(rows)
