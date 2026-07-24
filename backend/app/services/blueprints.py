from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

import app.services.provider_connections as commerce
from app.core.actor import ActorContext
from app.core.logging import get_logger, log_event
from app.db.models import ProductBlueprint
from app.models import (
    Blueprint,
    BlueprintCreateRequest,
    BlueprintUpdateRequest,
    BlueprintValidationResponse,
)
from app.providers.base import ReferenceSnapshotResult, ReferenceValidationResult
from app.services.serializers import to_blueprint


blueprint_logger = get_logger("blueprints")


def _get_blueprint_or_404(
    db: Session,
    *,
    actor: ActorContext,
    blueprint_id: str,
) -> ProductBlueprint:
    row = db.scalar(
        select(ProductBlueprint)
        .options(
            selectinload(ProductBlueprint.provider_store_connection),
            selectinload(ProductBlueprint.drafts),
        )
        .where(
            ProductBlueprint.id == blueprint_id,
            ProductBlueprint.organization_id == actor.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Blueprint not found.")
    return row


async def _validate_blueprint_reference_internal(
    db: Session,
    *,
    actor: ActorContext,
    blueprint: ProductBlueprint,
) -> tuple[ReferenceValidationResult, ReferenceSnapshotResult]:
    store_connection = commerce._get_store_connection_or_404(db, actor=actor, connection_id=blueprint.provider_store_connection_id)
    credentials = commerce._build_scoped_provider_credentials(
        db,
        organization_id=actor.organization_id,
        provider=blueprint.provider,
        store_connection=store_connection,
    )
    commerce._ensure_provider_credentials_complete(blueprint.provider, credentials)
    adapter = commerce.get_provider_adapter(blueprint.provider, credentials)  # type: ignore[arg-type]
    log_event(
        blueprint_logger,
        "blueprint.reference.validation.started",
        verbose_only=True,
        organization_id=actor.organization_id,
        blueprint_id=blueprint.id,
        provider=blueprint.provider,
        provider_store_connection_id=store_connection.id,
    )
    try:
        validation = await adapter.validate_reference(
            reference_type=blueprint.reference_type,
            reference_value=blueprint.reference_value,
        )
        snapshot = await adapter.fetch_reference_snapshot(
            reference_type=validation.reference_type,
            reference_value=validation.normalized_reference_value,
            provider_resource_id=validation.provider_resource_id,
        )
    except Exception as exc:
        commerce._raise_provider_action_error(
            provider=blueprint.provider,
            action="validating this blueprint reference",
            exc=exc,
        )
    blueprint.reference_type = validation.reference_type
    blueprint.reference_value = validation.normalized_reference_value
    blueprint.provider_resource_id = validation.provider_resource_id
    blueprint.provider_display_name = snapshot.provider_display_name or validation.provider_display_name
    blueprint.provider_snapshot_json = snapshot.provider_snapshot_json
    blueprint.product_type = snapshot.product_type
    blueprint.configuration_summary = snapshot.configuration_summary
    blueprint.variant_count = snapshot.variant_count
    blueprint.base_cost_amount = Decimal(str(snapshot.base_cost_amount)) if snapshot.base_cost_amount is not None else None
    blueprint.currency = snapshot.currency
    blueprint.validated_at = commerce.utc_now()
    if snapshot.placement_config_json and not blueprint.placement_config_json:
        blueprint.placement_config_json = snapshot.placement_config_json
    if snapshot.base_title and not blueprint.base_title:
        blueprint.base_title = snapshot.base_title
    if snapshot.base_description and not blueprint.base_description:
        blueprint.base_description = snapshot.base_description
    if snapshot.base_tags and not blueprint.base_tags_json:
        blueprint.base_tags_json = snapshot.base_tags
    blueprint.status = "active"
    log_event(
        blueprint_logger,
        "blueprint.reference.validated",
        verbose_only=True,
        organization_id=actor.organization_id,
        blueprint_id=blueprint.id,
        provider=blueprint.provider,
        provider_resource_id=validation.provider_resource_id,
        variant_count=snapshot.variant_count,
        has_snapshot=bool(snapshot.provider_snapshot_json),
    )
    return validation, snapshot


async def create_blueprint(
    db: Session,
    *,
    actor: ActorContext,
    payload: BlueprintCreateRequest,
) -> Blueprint:
    store_connection = commerce._get_store_connection_or_404(db, actor=actor, connection_id=payload.provider_store_connection_id)
    row = ProductBlueprint(
        organization_id=actor.organization_id,
        provider=store_connection.provider,
        provider_store_connection_id=store_connection.id,
        name=payload.name.strip(),
        category=payload.category.strip(),
        status=payload.status,
        reference_type=payload.reference_type.strip(),
        reference_value=payload.reference_value.strip(),
        product_code=(payload.product_code or "").strip() or None,
        placement_config_json=payload.placement_config_json,
        base_title=(payload.base_title or "").strip() or None,
        base_description=(payload.base_description or "").strip() or None,
        base_tags_json=payload.base_tags,
        basic_design_info_json=payload.basic_design_info_json,
    )
    db.add(row)
    db.flush()
    await _validate_blueprint_reference_internal(db, actor=actor, blueprint=row)
    db.commit()
    db.refresh(row)
    row = _get_blueprint_or_404(db, actor=actor, blueprint_id=row.id)
    log_event(
        blueprint_logger,
        "blueprint.created",
        verbose_only=True,
        organization_id=actor.organization_id,
        blueprint_id=row.id,
        provider=row.provider,
        provider_store_connection_id=row.provider_store_connection_id,
        status=row.status,
    )
    return to_blueprint(row)


def list_blueprints(db: Session, *, actor: ActorContext) -> list[Blueprint]:
    rows = db.scalars(
        select(ProductBlueprint)
        .options(selectinload(ProductBlueprint.provider_store_connection), selectinload(ProductBlueprint.drafts))
        .where(ProductBlueprint.organization_id == actor.organization_id)
        .order_by(ProductBlueprint.created_at.desc())
    ).all()
    return [to_blueprint(row) for row in rows]


def get_blueprint(db: Session, *, actor: ActorContext, blueprint_id: str) -> Blueprint:
    return to_blueprint(_get_blueprint_or_404(db, actor=actor, blueprint_id=blueprint_id))


async def validate_blueprint_reference(
    db: Session,
    *,
    actor: ActorContext,
    blueprint_id: str,
) -> BlueprintValidationResponse:
    row = _get_blueprint_or_404(db, actor=actor, blueprint_id=blueprint_id)
    validation, _snapshot = await _validate_blueprint_reference_internal(db, actor=actor, blueprint=row)
    db.commit()
    db.refresh(row)
    refreshed = _get_blueprint_or_404(db, actor=actor, blueprint_id=blueprint_id)
    return BlueprintValidationResponse(
        blueprint=to_blueprint(refreshed),
        validation_status="validated",
        normalized_reference_value=validation.normalized_reference_value,
        provider_resource_id=validation.provider_resource_id,
    )


def update_blueprint(
    db: Session,
    *,
    actor: ActorContext,
    blueprint_id: str,
    payload: BlueprintUpdateRequest,
) -> Blueprint:
    row = _get_blueprint_or_404(db, actor=actor, blueprint_id=blueprint_id)
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.category is not None:
        row.category = payload.category.strip()
    if payload.product_code is not None:
        row.product_code = payload.product_code.strip() or None
    if payload.placement_config_json is not None:
        row.placement_config_json = payload.placement_config_json
    if payload.base_title is not None:
        row.base_title = payload.base_title.strip() or None
    if payload.base_description is not None:
        row.base_description = payload.base_description.strip() or None
    if payload.base_tags is not None:
        row.base_tags_json = payload.base_tags
    if payload.basic_design_info_json is not None:
        row.basic_design_info_json = payload.basic_design_info_json
    if payload.status is not None:
        row.status = payload.status
    db.commit()
    db.refresh(row)
    log_event(
        blueprint_logger,
        "blueprint.updated",
        verbose_only=True,
        organization_id=actor.organization_id,
        blueprint_id=row.id,
        provider=row.provider,
        status=row.status,
    )
    return to_blueprint(_get_blueprint_or_404(db, actor=actor, blueprint_id=blueprint_id))


def delete_blueprint(db: Session, *, actor: ActorContext, blueprint_id: str) -> None:
    row = _get_blueprint_or_404(db, actor=actor, blueprint_id=blueprint_id)
    if row.drafts:
        raise HTTPException(status_code=409, detail="Blueprint still has product drafts.")
    db.delete(row)
    db.commit()
    log_event(
        blueprint_logger,
        "blueprint.deleted",
        verbose_only=True,
        organization_id=actor.organization_id,
        blueprint_id=blueprint_id,
        provider=row.provider,
    )
