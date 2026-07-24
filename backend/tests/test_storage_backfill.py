from __future__ import annotations

from app.core.config import settings
from app.db.encryption import encrypt_value
from app.db.models import DesignAsset, Mockup, ProviderCredential, ProviderProductDraft
from app.services.storage_backfill import backfill_org_scoped_asset_keys
from tests.media_fixtures import VALID_PNG_BYTES


def test_non_default_organization_uploads_use_org_scoped_storage_keys(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "default_organization_id", "org-custom")
    with client.app.state.testing_session_local() as db:
        db.add(
            ProviderCredential(
                organization_id="org-custom",
                provider="etsy",
                key_name="oauth_refresh_token",
                encrypted_value=encrypt_value("fixture-etsy-refresh-token"),
            )
        )
        db.commit()

    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200

    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]

    asset_upload_response = client.post(
        "/design-assets",
        files={"file": ("design.PNG", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_upload_response.status_code == 201
    design_asset = asset_upload_response.json()
    assert (
        design_asset["storage_key"]
        == f"organizations/org-custom/design-assets/{design_asset['id']}/source.png"
    )

    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Scoped Storage Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-storage-scope",
        },
    )
    assert blueprint_response.status_code == 201

    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint_response.json()["id"],
            "design_asset_id": design_asset["id"],
            "title": "Scoped Storage Product",
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()

    mockup_response = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("mockup.PNG", VALID_PNG_BYTES, "image/png")},
        data={"position": "0"},
    )
    assert mockup_response.status_code == 201
    mockup = mockup_response.json()
    assert (
        mockup["storage_key"]
        == f"organizations/org-custom/draft-mockups/{product['id']}/{mockup['id']}/source.png"
    )


def test_backfill_org_scoped_asset_keys_migrates_legacy_rows_and_is_idempotent(client) -> None:
    fake_storage = client.app.state.fake_storage
    legacy_design_key = "design-assets/legacy-design-file.JPG"
    legacy_mockup_key = "draft-mockups/draft-legacy/legacy-mockup-file.PNG"

    fake_storage.objects[legacy_design_key] = b"design-bytes"
    fake_storage.objects[legacy_mockup_key] = b"mockup-bytes"

    with client.app.state.testing_session_local() as db:
        design_asset = DesignAsset(
            id="asset-legacy",
            organization_id="org-backfill",
            file_name="legacy-design.JPG",
            content_type="image/jpeg",
            size_bytes=len(fake_storage.objects[legacy_design_key]),
            storage_key=legacy_design_key,
            public_url=fake_storage.build_public_url(legacy_design_key),
            checksum="sha256-design",
        )
        draft = ProviderProductDraft(
            id="draft-legacy",
            organization_id="org-backfill",
            blueprint_id="blueprint-legacy",
            provider="printify",
            provider_store_connection_id="store-legacy",
            design_asset_id=design_asset.id,
            status="draft",
            validation_status="pending",
            publishing_status="not_started",
            title="Legacy Product",
        )
        mockup = Mockup(
            id="mockup-legacy",
            organization_id="org-backfill",
            provider_product_draft_id=draft.id,
            file_name="legacy-mockup.PNG",
            content_type="image/png",
            size_bytes=len(fake_storage.objects[legacy_mockup_key]),
            storage_key=legacy_mockup_key,
            public_url=fake_storage.build_public_url(legacy_mockup_key),
            checksum="sha256-mockup",
            position=0,
        )
        db.add_all([design_asset, draft, mockup])
        db.commit()

    with client.app.state.testing_session_local() as db:
        dry_run_result = backfill_org_scoped_asset_keys(db, apply=False)
        assert dry_run_result.design_assets.scanned == 1
        assert dry_run_result.design_assets.needs_migration == 1
        assert dry_run_result.design_assets.migrated == 0
        assert dry_run_result.mockups.scanned == 1
        assert dry_run_result.mockups.needs_migration == 1
        assert dry_run_result.mockups.migrated == 0

        unchanged_asset = db.get(DesignAsset, "asset-legacy")
        unchanged_mockup = db.get(Mockup, "mockup-legacy")
        assert unchanged_asset is not None
        assert unchanged_asset.storage_key == legacy_design_key
        assert unchanged_mockup is not None
        assert unchanged_mockup.storage_key == legacy_mockup_key

    with client.app.state.testing_session_local() as db:
        applied_result = backfill_org_scoped_asset_keys(db, apply=True)
        assert applied_result.design_assets.migrated == 1
        assert applied_result.mockups.migrated == 1
        assert applied_result.design_assets.missing_source == 0
        assert applied_result.mockups.missing_source == 0

        migrated_asset = db.get(DesignAsset, "asset-legacy")
        migrated_mockup = db.get(Mockup, "mockup-legacy")
        assert migrated_asset is not None
        assert migrated_mockup is not None

        assert (
            migrated_asset.storage_key
            == "organizations/org-backfill/design-assets/asset-legacy/source.jpg"
        )
        assert (
            migrated_mockup.storage_key
            == "organizations/org-backfill/draft-mockups/draft-legacy/mockup-legacy/source.png"
        )
        assert migrated_asset.public_url == fake_storage.build_public_url(migrated_asset.storage_key)
        assert migrated_mockup.public_url == fake_storage.build_public_url(migrated_mockup.storage_key)

    assert legacy_design_key not in fake_storage.objects
    assert legacy_mockup_key not in fake_storage.objects
    assert "organizations/org-backfill/design-assets/asset-legacy/source.jpg" in fake_storage.objects
    assert (
        "organizations/org-backfill/draft-mockups/draft-legacy/mockup-legacy/source.png"
        in fake_storage.objects
    )

    with client.app.state.testing_session_local() as db:
        rerun_result = backfill_org_scoped_asset_keys(db, apply=True)
        assert rerun_result.design_assets.scanned == 1
        assert rerun_result.design_assets.already_scoped == 1
        assert rerun_result.design_assets.migrated == 0
        assert rerun_result.mockups.scanned == 1
        assert rerun_result.mockups.already_scoped == 1
        assert rerun_result.mockups.migrated == 0
