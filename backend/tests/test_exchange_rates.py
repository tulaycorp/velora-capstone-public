from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

import app.services.exchange_rates as exchange_rates
from app.db.models import ExchangeRate, Order, ProviderStoreConnection
from app.services.business_analytics import CurrencyConverter


def test_sync_historical_exchange_rates_persists_daily_eur_rates(client, monkeypatch) -> None:
    occurred_at = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="fx-store",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="fx-store",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="FX Store",
                status="connected",
            )
        )
        db.flush()
        db.add(
            Order(
                organization_id="default-org",
                provider_store_connection_id="fx-store",
                provider="printify",
                external_order_id="fx-order",
                display_order_id="FX order",
                fulfillment_status="fulfilled",
                currency="USD",
                total_amount=Decimal("25.00"),
                retail_amount=Decimal("25.00"),
                order_created_at=occurred_at,
            )
        )
        db.commit()

    monkeypatch.setattr(
        exchange_rates,
        "_fetch_frankfurter_timeseries",
        lambda **_kwargs: {
            "rates": {
                "2026-07-20": {"USD": 1.2, "JPY": 180, "PHP": 68},
            }
        },
    )

    with client.app.state.testing_session_local() as db:
        result = exchange_rates.sync_historical_exchange_rates(
            db,
            organization_id="default-org",
            now=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        )
        rates = list(
            db.scalars(
                select(ExchangeRate).where(
                    ExchangeRate.organization_id == "default-org"
                )
            ).all()
        )

    assert result.rates_processed == 3
    assert {(rate.base_currency, rate.quote_currency) for rate in rates} == {
        ("EUR", "JPY"),
        ("EUR", "PHP"),
        ("EUR", "USD"),
    }


def test_currency_converter_triangulates_and_uses_latest_prior_rate() -> None:
    observation = datetime(2026, 7, 17, tzinfo=timezone.utc)
    converter = CurrencyConverter(
        [
            ExchangeRate(
                organization_id="default-org",
                base_currency="EUR",
                quote_currency="USD",
                effective_on=observation,
                rate=Decimal("1.25"),
                source="frankfurter",
            ),
            ExchangeRate(
                organization_id="default-org",
                base_currency="EUR",
                quote_currency="PHP",
                effective_on=observation,
                rate=Decimal("72.50"),
                source="frankfurter",
            ),
        ],
        "PHP",
    )

    converted = converter.convert(
        Decimal("100"),
        "USD",
        datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
    )

    assert converted == Decimal("5800")
