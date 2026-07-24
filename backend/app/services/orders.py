from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.database import WorkerSessionLocal as SessionLocal
from app.db.models import Order, ProviderStoreConnection, SyncEvent
from app.db.tenant_context import set_database_request_context
from app.providers import get_provider_adapter
from app.services.provider_connections import get_provider_credentials

orders_logger = get_logger("orders")

ConnectionSyncOutcome = Literal["completed", "partial", "failed"]


class OrderSyncInterruptedError(RuntimeError):
    pass


@dataclass
class ConnectionSyncResult:
    connection_id: str
    provider: str | None
    outcome: ConnectionSyncOutcome
    pages: int = 0
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    failure_summaries: list[dict[str, Any]] = field(default_factory=list)
    last_successful_at: datetime | None = None

    @property
    def useful_scope_completed(self) -> bool:
        return self.outcome == "completed" or self.pages > 0

    def to_result_json(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "outcome": self.outcome,
            "pages": self.pages,
            "fetched": self.fetched,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "failed": self.failed,
            "failure_summaries": self.failure_summaries,
            "last_successful_at": (
                self.last_successful_at.isoformat() if self.last_successful_at is not None else None
            ),
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _append_failure_summary(
    result: ConnectionSyncResult,
    *,
    code: str,
    count: int = 1,
    error_type: str | None = None,
) -> None:
    if len(result.failure_summaries) >= 20:
        return
    summary: dict[str, Any] = {"code": code, "count": count}
    if error_type:
        summary["error_type"] = error_type
    result.failure_summaries.append(summary)


def _create_sync_event(
    session: Session,
    *,
    job_id: str,
    organization_id: str,
    event_type: str,
    provider: str | None,
    connection_id: str | None,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        SyncEvent(
            sync_job_id=job_id,
            organization_id=organization_id,
            event_type=event_type,
            message=message,
            details_json=details,
            provider=provider,
            provider_store_connection_id=connection_id,
        )
    )


def _bulk_upsert_orders(session: Session, order_rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not order_rows:
        return 0, 0

    organization_id = str(order_rows[0]["organization_id"])
    provider = str(order_rows[0]["provider"])
    external_order_ids = [str(row["external_order_id"]) for row in order_rows]
    existing_ids = set(
        session.scalars(
            select(Order.external_order_id).where(
                Order.organization_id == organization_id,
                Order.provider == provider,
                Order.external_order_id.in_(external_order_ids),
            )
        ).all()
    )

    synced_at = _utc_now()
    table_columns = {column.name for column in Order.__table__.columns}
    values: list[dict[str, Any]] = []
    for order_row in order_rows:
        value = {key: item for key, item in order_row.items() if key in table_columns}
        value.update(
            {
                "id": str(uuid.uuid4()),
                "last_synced_at": synced_at,
                "created_at": synced_at,
                "updated_at": synced_at,
            }
        )
        values.append(value)

    dialect_name = session.get_bind().dialect.name
    insert_factory = sqlite_insert if dialect_name == "sqlite" else postgresql_insert
    insert_statement = insert_factory(Order).values(values)
    immutable_columns = {"id", "organization_id", "provider", "external_order_id", "created_at"}
    update_columns = {
        column.name: getattr(insert_statement.excluded, column.name)
        for column in Order.__table__.columns
        if column.name not in immutable_columns
    }
    session.execute(
        insert_statement.on_conflict_do_update(
            index_elements=["organization_id", "provider", "external_order_id"],
            set_=update_columns,
        )
    )
    updated_count = len(existing_ids)
    return len(values) - updated_count, updated_count


def _normalize_page_orders(
    *,
    job_id: str,
    adapter: Any,
    raw_orders: list[dict[str, Any]],
    organization_id: str,
    connection_id: str,
    result: ConnectionSyncResult,
) -> list[dict[str, Any]]:
    normalized_orders: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set()
    for raw_order in raw_orders:
        try:
            normalized = adapter.normalize_order(
                raw_order=raw_order,
                organization_id=organization_id,
                provider_store_connection_id=connection_id,
            )
            external_order_id = str(normalized.get("external_order_id") or "").strip()
            if not external_order_id:
                raise ValueError("Normalized order has no external identifier.")
            if external_order_id in seen_external_ids:
                result.skipped += 1
                continue
            seen_external_ids.add(external_order_id)
            normalized_orders.append(normalized)
        except Exception as exc:
            result.failed += 1
            _append_failure_summary(
                result,
                code="order_normalization_failed",
                error_type=type(exc).__name__,
            )
            log_event(
                orders_logger,
                "orders.order_normalization.failed",
                level=40,
                job_id=job_id,
                organization_id=organization_id,
                provider=result.provider,
                provider_store_connection_id=connection_id,
                error_type=type(exc).__name__,
            )
    return normalized_orders


async def execute_connection_sync(
    job_id: str,
    connection_id: str,
    *,
    heartbeat: Callable[[], bool] | None = None,
) -> ConnectionSyncResult:
    run_started_at = _utc_now()
    with SessionLocal() as session:
        connection = session.scalar(
            select(ProviderStoreConnection).where(
                ProviderStoreConnection.id == connection_id,
                ProviderStoreConnection.status == "connected",
                ProviderStoreConnection.deleted_at.is_(None),
            )
        )
        if connection is None:
            log_event(
                orders_logger,
                "orders.connection_sync.missing_connection",
                level=40,
                job_id=job_id,
                provider_store_connection_id=connection_id,
            )
            return ConnectionSyncResult(
                connection_id=connection_id,
                provider=None,
                outcome="failed",
                failed=1,
                failure_summaries=[{"code": "connection_missing", "count": 1}],
            )

        organization_id = connection.organization_id
        provider = connection.provider
        provider_store_id = connection.provider_store_id
        set_database_request_context(
            session,
            actor_id=None,
            organization_id=organization_id,
        )
        credentials = get_provider_credentials(
            session,
            organization_id=organization_id,
            provider=provider,
            credential_key=connection.credential_key,
        )
        result = ConnectionSyncResult(
            connection_id=connection_id,
            provider=provider,
            outcome="failed",
            last_successful_at=_parse_datetime(connection.order_sync_last_success_at),
        )
        if not credentials:
            result.failed = 1
            _append_failure_summary(result, code="credentials_missing")
            _create_sync_event(
                session,
                job_id=job_id,
                organization_id=organization_id,
                event_type="connection_error",
                provider=provider,
                connection_id=connection_id,
                message="Order sync credentials are unavailable.",
                details={"code": "credentials_missing"},
            )
            session.commit()
            return result

        cursor_state = connection.order_sync_cursor_json if isinstance(connection.order_sync_cursor_json, dict) else {}
        cursor = str(cursor_state.get("cursor") or "").strip() or None
        previous_watermark = _parse_datetime(connection.order_sync_watermark_at)
        since = _parse_datetime(cursor_state.get("since")) if cursor else None
        if since is None and previous_watermark is not None:
            since = previous_watermark - timedelta(hours=settings.order_sync_overlap_hours)
        candidate_watermark = _parse_datetime(cursor_state.get("watermark")) or previous_watermark
        try:
            persisted_page_count = max(int(cursor_state.get("pages_processed") or 0), 0) if cursor else 0
        except (TypeError, ValueError):
            persisted_page_count = 0
        _create_sync_event(
            session,
            job_id=job_id,
            organization_id=organization_id,
            event_type="connection_sync_started",
            provider=provider,
            connection_id=connection_id,
            message="Starting incremental order synchronization.",
            details={"resuming": cursor is not None},
        )
        session.commit()

    adapter = get_provider_adapter(provider, credentials)
    pages_this_run = 0
    while pages_this_run < settings.order_sync_max_pages_per_connection:
        try:
            page = await adapter.fetch_orders(
                provider_store_id=provider_store_id,
                since=since,
                cursor=cursor,
                limit=settings.order_sync_page_size,
            )
        except Exception as exc:
            result.failed += 1
            _append_failure_summary(
                result,
                code="provider_page_request_failed",
                error_type=type(exc).__name__,
            )
            result.outcome = "partial" if result.pages > 0 else "failed"
            log_event(
                orders_logger,
                "orders.connection_fetch.failed",
                level=40,
                job_id=job_id,
                organization_id=organization_id,
                provider=provider,
                provider_store_connection_id=connection_id,
                error_type=type(exc).__name__,
            )
            with SessionLocal() as session:
                set_database_request_context(
                    session,
                    actor_id=None,
                    organization_id=organization_id,
                )
                _create_sync_event(
                    session,
                    job_id=job_id,
                    organization_id=organization_id,
                    event_type="connection_error",
                    provider=provider,
                    connection_id=connection_id,
                    message="Provider order page request failed.",
                    details={"code": "provider_page_request_failed", "error_type": type(exc).__name__},
                )
                session.commit()
            return result

        pages_this_run += 1
        result.pages += 1
        result.fetched += page.fetched_count
        skipped_before_page = result.skipped
        failed_before_page = result.failed
        result.skipped += page.skipped_count
        result.failed += page.failed_count
        if page.failed_count:
            _append_failure_summary(result, code="provider_order_detail_failed", count=page.failed_count)

        normalized_orders = _normalize_page_orders(
            job_id=job_id,
            adapter=adapter,
            raw_orders=page.orders,
            organization_id=organization_id,
            connection_id=connection_id,
            result=result,
        )
        if page.observed_watermark_at is not None:
            observed_watermark = _parse_datetime(page.observed_watermark_at)
            if observed_watermark is not None and (
                candidate_watermark is None or observed_watermark > candidate_watermark
            ):
                candidate_watermark = observed_watermark

        with SessionLocal() as session:
            set_database_request_context(
                session,
                actor_id=None,
                organization_id=organization_id,
            )
            locked_connection = session.execute(
                select(ProviderStoreConnection)
                .where(
                    ProviderStoreConnection.id == connection_id,
                    ProviderStoreConnection.organization_id == organization_id,
                    ProviderStoreConnection.status == "connected",
                    ProviderStoreConnection.deleted_at.is_(None),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if locked_connection is None:
                raise OrderSyncInterruptedError("Provider store connection disappeared during order sync.")

            inserted_count, updated_count = _bulk_upsert_orders(session, normalized_orders)
            result.inserted += inserted_count
            result.updated += updated_count
            is_final_page = page.next_cursor is None
            if is_final_page:
                locked_connection.order_sync_cursor_json = None
                if result.failed == 0:
                    successful_at = _utc_now()
                    locked_connection.order_sync_watermark_at = candidate_watermark or run_started_at
                    locked_connection.order_sync_last_success_at = successful_at
                    result.last_successful_at = successful_at
            else:
                locked_connection.order_sync_cursor_json = {
                    "cursor": page.next_cursor,
                    "since": since.isoformat() if since is not None else None,
                    "watermark": candidate_watermark.isoformat() if candidate_watermark is not None else None,
                    "pages_processed": persisted_page_count + result.pages,
                }

            _create_sync_event(
                session,
                job_id=job_id,
                organization_id=organization_id,
                event_type="order_page_committed",
                provider=provider,
                connection_id=connection_id,
                message="Committed one bounded order page.",
                details={
                    "page": result.pages,
                    "fetched": page.fetched_count,
                    "inserted": inserted_count,
                    "updated": updated_count,
                    "skipped": result.skipped - skipped_before_page,
                    "failed": result.failed - failed_before_page,
                    "has_more": not is_final_page,
                },
            )
            session.commit()

        if heartbeat is not None and not heartbeat():
            raise OrderSyncInterruptedError("Order sync lease was lost after a committed page.")

        if is_final_page:
            result.outcome = "partial" if result.failed > 0 else "completed"
            log_event(
                orders_logger,
                "orders.connection_sync.completed",
                verbose_only=True,
                job_id=job_id,
                organization_id=organization_id,
                provider=provider,
                provider_store_connection_id=connection_id,
                outcome=result.outcome,
                page_count=result.pages,
                fetched_order_count=result.fetched,
                inserted_order_count=result.inserted,
                updated_order_count=result.updated,
                skipped_order_count=result.skipped,
                failed_order_count=result.failed,
            )
            return result

        cursor = page.next_cursor

    result.outcome = "partial"
    _append_failure_summary(result, code="page_limit_reached")
    with SessionLocal() as session:
        set_database_request_context(
            session,
            actor_id=None,
            organization_id=organization_id,
        )
        _create_sync_event(
            session,
            job_id=job_id,
            organization_id=organization_id,
            event_type="connection_partial",
            provider=provider,
            connection_id=connection_id,
            message="Order sync reached the configured page limit and will resume later.",
            details={"code": "page_limit_reached", "page_limit": settings.order_sync_max_pages_per_connection},
        )
        session.commit()
    return result
