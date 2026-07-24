from fastapi import APIRouter, Depends, Query
import re
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_workspace_actor_context, get_db
from app.db.models import Order as DBOrder, ProviderStoreConnection
from app.models.schemas import (
    Order,
    OrderFilters,
    OrderFilterStore,
    OrderPageResponse,
    PodProviderKey,
)

router = APIRouter(tags=["orders"])


CARD_LIKE_SEQUENCE_PATTERN = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
PUBLIC_ORDER_COLUMNS = (
    DBOrder.id,
    DBOrder.organization_id,
    DBOrder.provider_store_connection_id,
    DBOrder.provider,
    DBOrder.external_order_id,
    DBOrder.display_order_id,
    DBOrder.marketplace_order_id,
    DBOrder.product_summary,
    DBOrder.fulfillment_status,
    DBOrder.production_status,
    DBOrder.financial_status,
    DBOrder.currency,
    DBOrder.total_amount,
    DBOrder.order_created_at,
    DBOrder.shipped_at,
    DBOrder.delivered_at,
    DBOrder.cancelled_at,
    DBOrder.sent_to_production_at,
    DBOrder.retail_amount,
    DBOrder.provider_order_url,
    DBOrder.last_synced_at,
    DBOrder.created_at,
    DBOrder.updated_at,
)


def _passes_luhn_check(value: str) -> bool:
    total = 0
    double_digit = False

    for character in reversed(value):
        digit = int(character)
        if double_digit:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        double_digit = not double_digit

    return total % 10 == 0


def _mask_card_like_substrings(value: str | None) -> str | None:
    if not value:
        return value

    def replace(match: re.Match[str]) -> str:
        digits_only = match.group(0)
        if not _passes_luhn_check(digits_only):
            return digits_only
        return f"****{digits_only[-4:]}"

    return CARD_LIKE_SEQUENCE_PATTERN.sub(replace, value)


def _mask_public_order_strings(data: dict[str, object]) -> dict[str, object]:
    for field_name, field_value in list(data.items()):
        if isinstance(field_value, str):
            data[field_name] = _mask_card_like_substrings(field_value)
    return data


@router.get("/orders", response_model=OrderPageResponse)
def list_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    store_connection_id: str | None = None,
    provider: PodProviderKey | None = None,
    fulfillment_status: str | None = None,
    _actor: ActorContext = Depends(get_workspace_actor_context),
    db: Session = Depends(get_db)
) -> OrderPageResponse:
    scope_clauses = [DBOrder.organization_id == _actor.organization_id]
    metadata_scope_clauses = [DBOrder.organization_id == _actor.organization_id]
    if store_connection_id:
        scope_clauses.append(
            DBOrder.provider_store_connection_id == store_connection_id
        )

    filter_clauses = list(scope_clauses)
    if provider:
        filter_clauses.append(DBOrder.provider == provider)
    if fulfillment_status:
        filter_clauses.append(
            DBOrder.fulfillment_status == fulfillment_status.strip()
        )

    total = int(
        db.scalar(select(func.count(DBOrder.id)).where(*filter_clauses)) or 0
    )
    order_activity_at = func.coalesce(
        DBOrder.order_created_at,
        DBOrder.sent_to_production_at,
        DBOrder.created_at,
    )
    rows = db.execute(
        select(
            *PUBLIC_ORDER_COLUMNS,
            ProviderStoreConnection.label.label("provider_store_label"),
            ProviderStoreConnection.storefront_type.label(
                "provider_storefront_type"
            ),
        )
        .join(
            ProviderStoreConnection,
            ProviderStoreConnection.id == DBOrder.provider_store_connection_id,
        )
        .where(*filter_clauses)
        .order_by(order_activity_at.desc(), DBOrder.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).mappings().all()
    items = [
        Order.model_validate(_mask_public_order_strings(dict(row)))
        for row in rows
    ]

    providers = list(
        db.scalars(
            select(DBOrder.provider)
            .where(*metadata_scope_clauses)
            .distinct()
            .order_by(DBOrder.provider.asc())
        ).all()
    )
    fulfillment_statuses = list(
        db.scalars(
            select(DBOrder.fulfillment_status)
            .where(*metadata_scope_clauses)
            .distinct()
            .order_by(DBOrder.fulfillment_status.asc())
        ).all()
    )
    store_rows = db.execute(
        select(
            ProviderStoreConnection.id,
            ProviderStoreConnection.label,
            ProviderStoreConnection.provider,
        )
        .join(
            DBOrder,
            DBOrder.provider_store_connection_id == ProviderStoreConnection.id,
        )
        .where(*metadata_scope_clauses)
        .distinct()
        .order_by(
            ProviderStoreConnection.provider.asc(),
            ProviderStoreConnection.label.asc(),
            ProviderStoreConnection.id.asc(),
        )
    ).mappings().all()

    return OrderPageResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
        filters=OrderFilters(
            providers=providers,
            fulfillment_statuses=fulfillment_statuses,
            stores=[OrderFilterStore.model_validate(dict(row)) for row in store_rows],
        ),
    )
