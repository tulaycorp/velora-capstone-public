from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func, select

import app.services.etsy_sales as etsy_sales
from app.db.models import (
    DesignAsset,
    Expense,
    Order,
    OrderLineItem,
    ProductBlueprint,
    ProviderProductDraft,
    ProviderStoreConnection,
)


def test_etsy_sales_sync_reports_missing_connection_as_blocked(client, monkeypatch) -> None:
    monkeypatch.setattr(
        etsy_sales.commerce,
        "_list_etsy_connection_values",
        lambda _db, *, organization_id: {},
    )

    with client.app.state.testing_session_local() as db:
        result = etsy_sales.sync_etsy_marketplace_sales(
            db,
            organization_id="default-org",
        )

    assert result.outcome == "blocked"
    assert result.blocker == "Connect Etsy before importing marketplace sales."
    assert result.to_result_json()["records_imported"] == 0


def test_etsy_sales_sync_reports_missing_finance_permission_as_blocked(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        etsy_sales.commerce,
        "_list_etsy_connection_values",
        lambda _db, *, organization_id: {
            "seller-1": {
                "refresh_token": "refresh-token",
                "scopes": ["shops_r"],
                "shops": [{"shop_id": "12345"}],
            }
        },
    )

    with client.app.state.testing_session_local() as db:
        result = etsy_sales.sync_etsy_marketplace_sales(
            db,
            organization_id="default-org",
        )

    assert result.outcome == "blocked"
    assert "analytics access" in (result.blocker or "")


def test_etsy_sales_sync_reports_unmapped_shop_as_blocked(client, monkeypatch) -> None:
    monkeypatch.setattr(
        etsy_sales.commerce,
        "_list_etsy_connection_values",
        lambda _db, *, organization_id: {
            "seller-1": {
                "refresh_token": "refresh-token",
                "scopes": ["shops_r", "transactions_r"],
                "shops": [{"shop_id": "unmapped-shop"}],
            }
        },
    )

    with client.app.state.testing_session_local() as db:
        result = etsy_sales.sync_etsy_marketplace_sales(
            db,
            organization_id="default-org",
        )

    assert result.outcome == "blocked"
    assert result.skipped_shops == 1
    assert "Map a connected Velora store" in (result.blocker or "")


def test_etsy_sales_sync_distinguishes_successful_no_data_import(client, monkeypatch) -> None:
    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="etsy-no-data-store",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="printify-shop",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="No Data Shop",
                etsy_shop_id="no-data-shop",
                status="connected",
            )
        )
        db.commit()

    monkeypatch.setattr(
        etsy_sales.commerce,
        "_list_etsy_connection_values",
        lambda _db, *, organization_id: {
            "seller-1": {
                "refresh_token": "refresh-token",
                "seller_user_id": "seller-1",
                "scopes": ["shops_r", "transactions_r"],
                "shops": [{"shop_id": "no-data-shop"}],
            }
        },
    )
    monkeypatch.setattr(etsy_sales, "_refresh_access_token", lambda _token: "access-token")
    monkeypatch.setattr(etsy_sales, "fetch_etsy_shop_receipts", lambda **_kwargs: [])
    monkeypatch.setattr(etsy_sales, "fetch_etsy_ledger_entries", lambda **_kwargs: [])
    monkeypatch.setattr(
        etsy_sales,
        "sync_historical_exchange_rates",
        lambda *_args, **_kwargs: SimpleNamespace(rates_processed=0),
    )

    with client.app.state.testing_session_local() as db:
        result = etsy_sales.sync_etsy_marketplace_sales(
            db,
            organization_id="default-org",
        )

    assert result.outcome == "completed_no_data"
    assert result.blocker is None
    assert result.to_result_json()["records_imported"] == 0


def test_etsy_sales_sync_is_marketplace_first_and_idempotent(client, monkeypatch) -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderStoreConnection(
                id="etsy-sales-store",
                organization_id="default-org",
                provider="printify",
                credential_key="default",
                provider_store_id="printify-shop",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Etsy Sales Shop",
                etsy_shop_id="12345",
                status="connected",
            )
        )
        db.add(
            DesignAsset(
                id="etsy-sales-asset",
                organization_id="default-org",
                file_name="source.png",
                content_type="image/png",
                size_bytes=100,
                storage_key="organizations/default-org/etsy-sales/source.png",
            )
        )
        db.add(
            ProductBlueprint(
                id="etsy-sales-blueprint",
                organization_id="default-org",
                provider="printify",
                provider_store_connection_id="etsy-sales-store",
                name="Poster",
                category="Wall Art",
                status="active",
                reference_type="product",
                reference_value="template",
            )
        )
        db.flush()
        db.add(
            ProviderProductDraft(
                id="etsy-sales-product",
                organization_id="default-org",
                blueprint_id="etsy-sales-blueprint",
                provider="printify",
                provider_store_connection_id="etsy-sales-store",
                design_asset_id="etsy-sales-asset",
                status="published",
                validation_status="validated",
                publishing_status="succeeded",
                title="Mapped Etsy Poster",
                sku="POSTER-1",
                external_listing_id="98765",
            )
        )
        db.commit()

    monkeypatch.setattr(
        etsy_sales.commerce,
        "_list_etsy_connection_values",
        lambda _db, *, organization_id: {
            "seller-1": {
                "refresh_token": "refresh-token",
                "seller_user_id": "seller-1",
                "scopes": ["shops_r", "transactions_r"],
                "shops": [{"shop_id": "12345", "shop_name": "Sales Shop"}],
            }
        },
    )
    monkeypatch.setattr(etsy_sales, "_refresh_access_token", lambda _token: "access-token")
    monkeypatch.setattr(
        etsy_sales,
        "fetch_etsy_shop_receipts",
        lambda **_kwargs: [
            {
                "receipt_id": 444,
                "status": "paid",
                "is_paid": True,
                "created_timestamp": int(now.timestamp()),
                "grandtotal": {
                    "amount": 5000,
                    "divisor": 100,
                    "currency_code": "USD",
                },
                "transactions": [
                    {
                        "transaction_id": 555,
                        "listing_id": 98765,
                        "title": "Mapped Etsy Poster",
                        "quantity": 2,
                        "price": {
                            "amount": 2500,
                            "divisor": 100,
                            "currency_code": "USD",
                        },
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(
        etsy_sales,
        "fetch_etsy_receipt_transactions",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Embedded receipt transactions should be used.")
        ),
    )
    monkeypatch.setattr(
        etsy_sales,
        "fetch_etsy_ledger_entries",
        lambda **_kwargs: [
            {
                "entry_id": 777,
                "amount": -650,
                "currency": "USD",
                "ledger_type": "transaction_fee",
                "description": "Etsy transaction fee",
                "created_timestamp": int(now.timestamp()),
            }
        ],
    )
    monkeypatch.setattr(
        etsy_sales,
        "get_cached_etsy_refresh_token",
        lambda _token: "refresh-token",
    )
    monkeypatch.setattr(
        etsy_sales,
        "sync_historical_exchange_rates",
        lambda *_args, **_kwargs: SimpleNamespace(rates_processed=12),
    )

    with client.app.state.testing_session_local() as db:
        first = etsy_sales.sync_etsy_marketplace_sales(
            db,
            organization_id="default-org",
            now=now,
        )
    with client.app.state.testing_session_local() as db:
        second = etsy_sales.sync_etsy_marketplace_sales(
            db,
            organization_id="default-org",
            now=now,
        )
        order = db.scalar(
            select(Order).where(Order.provider == "etsy", Order.external_order_id == "444")
        )
        line = db.scalar(
            select(OrderLineItem).where(OrderLineItem.external_line_id == "555")
        )
        expense = db.scalar(
            select(Expense).where(Expense.source == "etsy", Expense.external_id == "12345:777")
        )
        assert db.scalar(select(func.count(Order.id)).where(Order.provider == "etsy")) == 1
        assert db.scalar(select(func.count(OrderLineItem.id))) == 1
        assert db.scalar(select(func.count(Expense.id)).where(Expense.source == "etsy")) == 1

    assert first.receipts_processed == 1
    assert second.receipts_processed == 1
    assert order is not None
    assert order.total_amount == Decimal("50.00")
    assert order.raw_payload_json is None
    assert line is not None
    assert line.product_id == "etsy-sales-product"
    assert line.mapping_status == "matched"
    assert line.revenue_amount == Decimal("50.00")
    assert expense is not None
    assert expense.amount == Decimal("6.50")
    assert first.exchange_rates_processed == 12
