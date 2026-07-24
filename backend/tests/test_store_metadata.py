from __future__ import annotations

from app.db.models import ProviderStoreConnection
from app.services.store_metadata import extract_safe_etsy_shop_id, scrub_provider_store_metadata


SENSITIVE_PROVIDER_KEYS = {
    "address",
    "customer",
    "customerReferenceId",
    "firstName",
    "lastName",
    "order",
    "shippingAddress",
}


def _collect_nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested_key
            for nested_value in value.values()
            for nested_key in _collect_nested_keys(nested_value)
        }
    if isinstance(value, list):
        return {
            nested_key
            for item in value
            for nested_key in _collect_nested_keys(item)
        }
    return set()


def test_safe_etsy_shop_id_extractor_ignores_unrelated_customer_data() -> None:
    metadata = {
        "order": {"firstName": "Private", "customerReferenceId": "customer-1"},
        "marketplace": {"shopId": "etsy-safe-shop"},
    }

    assert extract_safe_etsy_shop_id(metadata) == "etsy-safe-shop"


def test_provider_store_response_does_not_expose_raw_metadata(client) -> None:
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        db.add(
            ProviderStoreConnection(
                id="store-browser-boundary",
                organization_id="default-org",
                provider="gelato",
                credential_key="default",
                provider_store_id="gelato-browser-boundary",
                storefront_type="etsy",
                storefront_display_name="Etsy",
                label="Etsy boundary fixture",
                status="connected",
                raw_data_json={
                    "order": {
                        "customer": {
                            "firstName": "Private",
                            "lastName": "Customer",
                        },
                        "shippingAddress": {"address": "Private street"},
                        "customerReferenceId": "private-customer",
                    }
                },
            )
        )
        db.commit()

    response = client.get("/provider-store-connections")

    assert response.status_code == 200
    assert all("raw_data_json" not in item for item in response.json())
    assert _collect_nested_keys(response.json()).isdisjoint(SENSITIVE_PROVIDER_KEYS)


def test_metadata_scrub_dry_run_then_apply(client) -> None:
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        connection = ProviderStoreConnection(
            id="store-metadata-scrub",
            organization_id="default-org",
            provider="gelato",
            credential_key="default",
            provider_store_id="gelato-safe-shop",
            storefront_type="etsy",
            storefront_display_name="Etsy",
            label="Etsy [gelato-safe-shop]",
            status="connected",
            raw_data_json={
                "marketplace": {"shopId": "etsy-safe-shop"},
                "order": {"firstName": "Private"},
            },
        )
        db.add(connection)
        db.commit()

        dry_run = scrub_provider_store_metadata(db, apply=False)
        assert dry_run.metadata_cleared_count == 1

        persisted = db.get(ProviderStoreConnection, connection.id)
        assert persisted is not None
        assert persisted.raw_data_json is not None

        applied = scrub_provider_store_metadata(db, apply=True)
        assert applied.metadata_cleared_count == 1

    with session_factory() as db:
        persisted = db.get(ProviderStoreConnection, "store-metadata-scrub")
        assert persisted is not None
        assert persisted.raw_data_json is None
        assert persisted.etsy_shop_id == "etsy-safe-shop"
