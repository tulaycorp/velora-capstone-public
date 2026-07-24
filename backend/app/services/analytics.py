from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Integer, case, cast, exists, func, literal, or_, select
from sqlalchemy.orm import Session

import app.services.provider_connections as commerce
from app.core.actor import ActorContext
from app.core.config import settings
from app.db.models import (
    AnalyticsSnapshot,
    Mockup,
    Order,
    ProviderProductDraft,
    ProviderStoreConnection,
    PublishingJob,
)
from app.models import (
    AnalyticsOverview,
    AnalyticsScope,
    CatalogHealth,
    CatalogIssueCounts,
    CatalogNeedsAttentionItem,
    CatalogStatusCounts,
    EtsySnapshot,
    RecentActivity,
    StoreRollupRow,
    WorkflowHealth,
    WorkflowLatestFailure,
    WorkspaceAnalyticsResponse,
)

ATTENTION_ITEM_LIMIT = 5
TRIMMED_ERROR_LENGTH = 160
ETSY_SNAPSHOT_PROVIDER = "etsy"
ETSY_SNAPSHOT_SCOPE = "organization"


@dataclass(frozen=True)
class ProviderSnapshotRefreshResult:
    outcome: str
    fetched_shop_count: int
    failed_shop_count: int
    failure_summary: str | None = None


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _latest_timestamp(*values: datetime | None) -> datetime | None:
    normalized = [_coerce_utc(value) for value in values if value is not None]
    return max(normalized) if normalized else None


def _trim_error_message(value: str | None) -> str | None:
    message = " ".join((value or "").split()).strip()
    if not message:
        return None
    if len(message) <= TRIMMED_ERROR_LENGTH:
        return message
    return f"{message[:TRIMMED_ERROR_LENGTH - 1].rstrip()}…"


def _as_float(value: Decimal | float | int | None) -> float | None:
    return float(value) if value is not None else None


def _build_scope(*, store_connection: ProviderStoreConnection | None) -> AnalyticsScope:
    if store_connection is None:
        return AnalyticsScope(label="All stores")
    return AnalyticsScope(
        store_connection_id=store_connection.id,
        label=store_connection.label,
        provider=store_connection.provider,  # type: ignore[arg-type]
        storefront_type=store_connection.storefront_type,  # type: ignore[arg-type]
        is_all_stores=False,
    )


def _tag_count_expression(db: Session):
    dialect_name = db.get_bind().dialect.name
    function = func.jsonb_array_length if dialect_name == "postgresql" else func.json_array_length
    return func.coalesce(function(ProviderProductDraft.tags_json), 0)


def _draft_issue_expressions(db: Session) -> dict[str, Any]:
    has_mockup = exists(
        select(Mockup.id).where(
            Mockup.provider_product_draft_id == ProviderProductDraft.id,
            Mockup.organization_id == ProviderProductDraft.organization_id,
        )
    )
    expressions = {
        "missing_description": or_(
            ProviderProductDraft.description.is_(None),
            func.length(func.trim(ProviderProductDraft.description)) == 0,
        ),
        "low_tags": _tag_count_expression(db) < 5,
        "missing_retail_price": ProviderProductDraft.retail_price.is_(None),
        "missing_sku": or_(
            ProviderProductDraft.sku.is_(None),
            func.length(func.trim(ProviderProductDraft.sku)) == 0,
        ),
        "zero_mockups": ~has_mockup,
        "failed_publish": ProviderProductDraft.publishing_status == "failed",
    }
    expressions["issue_score"] = sum(
        cast(expressions[key], Integer)
        for key in (
            "missing_description",
            "low_tags",
            "missing_retail_price",
            "missing_sku",
            "zero_mockups",
            "failed_publish",
        )
    )
    return expressions


def _scope_clause(model: type[Any], store_connection_id: str | None):
    if store_connection_id is None:
        return literal(True)
    return model.provider_store_connection_id == store_connection_id


def _count_when(condition: Any):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _build_catalog_health(
    db: Session,
    *,
    organization_id: str,
    store_connection_id: str | None,
) -> tuple[CatalogHealth, int, int]:
    issues = _draft_issue_expressions(db)
    scope_clause = _scope_clause(ProviderProductDraft, store_connection_id)
    aggregate = db.execute(
        select(
            _count_when(ProviderProductDraft.status == "draft"),
            _count_when(ProviderProductDraft.status == "ready"),
            _count_when(ProviderProductDraft.status == "published"),
            _count_when(ProviderProductDraft.publishing_status == "failed"),
            _count_when(issues["missing_description"]),
            _count_when(issues["low_tags"]),
            _count_when(issues["missing_retail_price"]),
            _count_when(issues["missing_sku"]),
            _count_when(issues["zero_mockups"]),
            _count_when(issues["issue_score"] > 0),
            _count_when(ProviderProductDraft.created_at >= datetime.now(timezone.utc) - timedelta(days=30)),
        ).where(
            ProviderProductDraft.organization_id == organization_id,
            scope_clause,
        )
    ).one()

    attention_rows = db.execute(
        select(
            ProviderProductDraft.id,
            ProviderProductDraft.title,
            ProviderStoreConnection.label,
            ProviderProductDraft.status,
            ProviderProductDraft.publishing_status,
            ProviderProductDraft.updated_at,
            issues["missing_description"].label("missing_description"),
            issues["low_tags"].label("low_tags"),
            issues["missing_retail_price"].label("missing_retail_price"),
            issues["missing_sku"].label("missing_sku"),
            issues["zero_mockups"].label("zero_mockups"),
            issues["failed_publish"].label("failed_publish"),
            issues["issue_score"].label("issue_score"),
        )
        .join(
            ProviderStoreConnection,
            ProviderStoreConnection.id == ProviderProductDraft.provider_store_connection_id,
        )
        .where(
            ProviderProductDraft.organization_id == organization_id,
            scope_clause,
            issues["issue_score"] > 0,
        )
        .order_by(
            issues["issue_score"].desc(),
            ProviderProductDraft.updated_at.asc(),
            ProviderProductDraft.title.asc(),
        )
        .limit(ATTENTION_ITEM_LIMIT)
    ).all()

    needs_attention: list[CatalogNeedsAttentionItem] = []
    for row in attention_rows:
        issue_labels = [
            label
            for key, label in (
                ("missing_description", "Missing description"),
                ("low_tags", "Fewer than 5 tags"),
                ("missing_retail_price", "Missing retail price"),
                ("missing_sku", "Missing SKU"),
                ("zero_mockups", "No mockups"),
                ("failed_publish", "Failed publish"),
            )
            if bool(row._mapping[key])
        ]
        needs_attention.append(
            CatalogNeedsAttentionItem(
                product_id=row.id,
                title=row.title,
                provider_store_label=row.label,
                status=row.status,
                publishing_status=row.publishing_status,
                issue_count=len(issue_labels),
                issues=issue_labels,
                updated_at=_coerce_utc(row.updated_at),
            )
        )

    return (
        CatalogHealth(
            status_counts=CatalogStatusCounts(
                draft_count=int(aggregate[0]),
                ready_count=int(aggregate[1]),
                published_count=int(aggregate[2]),
                failed_publish_count=int(aggregate[3]),
            ),
            issue_counts=CatalogIssueCounts(
                missing_description_count=int(aggregate[4]),
                low_tag_count_count=int(aggregate[5]),
                missing_retail_price_count=int(aggregate[6]),
                missing_sku_count=int(aggregate[7]),
                zero_mockups_count=int(aggregate[8]),
            ),
            needs_attention=needs_attention,
        ),
        int(aggregate[9]),
        int(aggregate[10]),
    )


def _build_recent_activity(
    db: Session,
    *,
    organization_id: str,
    store_connection_id: str | None,
    now: datetime,
    new_drafts_last_30_days: int,
) -> RecentActivity:
    cutoff_7 = now - timedelta(days=7)
    cutoff_30 = now - timedelta(days=30)
    order_activity_at = func.coalesce(Order.order_created_at, Order.created_at)
    order_scope = _scope_clause(Order, store_connection_id)
    amount = func.coalesce(Order.retail_amount, Order.total_amount)
    currency = func.nullif(func.trim(Order.currency), "")
    order_aggregate = db.execute(
        select(
            _count_when(order_activity_at >= cutoff_7),
            _count_when(order_activity_at >= cutoff_30),
            func.coalesce(func.sum(case((order_activity_at >= cutoff_30, amount), else_=0)), 0),
            func.count(func.distinct(case((order_activity_at >= cutoff_30, currency), else_=None))),
            func.min(case((order_activity_at >= cutoff_30, currency), else_=None)),
        ).where(Order.organization_id == organization_id, order_scope)
    ).one()

    successful_publishes = db.scalar(
        select(_count_when(PublishingJob.status == "succeeded")).where(
            PublishingJob.organization_id == organization_id,
            _scope_clause(PublishingJob, store_connection_id),
            func.coalesce(
                PublishingJob.completed_at,
                PublishingJob.updated_at,
                PublishingJob.created_at,
            )
            >= cutoff_30,
        )
    )
    currency_count = int(order_aggregate[3])
    return RecentActivity(
        orders_last_7_days=int(order_aggregate[0]),
        orders_last_30_days=int(order_aggregate[1]),
        revenue_last_30_days=round(_as_float(order_aggregate[2]) or 0.0, 2),
        revenue_currency=order_aggregate[4] if currency_count == 1 else None,
        revenue_is_mixed_currency=currency_count > 1,
        new_drafts_last_30_days=new_drafts_last_30_days,
        successful_publishes_last_30_days=int(successful_publishes or 0),
    )


def _publish_duration_expression(db: Session):
    if db.get_bind().dialect.name == "postgresql":
        return func.extract("epoch", PublishingJob.completed_at - PublishingJob.started_at)
    return (func.julianday(PublishingJob.completed_at) - func.julianday(PublishingJob.started_at)) * 86400


def _build_workflow_health(
    db: Session,
    *,
    organization_id: str,
    store_connection_id: str | None,
    now: datetime,
    latest_etsy_fetch_at: datetime | None,
) -> tuple[WorkflowHealth, int, int]:
    cutoff_30 = now - timedelta(days=30)
    scope_clause = _scope_clause(PublishingJob, store_connection_id)
    settled_in_window = (
        PublishingJob.status.in_(("succeeded", "failed"))
        & (func.coalesce(PublishingJob.completed_at, PublishingJob.updated_at, PublishingJob.created_at) >= cutoff_30)
    )
    completed_with_duration = (
        settled_in_window
        & PublishingJob.started_at.is_not(None)
        & PublishingJob.completed_at.is_not(None)
    )
    aggregate = db.execute(
        select(
            _count_when(PublishingJob.status == "queued"),
            _count_when(PublishingJob.status.in_(("leased", "running"))),
            _count_when((PublishingJob.status == "failed") & settled_in_window),
            func.avg(case((completed_with_duration, _publish_duration_expression(db)), else_=None)),
            _count_when((PublishingJob.status == "succeeded") & settled_in_window),
            _count_when(settled_in_window),
            func.max(PublishingJob.completed_at),
            func.max(PublishingJob.started_at),
            func.max(PublishingJob.updated_at),
            func.max(PublishingJob.created_at),
        ).where(
            PublishingJob.organization_id == organization_id,
            scope_clause,
        )
    ).one()

    latest_failure_row = db.execute(
        select(
            ProviderProductDraft.id,
            ProviderProductDraft.title,
            ProviderStoreConnection.label,
            PublishingJob.completed_at,
            PublishingJob.updated_at,
            PublishingJob.created_at,
            PublishingJob.error_message,
        )
        .join(
            ProviderProductDraft,
            ProviderProductDraft.id == PublishingJob.provider_product_draft_id,
        )
        .join(
            ProviderStoreConnection,
            ProviderStoreConnection.id == PublishingJob.provider_store_connection_id,
        )
        .where(
            PublishingJob.organization_id == organization_id,
            scope_clause,
            PublishingJob.status == "failed",
        )
        .order_by(
            func.coalesce(
                PublishingJob.completed_at,
                PublishingJob.updated_at,
                PublishingJob.created_at,
            ).desc()
        )
        .limit(1)
    ).one_or_none()
    latest_failure = None
    if latest_failure_row is not None:
        latest_failure = WorkflowLatestFailure(
            product_id=latest_failure_row.id,
            title=latest_failure_row.title,
            provider_store_label=latest_failure_row.label,
            failed_at=_latest_timestamp(
                latest_failure_row.completed_at,
                latest_failure_row.updated_at,
                latest_failure_row.created_at,
            ),
            error_message=_trim_error_message(latest_failure_row.error_message),
        )

    return (
        WorkflowHealth(
            queued_job_count=int(aggregate[0]),
            in_progress_job_count=int(aggregate[1]),
            failed_job_count_last_30_days=int(aggregate[2]),
            average_publish_duration_seconds=(
                round(_as_float(aggregate[3]) or 0.0, 2) if aggregate[3] is not None else None
            ),
            latest_failure=latest_failure,
            latest_publish_activity_at=_latest_timestamp(*aggregate[6:10]),
            latest_etsy_fetch_at=latest_etsy_fetch_at,
        ),
        int(aggregate[4]),
        int(aggregate[5]),
    )


def _snapshot_rows(snapshot: AnalyticsSnapshot | None) -> list[StoreRollupRow]:
    payload = snapshot.payload_json if snapshot is not None else None
    raw_rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(raw_rows, list):
        return []
    rows: list[StoreRollupRow] = []
    for item in raw_rows:
        try:
            rows.append(StoreRollupRow.model_validate(item))
        except ValidationError:
            continue
    return rows


def _snapshot_metadata(
    snapshot: AnalyticsSnapshot | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    if snapshot is None or snapshot.payload_json is None or snapshot.fetched_at is None:
        freshness = "missing"
    elif snapshot.expires_at is None or (_coerce_utc(snapshot.expires_at) or now) <= now:
        freshness = "stale"
    else:
        freshness = "fresh"
    return {
        "freshness": freshness,
        "refresh_status": snapshot.status if snapshot is not None else "missing",
        "fetched_at": _coerce_utc(snapshot.fetched_at) if snapshot is not None else None,
        "expires_at": _coerce_utc(snapshot.expires_at) if snapshot is not None else None,
        "last_refresh_attempted_at": (
            _coerce_utc(snapshot.last_attempted_at) if snapshot is not None else None
        ),
    }


def _build_etsy_snapshot(
    *,
    available: bool,
    unavailable_reason: str | None,
    is_connected: bool,
    connected_account_count: int,
    supports_detailed_receipts: bool,
    rows: list[StoreRollupRow],
    snapshot: AnalyticsSnapshot | None,
    now: datetime,
) -> EtsySnapshot:
    metadata = _snapshot_metadata(snapshot, now=now)
    if not available:
        return EtsySnapshot(
            available=False,
            unavailable_reason=unavailable_reason,
            is_connected=is_connected,
            connected_account_count=connected_account_count,
            supports_detailed_receipts=supports_detailed_receipts,
            **metadata,
        )

    mapped_store_ids = {
        connection_id
        for row in rows
        for connection_id in row.matched_connection_ids
        if connection_id
    }
    review_count = sum(row.review_count for row in rows)
    weighted_review_total = sum(
        (row.review_average or 0.0) * row.review_count
        for row in rows
        if row.review_average is not None and row.review_count > 0
    )
    return EtsySnapshot(
        available=True,
        unavailable_reason=None,
        is_connected=is_connected,
        connected_account_count=connected_account_count,
        supports_detailed_receipts=supports_detailed_receipts,
        connected_shop_count=len(rows),
        mapped_store_count=len(mapped_store_ids),
        lifetime_sales_count=sum(row.lifetime_sales_count for row in rows),
        active_listing_count=sum(row.active_listing_count for row in rows),
        digital_listing_count=sum(row.digital_listing_count for row in rows),
        favorite_count=sum(row.favorite_count for row in rows),
        review_count=review_count,
        review_average=round(weighted_review_total / review_count, 2) if review_count else None,
        vacation_shop_count=sum(1 for row in rows if row.is_vacation is True),
        payments_onboarding_issue_count=sum(1 for row in rows if row.has_payments_onboarding_issue),
        **metadata,
    )


def _fetch_store_rollup(
    db: Session,
    *,
    organization_id: str,
) -> tuple[bool, int, bool, list[StoreRollupRow], int]:
    actor = ActorContext(organization_id=organization_id, actor_id="analytics-worker")
    values_by_key = commerce._list_etsy_connection_values(db, organization_id=organization_id)
    connection_status = commerce._build_etsy_connection_status(
        db,
        actor=actor,
        values_by_key=values_by_key,
    )
    supports_detailed_receipts = "transactions_r" in connection_status.scopes
    if not connection_status.is_connected:
        return False, 0, False, [], 0

    connected_shops_by_id = {shop.shop_id: shop for shop in connection_status.connected_shops}
    shop_sources: list[dict[str, object]] = []
    seen_shop_ids: set[str] = set()
    for values in values_by_key.values():
        refresh_token = commerce._normalize_optional_string(values.get("refresh_token"))
        if not refresh_token:
            continue
        for shop in commerce._normalize_etsy_shop_summaries(
            values.get("shops") if isinstance(values.get("shops"), list) else []
        ):
            shop_id = commerce._normalize_optional_string(shop.get("shop_id"))
            if not shop_id or shop_id in seen_shop_ids:
                continue
            seen_shop_ids.add(shop_id)
            shop_sources.append(
                {
                    "shop_id": shop_id,
                    "shop_name": commerce._normalize_optional_string(shop.get("shop_name")) or shop_id,
                    "shop_url": commerce._normalize_optional_string(shop.get("shop_url")),
                    "refresh_token": refresh_token,
                    "last_synced_at": commerce._parse_optional_datetime(values.get("last_synced_at")),
                }
            )

    rows: list[StoreRollupRow] = []
    failed_shop_count = 0
    for source in shop_sources:
        shop_id = str(source["shop_id"])
        try:
            access_token = commerce._refresh_access_token(source["refresh_token"])
            raw_shop = commerce.fetch_etsy_shop(access_token=access_token, shop_id=shop_id)
        except HTTPException:
            failed_shop_count += 1
            continue

        connected_shop = connected_shops_by_id.get(shop_id)
        matched_pairs = sorted(
            zip(
                connected_shop.matched_connection_ids if connected_shop else [],
                connected_shop.matched_connection_labels if connected_shop else [],
                strict=False,
            ),
            key=lambda pair: pair[1].casefold(),
        )
        rows.append(
            StoreRollupRow(
                shop_id=shop_id,
                shop_name=commerce._normalize_optional_string(raw_shop.get("shop_name")) or str(source["shop_name"]),
                shop_url=commerce._normalize_optional_string(raw_shop.get("url"))
                or commerce._normalize_optional_string(raw_shop.get("shop_url"))
                or str(source.get("shop_url") or "")
                or None,
                currency_code=commerce._normalize_optional_string(raw_shop.get("currency_code")),
                lifetime_sales_count=commerce._parse_optional_int(raw_shop.get("transaction_sold_count")) or 0,
                active_listing_count=commerce._parse_optional_int(raw_shop.get("listing_active_count")) or 0,
                digital_listing_count=commerce._parse_optional_int(raw_shop.get("digital_listing_count")) or 0,
                favorite_count=commerce._parse_optional_int(raw_shop.get("num_favorers")) or 0,
                review_count=commerce._parse_optional_int(raw_shop.get("review_count")) or 0,
                review_average=commerce._parse_optional_float(raw_shop.get("review_average")),
                is_vacation=(
                    raw_shop.get("is_vacation") if isinstance(raw_shop.get("is_vacation"), bool) else None
                ),
                has_payments_onboarding_issue=(
                    not raw_shop.get("is_etsy_payments_onboarded")
                    if isinstance(raw_shop.get("is_etsy_payments_onboarded"), bool)
                    else False
                ),
                updated_at=commerce._parse_optional_epoch_datetime(
                    raw_shop.get("updated_timestamp") or raw_shop.get("update_date")
                ),
                last_synced_at=_coerce_utc(source.get("last_synced_at")),  # type: ignore[arg-type]
                matched_connection_ids=[connection_id for connection_id, _ in matched_pairs],
                matched_connection_labels=[label for _, label in matched_pairs],
            )
        )

    rows.sort(
        key=lambda row: (
            -row.lifetime_sales_count,
            -row.favorite_count,
            row.shop_name.casefold(),
        )
    )
    return (
        True,
        connection_status.connected_account_count,
        supports_detailed_receipts,
        rows,
        failed_shop_count,
    )


def _get_or_create_snapshot(
    db: Session,
    *,
    organization_id: str,
    attempted_at: datetime,
) -> AnalyticsSnapshot:
    snapshot = db.scalar(
        select(AnalyticsSnapshot)
        .where(
            AnalyticsSnapshot.organization_id == organization_id,
            AnalyticsSnapshot.provider == ETSY_SNAPSHOT_PROVIDER,
            AnalyticsSnapshot.source_scope == ETSY_SNAPSHOT_SCOPE,
        )
        .with_for_update()
    )
    if snapshot is not None:
        return snapshot
    snapshot = AnalyticsSnapshot(
        organization_id=organization_id,
        provider=ETSY_SNAPSHOT_PROVIDER,
        source_scope=ETSY_SNAPSHOT_SCOPE,
        status="failed",
        last_attempted_at=attempted_at,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def record_etsy_analytics_refresh_failure(
    db: Session,
    *,
    organization_id: str,
    failure_summary: str,
    attempted_at: datetime | None = None,
) -> None:
    now = attempted_at or datetime.now(timezone.utc)
    snapshot = _get_or_create_snapshot(
        db,
        organization_id=organization_id,
        attempted_at=now,
    )
    snapshot.status = "failed"
    snapshot.last_attempted_at = now
    snapshot.last_failure_at = now
    snapshot.failure_summary = _trim_error_message(failure_summary)
    db.commit()


def refresh_etsy_analytics_snapshot(
    db: Session,
    *,
    organization_id: str,
    now: datetime | None = None,
) -> ProviderSnapshotRefreshResult:
    attempted_at = now or datetime.now(timezone.utc)
    is_connected, connected_account_count, supports_detailed_receipts, rows, failed_shop_count = (
        _fetch_store_rollup(db, organization_id=organization_id)
    )
    if failed_shop_count:
        summary = (
            f"Etsy analytics refresh failed for {failed_shop_count} "
            f"shop{'s' if failed_shop_count != 1 else ''}; serving the last successful snapshot."
        )
        record_etsy_analytics_refresh_failure(
            db,
            organization_id=organization_id,
            failure_summary=summary,
            attempted_at=attempted_at,
        )
        return ProviderSnapshotRefreshResult(
            outcome="partial" if rows else "failed",
            fetched_shop_count=len(rows),
            failed_shop_count=failed_shop_count,
            failure_summary=summary,
        )

    snapshot = _get_or_create_snapshot(
        db,
        organization_id=organization_id,
        attempted_at=attempted_at,
    )
    snapshot.payload_json = {
        "is_connected": is_connected,
        "connected_account_count": connected_account_count,
        "supports_detailed_receipts": supports_detailed_receipts,
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    snapshot.status = "succeeded"
    snapshot.fetched_at = attempted_at
    snapshot.expires_at = attempted_at + timedelta(seconds=settings.analytics_snapshot_ttl_seconds)
    snapshot.last_attempted_at = attempted_at
    snapshot.last_failure_at = None
    snapshot.failure_summary = None
    db.commit()
    return ProviderSnapshotRefreshResult(
        outcome="completed",
        fetched_shop_count=len(rows),
        failed_shop_count=0,
    )


def get_workspace_analytics(
    db: Session,
    *,
    actor: ActorContext,
    store_connection_id: str | None = None,
) -> WorkspaceAnalyticsResponse:
    now = datetime.now(timezone.utc)
    organization_id = actor.organization_id
    if not organization_id:
        raise HTTPException(status_code=403, detail="Organization context is required.")
    requested_store_id = (store_connection_id or "").strip()

    selected_connection: ProviderStoreConnection | None = None
    if requested_store_id and requested_store_id != "all":
        selected_connection = db.scalar(
            select(ProviderStoreConnection).where(
                ProviderStoreConnection.id == requested_store_id,
                ProviderStoreConnection.organization_id == organization_id,
                ProviderStoreConnection.deleted_at.is_(None),
            )
        )
        if selected_connection is None:
            raise HTTPException(status_code=404, detail="Store connection not found.")
    scoped_store_id = selected_connection.id if selected_connection is not None else None
    scope = _build_scope(store_connection=selected_connection)

    values_by_key = commerce._list_etsy_connection_values(db, organization_id=organization_id)
    connection_status = commerce._build_etsy_connection_status(
        db,
        actor=actor,
        values_by_key=values_by_key,
    )
    is_connected = connection_status.is_connected
    connected_account_count = connection_status.connected_account_count
    supports_detailed_receipts = "transactions_r" in connection_status.scopes
    snapshot = db.scalar(
        select(AnalyticsSnapshot).where(
            AnalyticsSnapshot.organization_id == organization_id,
            AnalyticsSnapshot.provider == ETSY_SNAPSHOT_PROVIDER,
            AnalyticsSnapshot.source_scope == ETSY_SNAPSHOT_SCOPE,
        )
    )
    all_rollup_rows = _snapshot_rows(snapshot)
    filtered_rollup_rows = [
        row
        for row in all_rollup_rows
        if selected_connection is None or selected_connection.id in row.matched_connection_ids
    ]

    warnings: list[str] = []
    if snapshot is not None and snapshot.failure_summary:
        warnings.append(snapshot.failure_summary)
    metadata = _snapshot_metadata(snapshot, now=now)
    if metadata["freshness"] == "stale":
        warnings.append("Etsy market metrics are stale while a background refresh is pending.")

    if not is_connected:
        etsy_snapshot = _build_etsy_snapshot(
            available=False,
            unavailable_reason="Connect Etsy in Settings to unlock market analytics.",
            is_connected=False,
            connected_account_count=0,
            supports_detailed_receipts=False,
            rows=[],
            snapshot=snapshot,
            now=now,
        )
        filtered_rollup_rows = []
    elif selected_connection is not None and selected_connection.storefront_type != "etsy":
        etsy_snapshot = _build_etsy_snapshot(
            available=False,
            unavailable_reason=f"{selected_connection.label} is not mapped to a discovered Etsy shop.",
            is_connected=True,
            connected_account_count=connected_account_count,
            supports_detailed_receipts=supports_detailed_receipts,
            rows=[],
            snapshot=snapshot,
            now=now,
        )
        filtered_rollup_rows = []
    elif filtered_rollup_rows:
        etsy_snapshot = _build_etsy_snapshot(
            available=True,
            unavailable_reason=None,
            is_connected=True,
            connected_account_count=connected_account_count,
            supports_detailed_receipts=supports_detailed_receipts,
            rows=filtered_rollup_rows,
            snapshot=snapshot,
            now=now,
        )
    else:
        unavailable_reason = (
            f"{selected_connection.label} is not mapped to a discovered Etsy shop."
            if selected_connection is not None
            else "Etsy market metrics are waiting for the background snapshot refresh."
            if snapshot is None or snapshot.payload_json is None
            else "No Etsy shops have been discovered yet. Refresh Etsy in Settings to load shop metrics."
        )
        etsy_snapshot = _build_etsy_snapshot(
            available=False,
            unavailable_reason=unavailable_reason,
            is_connected=True,
            connected_account_count=connected_account_count,
            supports_detailed_receipts=supports_detailed_receipts,
            rows=[],
            snapshot=snapshot,
            now=now,
        )

    catalog_health, listings_needing_attention_count, new_drafts_last_30_days = _build_catalog_health(
        db,
        organization_id=organization_id,
        store_connection_id=scoped_store_id,
    )
    recent_activity = _build_recent_activity(
        db,
        organization_id=organization_id,
        store_connection_id=scoped_store_id,
        now=now,
        new_drafts_last_30_days=new_drafts_last_30_days,
    )
    workflow_health, publish_success_count_last_30, publish_settled_count_last_30 = _build_workflow_health(
        db,
        organization_id=organization_id,
        store_connection_id=scoped_store_id,
        now=now,
        latest_etsy_fetch_at=_coerce_utc(snapshot.fetched_at) if snapshot is not None else None,
    )
    publish_success_rate_last_30 = (
        round((publish_success_count_last_30 / publish_settled_count_last_30) * 100, 2)
        if publish_settled_count_last_30
        else None
    )
    overview = AnalyticsOverview(
        published_product_count=catalog_health.status_counts.published_count,
        active_etsy_listing_count=etsy_snapshot.active_listing_count if etsy_snapshot.available else 0,
        orders_last_30_days=recent_activity.orders_last_30_days,
        publish_success_rate_last_30_days=publish_success_rate_last_30,
        publish_success_count_last_30_days=publish_success_count_last_30,
        publish_settled_count_last_30_days=publish_settled_count_last_30,
        listings_needing_attention_count=listings_needing_attention_count,
    )

    return WorkspaceAnalyticsResponse(
        generated_at=now,
        scope=scope,
        overview=overview,
        catalog_health=catalog_health,
        workflow_health=workflow_health,
        recent_activity=recent_activity,
        etsy_snapshot=etsy_snapshot,
        store_rollup=filtered_rollup_rows,
        warnings=warnings,
    )
