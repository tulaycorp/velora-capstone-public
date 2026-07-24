from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

import app.jobs.publishing as publishing_jobs
from app.db.models import ProviderProductDraft, PublishingJob, PublishingOutbox, SyncJob
from tests.media_fixtures import VALID_PNG_BYTES


def _create_publishable_product(
    client,
    *,
    title: str = "Durable Publish Listing",
    retail_price: float | None = 39.99,
    include_mockup: bool = True,
    design_description: str | None = "Private artwork direction",
) -> dict[str, object]:
    credentials_response = client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    )
    assert credentials_response.status_code == 200
    sync_response = client.post("/provider-store-connections/sync/printify")
    assert sync_response.status_code == 200
    provider_store_connection_id = sync_response.json()["connections"][0]["id"]
    asset_response = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    )
    assert asset_response.status_code == 201
    blueprint_response = client.post(
        "/blueprints",
        json={
            "name": "Durable Publish Blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": provider_store_connection_id,
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/durable-template",
        },
    )
    assert blueprint_response.status_code == 201
    blueprint_id = blueprint_response.json()["id"]
    assert client.post(f"/blueprints/{blueprint_id}/validate-reference").status_code == 200
    product_response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint_id,
            "design_asset_id": asset_response.json()["id"],
            "title": title,
            "description": "A durable publishing test listing.",
            "tags": ["durable", "publishing"],
            "retail_price": retail_price,
            "currency": "USD",
            "sku": "DURABLE-001",
            "design_description": design_description,
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()
    if include_mockup:
        mockup_response = client.post(
            f"/products/{product['id']}/mockups",
            files={"file": ("listing.png", VALID_PNG_BYTES, "image/png")},
        )
        assert mockup_response.status_code == 201
        product = client.get(f"/products/{product['id']}").json()
    return product


def _make_outbox_due(client, publishing_job_id: str) -> None:
    with client.app.state.testing_session_local() as session:
        outbox = session.scalar(
            select(PublishingOutbox).where(
                PublishingOutbox.publishing_job_id == publishing_job_id
            )
        )
        assert outbox is not None
        outbox.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()


def test_duplicate_publish_clicks_share_one_transactional_job_and_outbox(
    client,
    monkeypatch,
) -> None:
    product = _create_publishable_product(client)

    def broker_unavailable(_publishing_job_id: str) -> None:
        raise RuntimeError("Redis unavailable")

    monkeypatch.setattr(publishing_jobs.publish_product, "send", broker_unavailable)
    first_response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )
    second_response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_job = first_response.json()["job"]
    assert second_response.json()["job"]["id"] == first_job["id"]
    assert first_job["product_revision"] == product["revision"]
    with client.app.state.testing_session_local() as session:
        assert session.scalar(select(func.count()).select_from(PublishingJob)) == 1
        assert session.scalar(
            select(func.count()).select_from(SyncJob).where(
                SyncJob.job_type == "product_publish"
            )
        ) == 1
        assert session.scalar(select(func.count()).select_from(PublishingOutbox)) == 1


def test_product_reads_and_publish_snapshots_refresh_signed_media_urls(client, monkeypatch) -> None:
    product = _create_publishable_product(client)
    storage = client.app.state.fake_storage
    monkeypatch.setattr(
        storage,
        "build_public_url",
        lambda storage_key: f"https://fresh-signed.test/{storage_key}",
    )
    monkeypatch.setattr(
        publishing_jobs.publish_product,
        "send",
        lambda _publishing_job_id: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
    )

    refreshed_product = client.get(f"/products/{product['id']}").json()
    assert refreshed_product["design_asset"]["public_url"].startswith("https://fresh-signed.test/")
    assert refreshed_product["mockups"][0]["public_url"].startswith("https://fresh-signed.test/")

    response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )
    assert response.status_code == 200
    with client.app.state.testing_session_local() as session:
        job = session.get(PublishingJob, response.json()["job"]["id"])
        assert job is not None
        provider_input = job.submitted_snapshot_json["provider_input"]
        assert provider_input["design_asset_url"].startswith("https://fresh-signed.test/")
        assert provider_input["mockup_urls"] == []
        assert [image["file_name"] for image in job.submitted_snapshot_json["etsy_listing_images"]] == [
            "listing.png"
        ]


def test_pending_outbox_survives_api_dispatch_failure_and_uses_immutable_snapshot(
    client,
    monkeypatch,
) -> None:
    product = _create_publishable_product(client, title="Submitted Revision Title")
    immediate_send = publishing_jobs.publish_product.send
    monkeypatch.setattr(
        publishing_jobs.publish_product,
        "send",
        lambda _publishing_job_id: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
    )
    publish_response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )
    assert publish_response.status_code == 200
    job = publish_response.json()["job"]
    assert job["status"] == "queued"

    update_response = client.patch(
        f"/products/{product['id']}",
        json={
            "title": "Later Unsaved Publish Revision",
            "expected_revision": product["revision"],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["revision"] == product["revision"] + 1

    _make_outbox_due(client, job["id"])
    monkeypatch.setattr(publishing_jobs.publish_product, "send", immediate_send)
    assert publishing_jobs.dispatch_publishing_outbox(publishing_job_id=job["id"]) == 1

    completed_job = client.get(f"/publishing-jobs/{job['id']}").json()
    assert completed_job["status"] == "succeeded"
    assert completed_job["product_revision"] == product["revision"]
    fake_adapter = client.app.state.fake_printify_adapter_class
    provider_product_id = f"pf-{product['id']}"
    assert fake_adapter.created_products[provider_product_id]["payload"]["title"] == "Submitted Revision Title"


def test_worker_retry_reuses_persisted_provider_product(client) -> None:
    product = _create_publishable_product(client)
    fake_adapter = client.app.state.fake_printify_adapter_class
    fake_adapter.publish_failures_remaining = 1

    response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )

    assert response.status_code == 200
    job_id = response.json()["job"]["id"]
    job = client.get(f"/publishing-jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["retry_count"] == 1
    assert list(fake_adapter.created_products) == [f"pf-{product['id']}"]
    with client.app.state.testing_session_local() as session:
        sync_job = session.scalar(
            select(SyncJob)
            .join(PublishingJob, PublishingJob.sync_job_id == SyncJob.id)
            .where(PublishingJob.id == job_id)
        )
        assert sync_job is not None
        assert sync_job.status == "completed"
        assert sync_job.attempt_count == 2
        outbox = session.scalar(
            select(PublishingOutbox).where(PublishingOutbox.publishing_job_id == job_id)
        )
        assert outbox is not None
        assert outbox.status == "dispatched"
        assert outbox.lease_owner is None

    filtered_jobs = client.get(
        "/publishing-jobs",
        params={"product_id": product["id"]},
    )
    assert filtered_jobs.status_code == 200
    assert [item["id"] for item in filtered_jobs.json()] == [job_id]
    assert client.get(
        "/publishing-jobs",
        params={"product_id": "another-product"},
    ).json() == []


def test_etsy_image_retry_resumes_after_metadata_without_touching_provider(client) -> None:
    product = _create_publishable_product(client)
    fake_adapter = client.app.state.fake_printify_adapter_class
    client.app.state.etsy_image_sync_failures_remaining = 1

    response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )

    assert response.status_code == 200
    job = client.get(f"/publishing-jobs/{response.json()['job']['id']}").json()
    assert job["status"] == "succeeded"
    assert job["stage"] == "completed"
    assert job["retry_count"] == 1
    assert list(fake_adapter.created_products) == [f"pf-{product['id']}"]
    assert fake_adapter.updated_products == {}
    assert client.app.state.etsy_listing_sync_attempts == 1
    assert client.app.state.etsy_image_sync_attempts == 2


def test_terminal_publish_failure_preserves_stage_and_sanitized_upstream_error(client) -> None:
    product = _create_publishable_product(client)
    client.app.state.etsy_listing_sync_failures_remaining = 3

    response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )

    assert response.status_code == 200
    job = client.get(f"/publishing-jobs/{response.json()['job']['id']}").json()
    assert job["status"] == "failed"
    assert job["stage"] == "etsy_listing_created"
    assert job["retry_count"] == 3
    assert job["error_message"] == (
        "etsy_metadata_sync: Etsy listing update failed with HTTP 409: request conflict"
    )
    assert client.app.state.etsy_listing_sync_attempts == 3
    assert client.app.state.etsy_image_sync_attempts == 0


def test_send_requeues_terminal_failed_job_for_same_saved_revision(client) -> None:
    product = _create_publishable_product(client)
    initial_response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )
    assert initial_response.status_code == 200
    updated_response = client.patch(
        f"/products/{product['id']}",
        json={"title": "Retry this saved revision", "expected_revision": product["revision"]},
    )
    assert updated_response.status_code == 200
    updated_product = updated_response.json()
    client.app.state.etsy_listing_sync_failures_remaining = 3

    first_response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": updated_product["revision"]},
    )
    assert first_response.status_code == 200
    failed_job = first_response.json()["job"]
    assert client.get(f"/publishing-jobs/{failed_job['id']}").json()["status"] == "failed"

    second_response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": updated_product["revision"]},
    )

    assert second_response.status_code == 200
    assert second_response.json()["job"]["id"] == failed_job["id"]
    retried_job = client.get(f"/publishing-jobs/{failed_job['id']}").json()
    assert retried_job["status"] == "succeeded"
    assert retried_job["stage"] == "completed"
    assert retried_job["error_message"] is None
    assert client.app.state.etsy_listing_sync_attempts == 5
    assert client.app.state.etsy_image_sync_attempts == 2


def test_expired_publishing_worker_is_reaped_and_republished_once(
    client,
    monkeypatch,
) -> None:
    product = _create_publishable_product(client)
    immediate_send = publishing_jobs.publish_product.send
    monkeypatch.setattr(
        publishing_jobs.publish_product,
        "send",
        lambda _publishing_job_id: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
    )
    response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )
    assert response.status_code == 200
    job_id = response.json()["job"]["id"]
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    with client.app.state.testing_session_local() as session:
        job = session.get(PublishingJob, job_id)
        assert job is not None
        sync_job = session.get(SyncJob, job.sync_job_id)
        draft = session.get(ProviderProductDraft, job.provider_product_draft_id)
        outbox = session.scalar(
            select(PublishingOutbox).where(PublishingOutbox.publishing_job_id == job_id)
        )
        assert sync_job is not None and draft is not None and outbox is not None
        sync_job.status = "running"
        sync_job.lease_owner = "terminated-worker"
        sync_job.lease_expires_at = expired_at
        sync_job.heartbeat_at = expired_at
        sync_job.attempt_count = 1
        job.status = "running"
        draft.publishing_status = "publishing"
        outbox.status = "dispatched"
        outbox.dispatched_at = expired_at
        session.commit()

    monkeypatch.setattr(publishing_jobs.publish_product, "send", immediate_send)
    publishing_jobs.reap_expired_publishing_jobs.fn()

    completed_job = client.get(f"/publishing-jobs/{job_id}").json()
    assert completed_job["status"] == "succeeded"
    assert completed_job["retry_count"] == 1
    fake_adapter = client.app.state.fake_printify_adapter_class
    assert list(fake_adapter.created_products) == [f"pf-{product['id']}"]
    with client.app.state.testing_session_local() as session:
        sync_job = session.scalar(
            select(SyncJob)
            .join(PublishingJob, PublishingJob.sync_job_id == SyncJob.id)
            .where(PublishingJob.id == job_id)
        )
        assert sync_job is not None
        assert sync_job.status == "completed"
        assert sync_job.attempt_count == 2


def test_publish_rejects_stale_expected_revision(client) -> None:
    product = _create_publishable_product(client)

    response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"] + 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_product_revision"


def test_publish_returns_field_addressable_readiness_failures(client) -> None:
    product = _create_publishable_product(
        client,
        retail_price=None,
        include_mockup=False,
    )

    response = client.post(
        f"/products/{product['id']}/publish",
        json={"expected_revision": product["revision"]},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "publish_not_ready"
    assert {issue["field"] for issue in detail["fields"]} == {
        "retail_price",
        "mockups",
    }
    with client.app.state.testing_session_local() as session:
        assert session.scalar(select(func.count()).select_from(PublishingJob)) == 0
        assert session.scalar(select(func.count()).select_from(PublishingOutbox)) == 0


def test_design_description_and_media_changes_survive_reload_and_advance_revision(client) -> None:
    product = _create_publishable_product(
        client,
        include_mockup=False,
        design_description="Initial private direction",
    )
    initial_revision = product["revision"]
    updated_response = client.patch(
        f"/products/{product['id']}",
        json={
            "design_description": "Updated private direction",
            "expected_revision": initial_revision,
        },
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["revision"] == initial_revision + 1

    mockup_response = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("listing.png", VALID_PNG_BYTES, "image/png")},
    )
    assert mockup_response.status_code == 201
    reloaded = client.get(f"/products/{product['id']}").json()

    assert reloaded["design_description"] == "Updated private direction"
    assert reloaded["revision"] == updated["revision"] + 1

    second_mockup_response = client.post(
        f"/products/{product['id']}/mockups",
        files={"file": ("listing-two.png", VALID_PNG_BYTES, "image/png")},
    )
    assert second_mockup_response.status_code == 201
    second_mockup = second_mockup_response.json()
    after_second_upload = client.get(f"/products/{product['id']}").json()
    assert after_second_upload["revision"] == reloaded["revision"] + 1

    reversed_ids = [second_mockup["id"], mockup_response.json()["id"]]
    reorder_response = client.patch(
        f"/products/{product['id']}/mockups/order",
        json={"mockup_ids": reversed_ids},
    )
    assert reorder_response.status_code == 200
    reordered = reorder_response.json()
    assert reordered["revision"] == after_second_upload["revision"] + 1

    no_op_reorder_response = client.patch(
        f"/products/{product['id']}/mockups/order",
        json={"mockup_ids": reversed_ids},
    )
    assert no_op_reorder_response.status_code == 200
    assert no_op_reorder_response.json()["revision"] == reordered["revision"]

    delete_response = client.delete(
        f"/products/{product['id']}/mockups/{second_mockup['id']}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["revision"] == reordered["revision"] + 1
