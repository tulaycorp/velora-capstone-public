from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ExchangeRate, Expense, Order


SUPPORTED_CURRENCIES = ("EUR", "JPY", "PHP", "USD")
FRANKFURTER_SOURCE = "frankfurter"


@dataclass(frozen=True)
class ExchangeRateSyncResult:
    rates_processed: int = 0
    start_date: date | None = None
    end_date: date | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fetch_frankfurter_timeseries(*, start_date: date, end_date: date) -> dict[str, Any]:
    symbols = ",".join(currency for currency in SUPPORTED_CURRENCIES if currency != "EUR")
    url = (
        f"{settings.exchange_rate_api_base_url.rstrip('/')}/v1/"
        f"{start_date.isoformat()}..{end_date.isoformat()}"
    )
    with httpx.Client(timeout=settings.exchange_rate_api_timeout_seconds) as client:
        response = client.get(url, params={"base": "EUR", "symbols": symbols})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("rates"), dict):
        raise ValueError("Exchange-rate provider returned an invalid response.")
    return payload


def sync_historical_exchange_rates(
    db: Session,
    *,
    organization_id: str,
    now: datetime | None = None,
) -> ExchangeRateSyncResult:
    synced_at = _as_utc(now or datetime.now(timezone.utc))
    earliest_order = db.scalar(
        select(func.min(Order.order_created_at)).where(
            Order.organization_id == organization_id,
            Order.currency.in_(SUPPORTED_CURRENCIES),
        )
    )
    earliest_expense = db.scalar(
        select(func.min(Expense.incurred_on)).where(
            Expense.organization_id == organization_id,
            Expense.currency.in_(SUPPORTED_CURRENCIES),
        )
    )
    earliest_candidates = [
        _as_utc(value).date()
        for value in (earliest_order, earliest_expense)
        if value is not None
    ]
    if not earliest_candidates:
        return ExchangeRateSyncResult()

    earliest_date = min(earliest_candidates)
    latest_stored = db.scalar(
        select(func.max(ExchangeRate.effective_on)).where(
            ExchangeRate.organization_id == organization_id,
            ExchangeRate.source == FRANKFURTER_SOURCE,
            ExchangeRate.base_currency == "EUR",
        )
    )
    start_date = (
        max(earliest_date, _as_utc(latest_stored).date() - timedelta(days=7))
        if latest_stored is not None
        else earliest_date
    )
    end_date = synced_at.date()
    payload = _fetch_frankfurter_timeseries(start_date=start_date, end_date=end_date)
    range_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    range_end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    existing_rates = {
        (rate.quote_currency, _as_utc(rate.effective_on).date()): rate
        for rate in db.scalars(
            select(ExchangeRate).where(
                ExchangeRate.organization_id == organization_id,
                ExchangeRate.source == FRANKFURTER_SOURCE,
                ExchangeRate.base_currency == "EUR",
                ExchangeRate.quote_currency.in_(
                    currency
                    for currency in SUPPORTED_CURRENCIES
                    if currency != "EUR"
                ),
                ExchangeRate.effective_on >= range_start,
                ExchangeRate.effective_on <= range_end,
            )
        ).all()
    }

    processed = 0
    for raw_date, raw_rates in payload["rates"].items():
        if not isinstance(raw_rates, dict):
            continue
        try:
            effective_date = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        effective_on = datetime.combine(effective_date, time.min, tzinfo=timezone.utc)
        for quote_currency in SUPPORTED_CURRENCIES:
            if quote_currency == "EUR":
                continue
            raw_rate = raw_rates.get(quote_currency)
            try:
                rate_value = Decimal(str(raw_rate))
            except (InvalidOperation, TypeError):
                continue
            if rate_value <= 0:
                continue
            existing = existing_rates.get((quote_currency, effective_date))
            rate = existing or ExchangeRate(
                organization_id=organization_id,
                base_currency="EUR",
                quote_currency=quote_currency,
                effective_on=effective_on,
                rate=rate_value,
                source=FRANKFURTER_SOURCE,
            )
            rate.rate = rate_value
            rate.source = FRANKFURTER_SOURCE
            db.add(rate)
            existing_rates[(quote_currency, effective_date)] = rate
            processed += 1

    db.commit()
    return ExchangeRateSyncResult(
        rates_processed=processed,
        start_date=start_date,
        end_date=end_date,
    )
