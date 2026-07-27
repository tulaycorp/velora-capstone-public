from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Expense, Order, OrderLineItem, ProviderProductDraft, ProviderStoreConnection
from app.services import provider_connections as commerce
from app.services.exchange_rates import sync_historical_exchange_rates
from app.services.etsy import (
    _refresh_access_token,
    fetch_etsy_ledger_entries,
    fetch_etsy_receipt_transactions,
    fetch_etsy_shop_receipts,
    get_cached_etsy_refresh_token,
)


@dataclass(frozen=True)
class EtsySalesSyncResult:
    outcome: str = "completed"
    blocker: str | None = None
    accounts_processed: int = 0
    shops_processed: int = 0
    receipts_processed: int = 0
    lines_processed: int = 0
    expenses_processed: int = 0
    exchange_rates_processed: int = 0
    exchange_rate_sync_failed: bool = False
    skipped_shops: int = 0

    def to_result_json(self) -> dict[str, int | bool | str | None]:
        return {
            "outcome": self.outcome,
            "blocker": self.blocker,
            "accounts_processed": self.accounts_processed,
            "shops_processed": self.shops_processed,
            "receipts_processed": self.receipts_processed,
            "lines_processed": self.lines_processed,
            "expenses_processed": self.expenses_processed,
            "exchange_rates_processed": self.exchange_rates_processed,
            "exchange_rate_sync_failed": self.exchange_rate_sync_failed,
            "skipped_shops": self.skipped_shops,
            "records_imported": (
                self.receipts_processed
                + self.lines_processed
                + self.expenses_processed
            ),
        }


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and value > 0:
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _money(value: object, *, default_currency: str | None = None) -> tuple[Decimal | None, str | None]:
    if isinstance(value, dict):
        raw_amount = value.get("amount")
        raw_divisor = value.get("divisor") or 1
        currency = str(
            value.get("currency_code")
            or value.get("currency")
            or default_currency
            or ""
        ).upper() or None
        try:
            return Decimal(str(raw_amount)) / Decimal(str(raw_divisor)), currency
        except (InvalidOperation, TypeError, ZeroDivisionError):
            return None, currency
    try:
        return Decimal(str(value)), str(default_currency or "").upper() or None
    except (InvalidOperation, TypeError):
        return None, str(default_currency or "").upper() or None


def _ledger_money(entry: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    amount, currency = _money(entry.get("amount"), default_currency=entry.get("currency"))
    if amount is None:
        return None, currency
    # Etsy ledger integer amounts are minor currency units.
    if not isinstance(entry.get("amount"), dict):
        amount /= Decimal("100")
    return amount, currency


def _first_string(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return None


def _find_product(
    products: list[ProviderProductDraft],
    *,
    listing_id: str | None,
    external_product_id: str | None,
    sku: str | None,
) -> ProviderProductDraft | None:
    for product in products:
        if listing_id and product.external_listing_id == listing_id:
            return product
    for product in products:
        if external_product_id and product.provider_product_id == external_product_id:
            return product
    for product in products:
        if sku and product.sku == sku:
            return product
    return None


def sync_etsy_marketplace_sales(
    db: Session,
    *,
    organization_id: str,
    now: datetime | None = None,
) -> EtsySalesSyncResult:
    synced_at = now or datetime.now(timezone.utc)
    values_by_key = commerce._list_etsy_connection_values(
        db,
        organization_id=organization_id,
    )
    if not values_by_key:
        return EtsySalesSyncResult(
            outcome="blocked",
            blocker="Connect Etsy before importing marketplace sales.",
        )

    refreshable_accounts = [
        values
        for values in values_by_key.values()
        if str(values.get("refresh_token") or "").strip()
    ]
    if not refreshable_accounts:
        return EtsySalesSyncResult(
            outcome="blocked",
            blocker="Reconnect Etsy because no usable refresh token is available.",
        )

    authorized_accounts = [
        values
        for values in refreshable_accounts
        if "transactions_r"
        in {str(item).strip() for item in values.get("scopes", [])}
    ]
    if not authorized_accounts:
        return EtsySalesSyncResult(
            outcome="blocked",
            blocker="Grant Etsy analytics access to import receipts, transactions, and fees.",
        )

    discovered_shop_ids = {
        shop_id
        for values in authorized_accounts
        for shop in values.get("shops", [])
        if isinstance(shop, dict)
        if (shop_id := _first_string(shop, "shop_id"))
    }
    if not discovered_shop_ids:
        return EtsySalesSyncResult(
            outcome="blocked",
            blocker="Refresh Etsy shop discovery before importing marketplace sales.",
        )

    products = list(
        db.scalars(
            select(ProviderProductDraft).where(
                ProviderProductDraft.organization_id == organization_id
            )
        ).all()
    )
    connections = list(
        db.scalars(
            select(ProviderStoreConnection).where(
                ProviderStoreConnection.organization_id == organization_id,
                ProviderStoreConnection.deleted_at.is_(None),
                ProviderStoreConnection.storefront_type == "etsy",
            )
        ).all()
    )
    mapped_shop_ids = {
        connection.etsy_shop_id
        for connection in connections
        if connection.status == "connected" and connection.etsy_shop_id
    }
    if not discovered_shop_ids.intersection(mapped_shop_ids):
        return EtsySalesSyncResult(
            outcome="blocked",
            blocker="Map a connected Velora store to an Etsy shop before importing marketplace sales.",
            skipped_shops=len(discovered_shop_ids),
        )
    existing_marketplace_orders = list(
        db.scalars(
            select(Order).where(
                Order.organization_id == organization_id,
                Order.provider == "etsy",
            )
        ).all()
    )
    orders_by_external_id = {
        order.external_order_id: order for order in existing_marketplace_orders
    }
    existing_order_ids = [order.id for order in existing_marketplace_orders]
    lines_by_order_and_external_id = {
        (line.order_id, line.external_line_id): line
        for line in db.scalars(
            select(OrderLineItem).where(
                OrderLineItem.organization_id == organization_id,
                OrderLineItem.order_id.in_(existing_order_ids)
                if existing_order_ids
                else False,
            )
        ).all()
    }
    expenses_by_external_id = {
        expense.external_id: expense
        for expense in db.scalars(
            select(Expense).where(
                Expense.organization_id == organization_id,
                Expense.source == "etsy",
            )
        ).all()
        if expense.external_id
    }
    latest_marketplace_sync = db.scalar(
        select(Order.last_synced_at)
        .where(Order.organization_id == organization_id, Order.provider == "etsy")
        .order_by(Order.last_synced_at.desc())
        .limit(1)
    )
    # A first-time history import can spend several minutes paging Etsy. Release
    # the read transaction before provider I/O so Neon cannot terminate an
    # idle-in-transaction connection underneath the eventual bulk write. Keep
    # the fully loaded ORM rows usable without triggering a new transaction.
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = True
    window_start = (
        latest_marketplace_sync - timedelta(hours=24)
        if latest_marketplace_sync is not None
        else None
    )
    accounts_processed = 0
    shops_processed = 0
    receipts_processed = 0
    lines_processed = 0
    expenses_processed = 0
    skipped_shops = 0

    for credential_key, values in values_by_key.items():
        scopes = {str(item).strip() for item in values.get("scopes", [])}
        refresh_token = str(values.get("refresh_token") or "").strip()
        if "transactions_r" not in scopes or not refresh_token:
            continue
        access_token = _refresh_access_token(refresh_token)
        accounts_processed += 1
        for shop in values.get("shops", []):
            if not isinstance(shop, dict):
                continue
            shop_id = _first_string(shop, "shop_id")
            if not shop_id:
                continue
            shop_connections = sorted(
                [
                    connection
                    for connection in connections
                    if connection.status == "connected"
                    and connection.etsy_shop_id == shop_id
                ],
                key=lambda connection: connection.id,
            )
            if not shop_connections:
                skipped_shops += 1
                continue

            receipts = fetch_etsy_shop_receipts(
                access_token=access_token,
                shop_id=shop_id,
                min_last_modified=window_start,
                max_last_modified=synced_at if window_start is not None else None,
            )
            shops_processed += 1
            earliest_shop_sale_at: datetime | None = None
            for receipt in receipts:
                receipt_id = _first_string(receipt, "receipt_id", "receiptId", "id")
                if not receipt_id:
                    continue
                embedded_transactions = receipt.get("transactions")
                transactions = (
                    [
                        item
                        for item in embedded_transactions
                        if isinstance(item, dict)
                    ]
                    if isinstance(embedded_transactions, list)
                    else []
                )
                if not transactions:
                    transactions = fetch_etsy_receipt_transactions(
                        access_token=access_token,
                        shop_id=shop_id,
                        receipt_id=receipt_id,
                    )
                transaction_products: list[ProviderProductDraft | None] = []
                for transaction in transactions:
                    transaction_products.append(
                        _find_product(
                            products,
                            listing_id=_first_string(transaction, "listing_id", "listingId"),
                            external_product_id=_first_string(
                                transaction,
                                "product_id",
                                "productId",
                            ),
                            sku=_first_string(transaction, "sku"),
                        )
                    )
                matched_product = next(
                    (product for product in transaction_products if product is not None),
                    None,
                )
                connection = (
                    next(
                        (
                            candidate
                            for candidate in shop_connections
                            if matched_product
                            and candidate.id == matched_product.provider_store_connection_id
                        ),
                        None,
                    )
                    or shop_connections[0]
                )
                ordered_at = (
                    _timestamp(
                        receipt.get("created_timestamp")
                        or receipt.get("create_timestamp")
                        or receipt.get("create_date")
                    )
                    or synced_at
                )
                if earliest_shop_sale_at is None or ordered_at < earliest_shop_sale_at:
                    earliest_shop_sale_at = ordered_at
                total, currency = _money(
                    receipt.get("grandtotal")
                    or receipt.get("total_price")
                    or receipt.get("subtotal"),
                    default_currency=receipt.get("currency_code") or receipt.get("currency"),
                )
                existing_order = orders_by_external_id.get(receipt_id)
                order = existing_order or Order(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    provider="etsy",
                    external_order_id=receipt_id,
                    display_order_id=f"Etsy #{receipt_id}",
                    provider_store_connection_id=connection.id,
                    fulfillment_status="open",
                    total_amount=Decimal("0"),
                )
                order.provider_store_connection_id = connection.id
                order.marketplace_order_id = receipt_id
                order.display_order_id = _first_string(receipt, "name") or f"Etsy #{receipt_id}"
                order.fulfillment_status = (
                    "cancelled"
                    if receipt.get("is_canceled") or receipt.get("was_canceled")
                    else str(receipt.get("status") or "open").lower()
                )
                order.financial_status = "paid" if receipt.get("is_paid", True) else "pending"
                order.currency = currency
                order.total_amount = total or Decimal("0")
                order.retail_amount = total
                order.order_created_at = ordered_at
                order.cancelled_at = ordered_at if order.fulfillment_status == "cancelled" else None
                order.last_synced_at = synced_at
                order.raw_payload_json = None
                db.add(order)
                orders_by_external_id[receipt_id] = order

                for index, transaction in enumerate(transactions):
                    transaction_id = (
                        _first_string(transaction, "transaction_id", "transactionId", "id")
                        or f"{receipt_id}:{index}"
                    )
                    product = transaction_products[index]
                    quantity = max(int(transaction.get("quantity") or 1), 1)
                    line_revenue, line_currency = _money(
                        transaction.get("price"),
                        default_currency=currency,
                    )
                    if line_revenue is not None:
                        line_revenue *= quantity
                    line_key = (order.id, transaction_id)
                    line = lines_by_order_and_external_id.get(line_key)
                    if line is None:
                        line = OrderLineItem(
                            organization_id=organization_id,
                            order_id=order.id,
                            external_line_id=transaction_id,
                            title=_first_string(transaction, "title") or "Etsy item",
                        )
                        lines_by_order_and_external_id[line_key] = line
                    line.product_id = product.id if product else None
                    line.external_listing_id = _first_string(
                        transaction,
                        "listing_id",
                        "listingId",
                    )
                    line.external_product_id = _first_string(
                        transaction,
                        "product_id",
                        "productId",
                    )
                    line.sku = _first_string(transaction, "sku")
                    line.title = _first_string(transaction, "title") or "Etsy item"
                    line.quantity = quantity
                    line.currency = line_currency or currency
                    line.revenue_amount = line_revenue
                    line.mapping_status = "matched" if product else "unmatched"
                    line.raw_payload_json = None
                    db.add(line)
                    lines_processed += 1
                receipts_processed += 1

            ledger_entries = fetch_etsy_ledger_entries(
                access_token=access_token,
                shop_id=shop_id,
                min_created=(
                    window_start
                    or earliest_shop_sale_at
                    or synced_at - timedelta(days=365)
                ),
                max_created=synced_at,
            )
            for entry in ledger_entries:
                entry_id = _first_string(entry, "entry_id", "ledger_entry_id", "id")
                amount, currency = _ledger_money(entry)
                if not entry_id or amount is None or amount >= 0 or not currency:
                    continue
                expense_external_id = f"{shop_id}:{entry_id}"
                existing_expense = expenses_by_external_id.get(expense_external_id)
                expense = existing_expense or Expense(
                    organization_id=organization_id,
                    source="etsy",
                    external_id=expense_external_id,
                    amount=Decimal("0"),
                    currency=currency,
                    incurred_on=synced_at,
                    category="marketplace_fee",
                )
                expenses_by_external_id[expense_external_id] = expense
                expense.provider_store_connection_id = shop_connections[0].id
                expense.incurred_on = (
                    _timestamp(
                        entry.get("created_timestamp")
                        or entry.get("create_date")
                    )
                    or synced_at
                )
                expense.category = (
                    _first_string(entry, "ledger_type", "reference_type")
                    or "marketplace_fee"
                ).lower()
                expense.amount = abs(amount)
                expense.currency = currency
                expense.note = _first_string(entry, "description")
                db.add(expense)
                expenses_processed += 1

        next_refresh_token = get_cached_etsy_refresh_token(refresh_token) or refresh_token
        if next_refresh_token != refresh_token:
            commerce._save_etsy_connection_values(
                db,
                organization_id=organization_id,
                credential_key=credential_key,
                refresh_token=next_refresh_token,
                seller_user_id=str(values.get("seller_user_id") or credential_key),
                scopes=list(scopes),
                shops=[shop for shop in values.get("shops", []) if isinstance(shop, dict)],
                last_synced_at=synced_at,
            )

    db.commit()
    exchange_rates_processed = 0
    exchange_rate_sync_failed = False
    try:
        exchange_rate_result = sync_historical_exchange_rates(
            db,
            organization_id=organization_id,
            now=synced_at,
        )
        exchange_rates_processed = exchange_rate_result.rates_processed
    except (httpx.HTTPError, ValueError):
        db.rollback()
        exchange_rate_sync_failed = True
    outcome = "completed"
    blocker = None
    if skipped_shops:
        outcome = "partial"
        blocker = "Some Etsy shops are not mapped to a connected Velora store."
    if exchange_rate_sync_failed:
        outcome = "partial"
        blocker = "Marketplace sales imported, but dated exchange rates could not be refreshed."
    if (
        outcome == "completed"
        and receipts_processed == 0
        and lines_processed == 0
        and expenses_processed == 0
    ):
        outcome = "completed_no_data"

    return EtsySalesSyncResult(
        outcome=outcome,
        blocker=blocker,
        accounts_processed=accounts_processed,
        shops_processed=shops_processed,
        receipts_processed=receipts_processed,
        lines_processed=lines_processed,
        expenses_processed=expenses_processed,
        exchange_rates_processed=exchange_rates_processed,
        exchange_rate_sync_failed=exchange_rate_sync_failed,
        skipped_shops=skipped_shops,
    )
