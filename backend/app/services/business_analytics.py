from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import ActorContext
from app.db.models import (
    ExchangeRate,
    Expense,
    Mockup,
    Order,
    OrderLineItem,
    Organization,
    ProviderProductDraft,
    ProviderStoreConnection,
)
from app.models.schemas import (
    AnalyticsCapabilities,
    AnalyticsDateRange,
    AnalyticsDetailPage,
    AnalyticsMoneyMetric,
    AnalyticsPreferencesResponse,
    AnalyticsPreferencesUpdateRequest,
    AnalyticsScope,
    AnalyticsTrendPoint,
    BusinessAnalyticsResponse,
    BusinessAnalyticsSummary,
    ExpenseCreateRequest,
    ExpenseRecord,
    ExpenseUpdateRequest,
    OrderLineMappingRequest,
    ProductPerformanceRow,
    SeoPerformanceRow,
    StorePerformanceRow,
    UnmatchedOrderLine,
)
from app.services import provider_connections as commerce


SUPPORTED_CURRENCIES = {"PHP", "USD", "EUR", "JPY"}
SUPPORTED_PRESETS = {
    "7d",
    "30d",
    "90d",
    "this_month",
    "last_month",
    "this_year",
    "all_time",
    "custom",
}


@dataclass(frozen=True)
class ResolvedRange:
    preset: str
    start: datetime
    end: datetime
    comparison_start: datetime | None
    comparison_end: datetime | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown reporting timezone.") from exc


def _local_boundary(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)


def _resolve_range(
    *,
    preset: str,
    zone: ZoneInfo,
    now: datetime,
    custom_start: date | None,
    custom_end: date | None,
    earliest_at: datetime | None,
) -> ResolvedRange:
    normalized_preset = preset if preset in SUPPORTED_PRESETS else "30d"
    today = _as_utc(now).astimezone(zone).date()
    end_day = today + timedelta(days=1)

    if normalized_preset == "7d":
        start_day = today - timedelta(days=6)
    elif normalized_preset == "30d":
        start_day = today - timedelta(days=29)
    elif normalized_preset == "90d":
        start_day = today - timedelta(days=89)
    elif normalized_preset == "this_month":
        start_day = today.replace(day=1)
    elif normalized_preset == "last_month":
        this_month = today.replace(day=1)
        end_day = this_month
        start_day = (this_month - timedelta(days=1)).replace(day=1)
    elif normalized_preset == "this_year":
        start_day = today.replace(month=1, day=1)
    elif normalized_preset == "all_time":
        earliest_day = _as_utc(earliest_at).astimezone(zone).date() if earliest_at else today
        start_day = earliest_day
    elif normalized_preset == "custom":
        if custom_start is None or custom_end is None or custom_start > custom_end:
            raise HTTPException(status_code=422, detail="A valid custom start and end date are required.")
        start_day = custom_start
        end_day = custom_end + timedelta(days=1)
    else:
        start_day = today - timedelta(days=29)

    start = _local_boundary(start_day, zone)
    end = _local_boundary(end_day, zone)
    if normalized_preset == "all_time":
        return ResolvedRange(normalized_preset, start, end, None, None)

    duration = end - start
    return ResolvedRange(
        normalized_preset,
        start,
        end,
        start - duration,
        start,
    )


def _money(
    amount: Decimal | None,
    *,
    currency: str,
    eligible_count: int,
    total_count: int,
) -> AnalyticsMoneyMetric:
    coverage = 100.0 if total_count == 0 else round((eligible_count / total_count) * 100, 1)
    return AnalyticsMoneyMetric(
        amount=float(amount) if amount is not None else None,
        currency=currency,
        coverage_percent=coverage,
    )


class CurrencyConverter:
    def __init__(self, rates: list[ExchangeRate], target: str) -> None:
        self.target = target
        self._rates: dict[tuple[str, str], list[ExchangeRate]] = defaultdict(list)
        for rate in rates:
            self._rates[(rate.base_currency.upper(), rate.quote_currency.upper())].append(rate)
        for values in self._rates.values():
            values.sort(key=lambda item: item.effective_on, reverse=True)

    def _rate(
        self,
        base: str,
        quote: str,
        effective: datetime,
    ) -> Decimal | None:
        for rate in self._rates.get((base, quote), []):
            if _as_utc(rate.effective_on) <= effective:
                return rate.rate
        for rate in self._rates.get((quote, base), []):
            if _as_utc(rate.effective_on) <= effective:
                return Decimal("1") / rate.rate
        return None

    def convert(self, amount: Decimal | None, currency: str | None, occurred_at: datetime) -> Decimal | None:
        if amount is None or not currency:
            return None
        source = currency.upper()
        if source == self.target:
            return amount
        effective = _as_utc(occurred_at)
        direct_rate = self._rate(source, self.target, effective)
        if direct_rate is not None:
            return amount * direct_rate
        source_to_eur = (
            Decimal("1")
            if source == "EUR"
            else self._rate(source, "EUR", effective)
        )
        eur_to_target = (
            Decimal("1")
            if self.target == "EUR"
            else self._rate("EUR", self.target, effective)
        )
        if source_to_eur is None or eur_to_target is None:
            return None
        return amount * source_to_eur * eur_to_target


def _scope(
    db: Session,
    *,
    organization_id: str,
    store_connection_id: str | None,
) -> tuple[AnalyticsScope, ProviderStoreConnection | None]:
    requested = (store_connection_id or "").strip()
    if not requested or requested == "all":
        return AnalyticsScope(label="All stores", is_all_stores=True), None
    connection = db.scalar(
        select(ProviderStoreConnection).where(
            ProviderStoreConnection.id == requested,
            ProviderStoreConnection.organization_id == organization_id,
            ProviderStoreConnection.deleted_at.is_(None),
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Store connection not found.")
    return (
        AnalyticsScope(
            store_connection_id=connection.id,
            label=connection.label,
            provider=connection.provider,
            storefront_type=connection.storefront_type,
            is_all_stores=False,
        ),
        connection,
    )


def _seo(product: ProviderProductDraft, mockup_count: int) -> tuple[int, list[str]]:
    score = 0
    issues: list[str] = []
    title_length = len(product.title.strip())
    if 70 <= title_length <= 140:
        score += 25
    else:
        issues.append("Improve title length")
    if len((product.description or "").strip()) >= 160:
        score += 25
    else:
        issues.append("Expand description")
    tag_count = len(product.tags_json or [])
    if tag_count == 13:
        score += 25
    else:
        issues.append("Use all 13 tags")
    if mockup_count > 0:
        score += 15
    else:
        issues.append("Add listing images")
    if product.retail_price is not None and product.sku:
        score += 10
    else:
        issues.append("Complete price and SKU")
    return score, issues


def _trend_granularity(start: datetime, end: datetime) -> str:
    duration_days = max((end - start).days, 1)
    if duration_days <= 45:
        return "day"
    if duration_days <= 400:
        return "week"
    return "month"


def _date_key(value: datetime, zone: ZoneInfo, granularity: str) -> str:
    local_day = _as_utc(value).astimezone(zone).date()
    if granularity == "week":
        local_day -= timedelta(days=local_day.weekday())
    elif granularity == "month":
        local_day = local_day.replace(day=1)
    return local_day.isoformat()


def _bucket_periods(
    start: datetime,
    end: datetime,
    zone: ZoneInfo,
    granularity: str,
) -> list[str]:
    start_day = _as_utc(start).astimezone(zone).date()
    end_day = _as_utc(end - timedelta(microseconds=1)).astimezone(zone).date()
    if granularity == "week":
        cursor = start_day - timedelta(days=start_day.weekday())
        step = timedelta(days=7)
    elif granularity == "month":
        cursor = start_day.replace(day=1)
        periods: list[str] = []
        while cursor <= end_day:
            periods.append(cursor.isoformat())
            cursor = (
                cursor.replace(year=cursor.year + 1, month=1)
                if cursor.month == 12
                else cursor.replace(month=cursor.month + 1)
            )
        return periods
    else:
        cursor = start_day
        step = timedelta(days=1)

    periods = []
    while cursor <= end_day:
        periods.append(cursor.isoformat())
        cursor += step
    return periods


def get_business_analytics(
    db: Session,
    *,
    actor: ActorContext,
    store_connection_id: str | None,
    preset: str,
    start: date | None,
    end: date | None,
    currency: str | None,
    timezone_name: str | None,
    include_details: bool = True,
) -> BusinessAnalyticsResponse:
    organization_id = actor.organization_id
    if not organization_id:
        raise HTTPException(status_code=403, detail="Organization context is required.")
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")

    reporting_currency = (currency or organization.reporting_currency or "PHP").upper()
    if reporting_currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="Unsupported reporting currency.")
    reporting_timezone = timezone_name or organization.reporting_timezone or "Asia/Manila"
    zone = _timezone(reporting_timezone)
    scope, selected_connection = _scope(
        db,
        organization_id=organization_id,
        store_connection_id=store_connection_id,
    )

    earliest_order_statement = select(func.min(Order.order_created_at)).where(
        Order.organization_id == organization_id
    )
    earliest_expense_statement = select(func.min(Expense.incurred_on)).where(
        Expense.organization_id == organization_id
    )
    earliest_product_statement = select(func.min(ProviderProductDraft.created_at)).where(
        ProviderProductDraft.organization_id == organization_id
    )
    if selected_connection is not None:
        earliest_order_statement = earliest_order_statement.where(
            Order.provider_store_connection_id == selected_connection.id
        )
        earliest_expense_statement = earliest_expense_statement.where(
            Expense.provider_store_connection_id == selected_connection.id
        )
        earliest_product_statement = earliest_product_statement.where(
            ProviderProductDraft.provider_store_connection_id == selected_connection.id
        )
    earliest_candidates = [
        value
        for value in (
            db.scalar(earliest_order_statement),
            db.scalar(earliest_expense_statement),
            db.scalar(earliest_product_statement),
        )
        if value is not None
    ]
    earliest_activity_at = min(earliest_candidates, default=None)
    resolved = _resolve_range(
        preset=preset,
        zone=zone,
        now=datetime.now(timezone.utc),
        custom_start=start,
        custom_end=end,
        earliest_at=earliest_activity_at,
    )

    rates = db.scalars(
        select(ExchangeRate).where(ExchangeRate.organization_id == organization_id)
    ).all()
    converter = CurrencyConverter(list(rates), reporting_currency)

    order_statement = select(Order).where(
        Order.organization_id == organization_id,
        Order.order_created_at >= resolved.comparison_start if resolved.comparison_start else Order.order_created_at >= resolved.start,
        Order.order_created_at < resolved.end,
    )
    if selected_connection is not None:
        order_statement = order_statement.where(
            Order.provider_store_connection_id == selected_connection.id
        )
    orders = list(db.scalars(order_statement).all())
    etsy_receipt_ids = {
        order.external_order_id for order in orders if order.provider == "etsy"
    }
    orders = [
        order
        for order in orders
        if order.provider == "etsy"
        or not order.marketplace_order_id
        or order.marketplace_order_id not in etsy_receipt_ids
    ]
    current_orders = [
        order for order in orders
        if order.order_created_at is not None and resolved.start <= _as_utc(order.order_created_at) < resolved.end
    ]
    comparison_orders = [
        order for order in orders
        if resolved.comparison_start is not None
        and order.order_created_at is not None
        and resolved.comparison_start <= _as_utc(order.order_created_at) < resolved.start
    ]

    expense_filters = [
        Expense.organization_id == organization_id,
        Expense.incurred_on >= resolved.comparison_start if resolved.comparison_start else Expense.incurred_on >= resolved.start,
        Expense.incurred_on < resolved.end,
    ]
    if selected_connection is not None:
        expense_filters.append(
            Expense.provider_store_connection_id == selected_connection.id
        )
    if include_details:
        expenses = list(
            db.scalars(select(Expense).where(*expense_filters)).all()
        )
    else:
        expenses = list(
            db.execute(
                select(
                    Expense.id,
                    Expense.incurred_on,
                    Expense.amount,
                    Expense.currency,
                    Expense.provider_store_connection_id,
                    Expense.product_id,
                ).where(*expense_filters)
            ).all()
        )
    current_expenses = [
        item for item in expenses if resolved.start <= _as_utc(item.incurred_on) < resolved.end
    ]

    order_revenue: dict[str, Decimal | None] = {}
    for order in orders:
        native_amount = order.retail_amount if order.retail_amount is not None else order.total_amount
        occurred_at = order.order_created_at or order.created_at
        order_revenue[order.id] = converter.convert(native_amount, order.currency, occurred_at)
    current_converted = [order_revenue[order.id] for order in current_orders if order_revenue[order.id] is not None]
    comparison_converted = [
        order_revenue[order.id] for order in comparison_orders if order_revenue[order.id] is not None
    ]
    revenue_total = sum(current_converted, Decimal("0")) if current_converted else None
    previous_revenue = sum(comparison_converted, Decimal("0")) if comparison_converted else None

    converted_expenses: dict[str, Decimal | None] = {
        item.id: converter.convert(item.amount, item.currency, item.incurred_on)
        for item in expenses
    }
    current_expense_values = [
        converted_expenses[item.id]
        for item in current_expenses
        if converted_expenses[item.id] is not None
    ]
    expense_total = sum(current_expense_values, Decimal("0")) if current_expense_values else Decimal("0")

    current_order_ids = [order.id for order in current_orders]
    line_items = list(
        db.scalars(
            select(OrderLineItem).where(
                OrderLineItem.organization_id == organization_id,
                OrderLineItem.order_id.in_(current_order_ids) if current_order_ids else False,
            )
        ).all()
    )
    converted_line_costs: list[Decimal] = []
    cost_eligible_lines = 0
    unit_count = 0
    unmatched_line_count = 0
    for item in line_items:
        unit_count += item.quantity
        if item.mapping_status == "unmatched":
            unmatched_line_count += 1
        native_cost = sum(
            (
                item.production_cost_amount or Decimal("0"),
                item.shipping_cost_amount or Decimal("0"),
                item.provider_fee_amount or Decimal("0"),
                item.refund_amount or Decimal("0"),
            ),
            Decimal("0"),
        )
        if any(
            value is not None
            for value in (
                item.production_cost_amount,
                item.shipping_cost_amount,
                item.provider_fee_amount,
                item.refund_amount,
            )
        ):
            order = next((candidate for candidate in current_orders if candidate.id == item.order_id), None)
            occurred_at = order.order_created_at if order and order.order_created_at else item.created_at
            converted = converter.convert(native_cost, item.currency, occurred_at)
            if converted is not None:
                converted_line_costs.append(converted)
                cost_eligible_lines += 1

    orders_with_lines = {item.order_id for item in line_items}
    cost_coverage_complete = (
        bool(current_orders)
        and orders_with_lines == set(current_order_ids)
        and cost_eligible_lines == len(line_items)
    )
    gross_profit = (
        revenue_total - sum(converted_line_costs, Decimal("0"))
        if revenue_total is not None and cost_coverage_complete
        else None
    )
    net_profit = gross_profit - expense_total if gross_profit is not None else None
    gross_margin = (
        float((gross_profit / revenue_total) * 100)
        if gross_profit is not None and revenue_total not in (None, Decimal("0"))
        else None
    )
    net_margin = (
        float((net_profit / revenue_total) * 100)
        if net_profit is not None and revenue_total not in (None, Decimal("0"))
        else None
    )

    trend_granularity = _trend_granularity(resolved.start, resolved.end)
    current_day_revenue: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    current_day_orders: dict[str, int] = defaultdict(int)
    comparison_day_revenue: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    comparison_day_orders: dict[str, int] = defaultdict(int)
    day_expenses: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    day_line_costs: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for order in current_orders:
        day = _date_key(
            order.order_created_at or order.created_at,
            zone,
            trend_granularity,
        )
        current_day_orders[day] += 1
        if order_revenue[order.id] is not None:
            current_day_revenue[day] += order_revenue[order.id] or Decimal("0")
    for order in comparison_orders:
        day = _date_key(
            order.order_created_at or order.created_at,
            zone,
            trend_granularity,
        )
        comparison_day_orders[day] += 1
        if order_revenue[order.id] is not None:
            comparison_day_revenue[day] += order_revenue[order.id] or Decimal("0")
    for item in current_expenses:
        converted = converted_expenses[item.id]
        if converted is not None:
            day_expenses[_date_key(item.incurred_on, zone, trend_granularity)] += converted
    if cost_coverage_complete:
        current_orders_by_id = {item.id: item for item in current_orders}
        for item in line_items:
            order = current_orders_by_id[item.order_id]
            native_cost = sum(
                (
                    item.production_cost_amount or Decimal("0"),
                    item.shipping_cost_amount or Decimal("0"),
                    item.provider_fee_amount or Decimal("0"),
                    item.refund_amount or Decimal("0"),
                ),
                Decimal("0"),
            )
            converted_cost = converter.convert(
                native_cost,
                item.currency,
                order.order_created_at or item.created_at,
            )
            if converted_cost is not None:
                day_line_costs[
                    _date_key(
                        order.order_created_at or item.created_at,
                        zone,
                        trend_granularity,
                    )
                ] += converted_cost

    current_days = _bucket_periods(
        resolved.start,
        resolved.end,
        zone,
        trend_granularity,
    )
    comparison_days = (
        _bucket_periods(
            resolved.comparison_start,
            resolved.comparison_end,
            zone,
            trend_granularity,
        )
        if resolved.comparison_start and resolved.comparison_end
        else []
    )
    trend = [
        AnalyticsTrendPoint(
            period=day,
            revenue=float(current_day_revenue[day]),
            expenses=float(day_expenses[day]),
            gross_profit=(
                float(current_day_revenue[day] - day_line_costs[day])
                if cost_coverage_complete
                else None
            ),
            net_profit=(
                float(
                    current_day_revenue[day]
                    - day_line_costs[day]
                    - day_expenses[day]
                )
                if cost_coverage_complete
                else None
            ),
            orders=current_day_orders[day],
            comparison_revenue=(
                float(comparison_day_revenue[comparison_days[index]])
                if index < len(comparison_days)
                else None
            ),
            comparison_orders=(
                comparison_day_orders[comparison_days[index]]
                if index < len(comparison_days)
                else None
            ),
        )
        for index, day in enumerate(current_days)
    ]

    connections = list(
        db.scalars(
            select(ProviderStoreConnection).where(
                ProviderStoreConnection.organization_id == organization_id,
                ProviderStoreConnection.deleted_at.is_(None),
            )
        ).all()
    )
    connection_by_id = {item.id: item for item in connections}
    product_statement = select(ProviderProductDraft).where(
        ProviderProductDraft.organization_id == organization_id
    )
    if selected_connection is not None:
        product_statement = product_statement.where(
            ProviderProductDraft.provider_store_connection_id == selected_connection.id
        )
    products = list(db.scalars(product_statement).all())
    product_ids = [product.id for product in products]
    mockup_counts = dict(
        db.execute(
            select(Mockup.provider_product_draft_id, func.count(Mockup.id))
            .where(Mockup.provider_product_draft_id.in_(product_ids) if product_ids else False)
            .group_by(Mockup.provider_product_draft_id)
        ).all()
    )

    lines_by_product: dict[str, list[OrderLineItem]] = defaultdict(list)
    for item in line_items:
        if item.product_id:
            lines_by_product[item.product_id].append(item)
    expenses_by_product: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in current_expenses:
        converted = converted_expenses[item.id]
        if item.product_id and converted is not None:
            expenses_by_product[item.product_id] += converted

    product_rows: list[ProductPerformanceRow] = []
    seo_rows: list[SeoPerformanceRow] = []
    for product in products:
        store = connection_by_id.get(product.provider_store_connection_id)
        score, issues = _seo(product, int(mockup_counts.get(product.id, 0)))
        product_lines = lines_by_product.get(product.id, [])
        product_revenue_values: list[Decimal] = []
        product_cost_values: list[Decimal] = []
        for item in product_lines:
            order = next((candidate for candidate in current_orders if candidate.id == item.order_id), None)
            occurred_at = order.order_created_at if order and order.order_created_at else item.created_at
            revenue = converter.convert(item.revenue_amount, item.currency, occurred_at)
            if revenue is not None:
                product_revenue_values.append(revenue)
            native_cost = sum(
                (
                    item.production_cost_amount or Decimal("0"),
                    item.shipping_cost_amount or Decimal("0"),
                    item.provider_fee_amount or Decimal("0"),
                    item.refund_amount or Decimal("0"),
                ),
                Decimal("0"),
            )
            if any(
                value is not None
                for value in (
                    item.production_cost_amount,
                    item.shipping_cost_amount,
                    item.provider_fee_amount,
                    item.refund_amount,
                )
            ):
                converted_cost = converter.convert(native_cost, item.currency, occurred_at)
                if converted_cost is not None:
                    product_cost_values.append(converted_cost)
        product_revenue = sum(product_revenue_values, Decimal("0")) if product_revenue_values else None
        product_gross = (
            product_revenue - sum(product_cost_values, Decimal("0"))
            if product_revenue is not None and len(product_cost_values) == len(product_lines)
            else None
        )
        product_net = (
            product_gross - expenses_by_product[product.id] if product_gross is not None else None
        )
        margin = (
            float((product_net / product_revenue) * 100)
            if product_net is not None and product_revenue not in (None, Decimal("0"))
            else None
        )
        product_rows.append(
            ProductPerformanceRow(
                product_id=product.id,
                title=product.title,
                store_connection_id=product.provider_store_connection_id,
                store_label=store.label if store else "Unknown store",
                status=product.status,
                active_days=max((_as_utc(datetime.now(timezone.utc)) - _as_utc(product.created_at)).days, 0),
                units=sum(item.quantity for item in product_lines),
                revenue=float(product_revenue) if product_revenue is not None else None,
                gross_profit=float(product_gross) if product_gross is not None else None,
                net_profit=float(product_net) if product_net is not None else None,
                margin_percent=margin,
                seo_score=score,
                seo_issues=issues,
                profitability_coverage_percent=(
                    100.0 if product_lines and len(product_cost_values) == len(product_lines) else 0.0
                ),
            )
        )
        seo_rows.append(
            SeoPerformanceRow(
                product_id=product.id,
                title=product.title,
                store_label=store.label if store else "Unknown store",
                status=product.status,
                score=score,
                issues=issues,
                title_length=len(product.title.strip()),
                tag_count=len(product.tags_json or []),
                has_description=bool((product.description or "").strip()),
                has_mockups=int(mockup_counts.get(product.id, 0)) > 0,
            )
        )

    store_rows: list[StorePerformanceRow] = []
    visible_connections = [selected_connection] if selected_connection else connections
    for connection in visible_connections:
        store_orders = [
            order for order in current_orders if order.provider_store_connection_id == connection.id
        ]
        store_revenue_values = [
            order_revenue[order.id] for order in store_orders if order_revenue[order.id] is not None
        ]
        store_revenue = sum(store_revenue_values, Decimal("0")) if store_revenue_values else None
        store_expense_values = [
            converted_expenses[item.id]
            for item in current_expenses
            if item.provider_store_connection_id == connection.id
            and converted_expenses[item.id] is not None
        ]
        store_expense = sum(store_expense_values, Decimal("0")) if store_expense_values else Decimal("0")
        store_lines = [item for item in line_items if item.order_id in {order.id for order in store_orders}]
        store_rows.append(
            StorePerformanceRow(
                store_connection_id=connection.id,
                store_label=connection.label,
                provider=connection.provider,
                storefront_type=connection.storefront_type,
                order_count=len(store_orders),
                units=sum(item.quantity for item in store_lines),
                revenue=float(store_revenue) if store_revenue is not None else None,
                expenses=float(store_expense),
                net_profit=None,
                margin_percent=None,
                unmatched_line_count=sum(
                    1 for item in store_lines if item.mapping_status == "unmatched"
                ),
            )
        )

    expense_records = (
        _expense_records(
            current_expenses,
            connections=connection_by_id,
            products={product.id: product for product in products},
        )
        if include_details
        else []
    )
    unmatched_rows = (
        _unmatched_rows(
            line_items,
            orders={order.id: order for order in current_orders},
            connections=connection_by_id,
        )
        if include_details
        else []
    )

    values_by_key = commerce._list_etsy_connection_values(db, organization_id=organization_id)
    etsy_status = commerce._build_etsy_connection_status(
        db,
        actor=actor,
        values_by_key=values_by_key,
    )
    detailed_finance = "transactions_r" in etsy_status.scopes
    warnings: list[str] = []
    missing_revenue_rates = len(current_orders) - len(current_converted)
    missing_expense_rates = len(current_expenses) - len(current_expense_values)
    if missing_revenue_rates:
        warnings.append(
            f"{missing_revenue_rates} order(s) were excluded from money totals because an FX rate is missing."
        )
    if missing_expense_rates:
        warnings.append(
            f"{missing_expense_rates} expense(s) were excluded from money totals because an FX rate is missing."
        )
    if current_orders and not line_items:
        warnings.append(
            "Product profitability is unavailable until order line items are imported and mapped."
        )

    return BusinessAnalyticsResponse(
        generated_at=datetime.now(timezone.utc),
        scope=scope,
        date_range=AnalyticsDateRange(
            preset=resolved.preset,
            start=resolved.start,
            end=resolved.end,
            comparison_start=resolved.comparison_start,
            comparison_end=resolved.comparison_end,
        ),
        currency=reporting_currency,
        timezone=reporting_timezone,
        trend_granularity=trend_granularity,
        summary=BusinessAnalyticsSummary(
            revenue=_money(
                revenue_total,
                currency=reporting_currency,
                eligible_count=len(current_converted),
                total_count=len(current_orders),
            ),
            expenses=_money(
                expense_total,
                currency=reporting_currency,
                eligible_count=len(current_expense_values),
                total_count=len(current_expenses),
            ),
            gross_profit=_money(
                gross_profit,
                currency=reporting_currency,
                eligible_count=cost_eligible_lines,
                total_count=len(line_items),
            ),
            net_profit=_money(
                net_profit,
                currency=reporting_currency,
                eligible_count=cost_eligible_lines,
                total_count=len(line_items),
            ),
            gross_margin_percent=gross_margin,
            net_margin_percent=net_margin,
            order_count=len(current_orders),
            unit_count=unit_count,
            previous_revenue=float(previous_revenue) if previous_revenue is not None else None,
            previous_order_count=len(comparison_orders) if resolved.comparison_start else None,
            unmatched_line_count=unmatched_line_count,
        ),
        trend=trend,
        products=sorted(product_rows, key=lambda item: item.revenue or 0, reverse=True),
        stores=sorted(store_rows, key=lambda item: item.revenue or 0, reverse=True),
        expenses=expense_records if include_details else [],
        seo=(
            sorted(seo_rows, key=lambda item: (item.score, item.title.lower()))
            if include_details
            else []
        ),
        unmatched_lines=unmatched_rows if include_details else [],
        capabilities=AnalyticsCapabilities(
            etsy_connected=etsy_status.is_connected,
            detailed_marketplace_finance=detailed_finance,
            authorization_upgrade_required=etsy_status.is_connected and not detailed_finance,
            actual_search_metrics_available=False,
            unavailable_metrics=[
                "Etsy impressions",
                "Etsy click-through rate",
                "Etsy search terms",
                "Authoritative keyword rank",
            ],
        ),
        warnings=warnings,
    )


def get_business_analytics_detail_page(
    db: Session,
    *,
    actor: ActorContext,
    resource: str,
    store_connection_id: str | None,
    preset: str,
    start: date | None,
    end: date | None,
    currency: str | None,
    timezone_name: str | None,
    page: int,
    page_size: int,
    product_measure: str = "revenue",
) -> AnalyticsDetailPage:
    organization_id = actor.organization_id
    if not organization_id:
        raise HTTPException(status_code=403, detail="Organization context is required.")
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    reporting_currency = (currency or organization.reporting_currency or "PHP").upper()
    if reporting_currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=422, detail="Unsupported reporting currency.")
    reporting_timezone = timezone_name or organization.reporting_timezone or "Asia/Manila"
    zone = _timezone(reporting_timezone)
    _, selected_connection = _scope(
        db,
        organization_id=organization_id,
        store_connection_id=store_connection_id,
    )

    earliest_order_statement = select(func.min(Order.order_created_at)).where(
        Order.organization_id == organization_id
    )
    earliest_expense_statement = select(func.min(Expense.incurred_on)).where(
        Expense.organization_id == organization_id
    )
    earliest_product_statement = select(func.min(ProviderProductDraft.created_at)).where(
        ProviderProductDraft.organization_id == organization_id
    )
    if selected_connection is not None:
        earliest_order_statement = earliest_order_statement.where(
            Order.provider_store_connection_id == selected_connection.id
        )
        earliest_expense_statement = earliest_expense_statement.where(
            Expense.provider_store_connection_id == selected_connection.id
        )
        earliest_product_statement = earliest_product_statement.where(
            ProviderProductDraft.provider_store_connection_id == selected_connection.id
        )
    earliest_activity_at = min(
        (
            value
            for value in (
                db.scalar(earliest_order_statement),
                db.scalar(earliest_expense_statement),
                db.scalar(earliest_product_statement),
            )
            if value is not None
        ),
        default=None,
    )
    resolved = _resolve_range(
        preset=preset,
        zone=zone,
        now=datetime.now(timezone.utc),
        custom_start=start,
        custom_end=end,
        earliest_at=earliest_activity_at,
    )
    offset = (page - 1) * page_size

    if resource == "expenses":
        statement = select(Expense).where(
            Expense.organization_id == organization_id,
            Expense.incurred_on >= resolved.start,
            Expense.incurred_on < resolved.end,
        )
        count_statement = select(func.count(Expense.id)).where(
            Expense.organization_id == organization_id,
            Expense.incurred_on >= resolved.start,
            Expense.incurred_on < resolved.end,
        )
        if selected_connection is not None:
            statement = statement.where(
                Expense.provider_store_connection_id == selected_connection.id
            )
            count_statement = count_statement.where(
                Expense.provider_store_connection_id == selected_connection.id
            )
        total = int(db.scalar(count_statement) or 0)
        expenses = list(
            db.scalars(
                statement.order_by(Expense.incurred_on.desc(), Expense.id.desc())
                .offset(offset)
                .limit(page_size)
            ).all()
        )
        connection_ids = {
            item.provider_store_connection_id
            for item in expenses
            if item.provider_store_connection_id
        }
        product_ids = {item.product_id for item in expenses if item.product_id}
        connections = {
            item.id: item
            for item in db.scalars(
                select(ProviderStoreConnection).where(
                    ProviderStoreConnection.organization_id == organization_id,
                    ProviderStoreConnection.id.in_(connection_ids)
                    if connection_ids
                    else False,
                )
            ).all()
        }
        products = {
            item.id: item
            for item in db.scalars(
                select(ProviderProductDraft).where(
                    ProviderProductDraft.organization_id == organization_id,
                    ProviderProductDraft.id.in_(product_ids) if product_ids else False,
                )
            ).all()
        }
        items: list[
            ProductPerformanceRow | ExpenseRecord | SeoPerformanceRow | UnmatchedOrderLine
        ] = _expense_records(
            expenses,
            connections=connections,
            products=products,
        )
    elif resource == "unmatched":
        filters = [
            OrderLineItem.organization_id == organization_id,
            OrderLineItem.mapping_status == "unmatched",
            Order.order_created_at >= resolved.start,
            Order.order_created_at < resolved.end,
        ]
        if selected_connection is not None:
            filters.append(Order.provider_store_connection_id == selected_connection.id)
        total = int(
            db.scalar(
                select(func.count(OrderLineItem.id))
                .join(
                    Order,
                    (Order.id == OrderLineItem.order_id)
                    & (Order.organization_id == OrderLineItem.organization_id),
                )
                .where(*filters)
            )
            or 0
        )
        page_rows = list(
            db.execute(
                select(OrderLineItem, Order)
                .join(
                    Order,
                    (Order.id == OrderLineItem.order_id)
                    & (Order.organization_id == OrderLineItem.organization_id),
                )
                .where(*filters)
                .order_by(
                    Order.order_created_at.desc(),
                    OrderLineItem.id.desc(),
                )
                .offset(offset)
                .limit(page_size)
            ).all()
        )
        connections = {
            item.id: item
            for item in db.scalars(
                select(ProviderStoreConnection).where(
                    ProviderStoreConnection.organization_id == organization_id
                )
            ).all()
        }
        items = _unmatched_rows(
            [line for line, _order in page_rows],
            orders={order.id: order for _line, order in page_rows},
            connections=connections,
        )
    elif resource in {"products", "seo"}:
        product_rows, seo_rows = _product_and_seo_detail_rows(
            db,
            organization_id=organization_id,
            selected_connection=selected_connection,
            resolved=resolved,
            reporting_currency=reporting_currency,
        )
        if resource == "products":
            if product_measure not in {"revenue", "units", "gross_profit", "net_profit"}:
                raise HTTPException(status_code=422, detail="Unsupported product measure.")
            product_rows.sort(
                key=lambda item: (
                    getattr(item, product_measure) is None,
                    -float(getattr(item, product_measure) or 0),
                    item.title.lower(),
                )
            )
            all_items = product_rows
        else:
            all_items = sorted(
                seo_rows,
                key=lambda item: (item.score, item.title.lower()),
            )
        total = len(all_items)
        items = all_items[offset : offset + page_size]
    else:
        raise HTTPException(status_code=422, detail="Unsupported analytics resource.")

    total_pages = ceil(total / page_size) if total else 0
    return AnalyticsDetailPage(
        resource=resource,
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


def _product_and_seo_detail_rows(
    db: Session,
    *,
    organization_id: str,
    selected_connection: ProviderStoreConnection | None,
    resolved: ResolvedRange,
    reporting_currency: str,
) -> tuple[list[ProductPerformanceRow], list[SeoPerformanceRow]]:
    rates = list(
        db.scalars(
            select(ExchangeRate).where(ExchangeRate.organization_id == organization_id)
        ).all()
    )
    converter = CurrencyConverter(rates, reporting_currency)
    order_statement = select(Order).where(
        Order.organization_id == organization_id,
        Order.order_created_at >= resolved.start,
        Order.order_created_at < resolved.end,
    )
    product_statement = select(ProviderProductDraft).where(
        ProviderProductDraft.organization_id == organization_id
    )
    expense_statement = select(Expense).where(
        Expense.organization_id == organization_id,
        Expense.product_id.is_not(None),
        Expense.incurred_on >= resolved.start,
        Expense.incurred_on < resolved.end,
    )
    if selected_connection is not None:
        order_statement = order_statement.where(
            Order.provider_store_connection_id == selected_connection.id
        )
        product_statement = product_statement.where(
            ProviderProductDraft.provider_store_connection_id == selected_connection.id
        )
        expense_statement = expense_statement.where(
            Expense.provider_store_connection_id == selected_connection.id
        )

    orders = list(db.scalars(order_statement).all())
    etsy_receipt_ids = {
        order.external_order_id for order in orders if order.provider == "etsy"
    }
    orders = [
        order
        for order in orders
        if order.provider == "etsy"
        or not order.marketplace_order_id
        or order.marketplace_order_id not in etsy_receipt_ids
    ]
    orders_by_id = {order.id: order for order in orders}
    products = list(db.scalars(product_statement).all())
    product_ids = [product.id for product in products]
    line_items = list(
        db.scalars(
            select(OrderLineItem).where(
                OrderLineItem.organization_id == organization_id,
                OrderLineItem.product_id.in_(product_ids) if product_ids else False,
                OrderLineItem.order_id.in_(orders_by_id) if orders_by_id else False,
            )
        ).all()
    )
    product_expenses = list(db.scalars(expense_statement).all())
    converted_expenses = {
        item.id: converter.convert(item.amount, item.currency, item.incurred_on)
        for item in product_expenses
    }
    connections = {
        item.id: item
        for item in db.scalars(
            select(ProviderStoreConnection).where(
                ProviderStoreConnection.organization_id == organization_id,
                ProviderStoreConnection.deleted_at.is_(None),
            )
        ).all()
    }
    mockup_counts = dict(
        db.execute(
            select(Mockup.provider_product_draft_id, func.count(Mockup.id))
            .where(Mockup.provider_product_draft_id.in_(product_ids) if product_ids else False)
            .group_by(Mockup.provider_product_draft_id)
        ).all()
    )
    lines_by_product: dict[str, list[OrderLineItem]] = defaultdict(list)
    for item in line_items:
        if item.product_id:
            lines_by_product[item.product_id].append(item)
    expenses_by_product: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in product_expenses:
        converted = converted_expenses[item.id]
        if item.product_id and converted is not None:
            expenses_by_product[item.product_id] += converted

    product_rows: list[ProductPerformanceRow] = []
    seo_rows: list[SeoPerformanceRow] = []
    now = datetime.now(timezone.utc)
    for product in products:
        store = connections.get(product.provider_store_connection_id)
        score, issues = _seo(product, int(mockup_counts.get(product.id, 0)))
        product_lines = lines_by_product.get(product.id, [])
        product_revenue_values: list[Decimal] = []
        product_cost_values: list[Decimal] = []
        for item in product_lines:
            order = orders_by_id.get(item.order_id)
            occurred_at = (
                order.order_created_at
                if order and order.order_created_at
                else item.created_at
            )
            revenue = converter.convert(item.revenue_amount, item.currency, occurred_at)
            if revenue is not None:
                product_revenue_values.append(revenue)
            native_cost = sum(
                (
                    item.production_cost_amount or Decimal("0"),
                    item.shipping_cost_amount or Decimal("0"),
                    item.provider_fee_amount or Decimal("0"),
                    item.refund_amount or Decimal("0"),
                ),
                Decimal("0"),
            )
            if any(
                value is not None
                for value in (
                    item.production_cost_amount,
                    item.shipping_cost_amount,
                    item.provider_fee_amount,
                    item.refund_amount,
                )
            ):
                converted_cost = converter.convert(native_cost, item.currency, occurred_at)
                if converted_cost is not None:
                    product_cost_values.append(converted_cost)
        product_revenue = (
            sum(product_revenue_values, Decimal("0"))
            if product_revenue_values
            else None
        )
        product_gross = (
            product_revenue - sum(product_cost_values, Decimal("0"))
            if product_revenue is not None
            and len(product_cost_values) == len(product_lines)
            else None
        )
        product_net = (
            product_gross - expenses_by_product[product.id]
            if product_gross is not None
            else None
        )
        margin = (
            float((product_net / product_revenue) * 100)
            if product_net is not None
            and product_revenue not in (None, Decimal("0"))
            else None
        )
        product_rows.append(
            ProductPerformanceRow(
                product_id=product.id,
                title=product.title,
                store_connection_id=product.provider_store_connection_id,
                store_label=store.label if store else "Unknown store",
                status=product.status,
                active_days=max((_as_utc(now) - _as_utc(product.created_at)).days, 0),
                units=sum(item.quantity for item in product_lines),
                revenue=float(product_revenue) if product_revenue is not None else None,
                gross_profit=float(product_gross) if product_gross is not None else None,
                net_profit=float(product_net) if product_net is not None else None,
                margin_percent=margin,
                seo_score=score,
                seo_issues=issues,
                profitability_coverage_percent=(
                    100.0
                    if product_lines
                    and len(product_cost_values) == len(product_lines)
                    else 0.0
                ),
            )
        )
        seo_rows.append(
            SeoPerformanceRow(
                product_id=product.id,
                title=product.title,
                store_label=store.label if store else "Unknown store",
                status=product.status,
                score=score,
                issues=issues,
                title_length=len(product.title.strip()),
                tag_count=len(product.tags_json or []),
                has_description=bool((product.description or "").strip()),
                has_mockups=int(mockup_counts.get(product.id, 0)) > 0,
            )
        )
    return product_rows, seo_rows


def _expense_records(
    expenses: list[Expense],
    *,
    connections: dict[str, ProviderStoreConnection],
    products: dict[str, ProviderProductDraft],
) -> list[ExpenseRecord]:
    return [
        ExpenseRecord(
            id=item.id,
            incurred_on=item.incurred_on,
            category=item.category,
            amount=float(item.amount),
            currency=item.currency,
            note=item.note,
            source=item.source,
            provider_store_connection_id=item.provider_store_connection_id,
            store_label=(
                connections[item.provider_store_connection_id].label
                if item.provider_store_connection_id in connections
                else None
            ),
            product_id=item.product_id,
            product_title=products[item.product_id].title if item.product_id in products else None,
            created_at=item.created_at,
        )
        for item in sorted(expenses, key=lambda value: value.incurred_on, reverse=True)
    ]


def _unmatched_rows(
    lines: list[OrderLineItem],
    *,
    orders: dict[str, Order],
    connections: dict[str, ProviderStoreConnection],
) -> list[UnmatchedOrderLine]:
    rows: list[UnmatchedOrderLine] = []
    for item in lines:
        if item.mapping_status != "unmatched":
            continue
        order = orders.get(item.order_id)
        if order is None:
            continue
        connection = connections.get(order.provider_store_connection_id)
        rows.append(
            UnmatchedOrderLine(
                id=item.id,
                order_id=order.id,
                order_display_id=order.display_order_id,
                ordered_at=order.order_created_at,
                title=item.title,
                sku=item.sku,
                external_listing_id=item.external_listing_id,
                quantity=item.quantity,
                revenue_amount=float(item.revenue_amount) if item.revenue_amount is not None else None,
                currency=item.currency,
                store_connection_id=order.provider_store_connection_id,
                store_label=connection.label if connection else "Unknown store",
            )
        )
    return rows[:100]


def create_expense(
    db: Session,
    *,
    actor: ActorContext,
    payload: ExpenseCreateRequest,
) -> ExpenseRecord:
    organization_id = actor.organization_id
    if not organization_id:
        raise HTTPException(status_code=403, detail="Organization context is required.")
    _validate_expense_links(
        db,
        organization_id=organization_id,
        store_connection_id=payload.provider_store_connection_id,
        product_id=payload.product_id,
    )
    expense = Expense(
        organization_id=organization_id,
        incurred_on=payload.incurred_on,
        category=payload.category.strip().lower().replace(" ", "_"),
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        note=(payload.note or "").strip() or None,
        source="manual",
        provider_store_connection_id=payload.provider_store_connection_id,
        product_id=payload.product_id,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return _expense_records(expense and [expense], connections={}, products={})[0]


def update_expense(
    db: Session,
    *,
    actor: ActorContext,
    expense_id: str,
    payload: ExpenseUpdateRequest,
) -> ExpenseRecord:
    organization_id = actor.organization_id
    expense = db.scalar(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.organization_id == organization_id,
            Expense.source == "manual",
        )
    )
    if expense is None:
        raise HTTPException(status_code=404, detail="Manual expense not found.")
    values = payload.model_dump(exclude_unset=True)
    store_id = values.get("provider_store_connection_id", expense.provider_store_connection_id)
    product_id = values.get("product_id", expense.product_id)
    _validate_expense_links(
        db,
        organization_id=organization_id,
        store_connection_id=store_id,
        product_id=product_id,
    )
    if "incurred_on" in values:
        expense.incurred_on = values["incurred_on"]
    if "category" in values:
        expense.category = values["category"].strip().lower().replace(" ", "_")
    if "amount" in values:
        expense.amount = Decimal(str(values["amount"]))
    if "currency" in values:
        expense.currency = values["currency"]
    if "note" in values:
        expense.note = (values["note"] or "").strip() or None
    if "provider_store_connection_id" in values:
        expense.provider_store_connection_id = values["provider_store_connection_id"]
    if "product_id" in values:
        expense.product_id = values["product_id"]
    db.commit()
    db.refresh(expense)
    return _expense_records([expense], connections={}, products={})[0]


def delete_expense(db: Session, *, actor: ActorContext, expense_id: str) -> None:
    expense = db.scalar(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.organization_id == actor.organization_id,
            Expense.source == "manual",
        )
    )
    if expense is None:
        raise HTTPException(status_code=404, detail="Manual expense not found.")
    db.delete(expense)
    db.commit()


def _validate_expense_links(
    db: Session,
    *,
    organization_id: str,
    store_connection_id: str | None,
    product_id: str | None,
) -> None:
    if store_connection_id and db.scalar(
        select(ProviderStoreConnection.id).where(
            ProviderStoreConnection.id == store_connection_id,
            ProviderStoreConnection.organization_id == organization_id,
            ProviderStoreConnection.deleted_at.is_(None),
        )
    ) is None:
        raise HTTPException(status_code=422, detail="Expense store is not available.")
    if product_id and db.scalar(
        select(ProviderProductDraft.id).where(
            ProviderProductDraft.id == product_id,
            ProviderProductDraft.organization_id == organization_id,
        )
    ) is None:
        raise HTTPException(status_code=422, detail="Expense product is not available.")


def map_order_line(
    db: Session,
    *,
    actor: ActorContext,
    line_id: str,
    payload: OrderLineMappingRequest,
) -> UnmatchedOrderLine | None:
    line = db.scalar(
        select(OrderLineItem).where(
            OrderLineItem.id == line_id,
            OrderLineItem.organization_id == actor.organization_id,
        )
    )
    if line is None:
        raise HTTPException(status_code=404, detail="Order line not found.")
    product = db.scalar(
        select(ProviderProductDraft).where(
            ProviderProductDraft.id == payload.product_id,
            ProviderProductDraft.organization_id == actor.organization_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=422, detail="Product is not available.")
    line.product_id = product.id
    line.mapping_status = "manual"
    line.mapped_by_user_id = actor.actor_id
    line.mapped_at = datetime.now(timezone.utc)
    db.commit()
    return None


def update_analytics_preferences(
    db: Session,
    *,
    actor: ActorContext,
    payload: AnalyticsPreferencesUpdateRequest,
) -> AnalyticsPreferencesResponse:
    organization = db.get(Organization, actor.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if payload.reporting_timezone is not None:
        _timezone(payload.reporting_timezone)
        organization.reporting_timezone = payload.reporting_timezone
    if payload.reporting_currency is not None:
        organization.reporting_currency = payload.reporting_currency
    db.commit()
    return AnalyticsPreferencesResponse(
        reporting_currency=organization.reporting_currency,
        reporting_timezone=organization.reporting_timezone,
    )
