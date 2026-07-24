from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image
from pydantic import ValidationError
import pytest

import app.services.ai_generation as ai_generation
from app.ai.openrouter import OpenRouterResponseError
from app.ai.schemas import (
    ListingOutput,
    ProviderGenerationResult,
    ProviderTargetedGenerationResult,
)
from app.core.config import settings
from app.core.actor import ActorContext
from app.core.distributed_rate_limit import RateLimiterUnavailable
from app.db.models import AIGeneration, ProviderProductDraft
from tests.media_fixtures import VALID_PNG_BYTES

# Alias kept for compatibility with tests ported from the development branch,
# which defined VALID_PNG inline. The shared fixture in tests.media_fixtures is
# the canonical source.
VALID_PNG = VALID_PNG_BYTES


DIVERSE_TAGS = [
    "botanical wall art",
    "colorful garden",
    "nature print",
    "modern floral decor",
    "living room accent",
    "gallery wall piece",
    "plant lover present",
    "housewarming idea",
    "office artwork",
    "abstract leaves",
    "organic shapes",
    "calm home style",
    "contemporary poster",
]


@pytest.fixture(autouse=True)
def _allow_ai_burst_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        ai_generation,
        "try_acquire_redis_sliding_window_slots",
        lambda **_kwargs: (True, 0.0),
    )


def _create_product(client) -> dict[str, object]:
    assert client.put(
        "/pod-providers/printify/credentials",
        json={"credentials": {"api_token": "token-123"}, "manual_store_seeds": []},
    ).status_code == 200
    connection = client.post("/provider-store-connections/sync/printify").json()["connections"][0]
    design_asset = client.post(
        "/design-assets",
        files={"file": ("design.png", VALID_PNG_BYTES, "image/png")},
    ).json()
    blueprint = client.post(
        "/blueprints",
        json={
            "name": "AI listing blueprint",
            "category": "Wall Art",
            "provider_store_connection_id": connection["id"],
            "reference_type": "printify_product_url",
            "reference_value": "https://printify.com/app/product-details/template-123",
        },
    ).json()
    assert client.post(f"/blueprints/{blueprint['id']}/validate-reference").status_code == 200
    response = client.post(
        "/products",
        json={
            "blueprint_id": blueprint["id"],
            "design_asset_id": design_asset["id"],
            "title": "Original title",
            "description": "Original description",
            "tags": ["original tag"],
            "design_description": "Abstract garden artwork",
        },
    )
    assert response.status_code == 201
    return response.json()


def _valid_listing_output(*, title: str) -> ListingOutput:
    return ListingOutput(
        title=title,
        description=(
            "A vibrant botanical art print brings a considered garden-inspired focal point to a living room, bedroom, office, or creative studio.\n\n"
            "The illustrated composition layers expressive color, organic shapes, and a calm contemporary mood for buyers who want nature-led decor without overwhelming a space.\n\n"
            "It works beautifully in a gallery wall, above a desk, or as a thoughtful gift for an art lover, housewarming, birthday, or creative friend.\n\n"
            "Review the product details and selected options before ordering so the final listing accurately reflects the available format, size, and fulfillment choices.\n\n"
            "This design is described from the supplied product context only, with no claims about materials, certifications, licensing, or dimensions beyond what the seller has verified."
        ),
        tags=DIVERSE_TAGS,
        seo_title="Botanical Wall Art Print for Modern Nature-Inspired Decor",
        seo_description="Shop a colorful botanical wall art print with expressive garden details, designed to bring a calm nature-inspired accent to modern rooms.",
        seo_keywords=[
            "botanical wall art",
            "colorful garden print",
            "nature inspired decor",
            "modern floral poster",
            "living room wall art",
        ],
    )


def test_apply_ai_generation_updates_selected_fields_and_audits_acceptance(client) -> None:
    product = _create_product(client)
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        generation = AIGeneration(
            organization_id="default-org",
            provider_product_draft_id=product["id"],
            provider_store_connection_id=product["provider_store_connection_id"],
            client_request_id="apply-generation-test-request",
            source_product_revision=product["revision"],
            provider_key="openrouter",
            model="test-model",
            prompt_version="etsy-listing-v1",
            input_hash="a" * 64,
            status="completed",
            output_json={"title": "Generated title", "description": "Generated description", "tags": ["generated tag"]},
            completed_at=datetime.now(timezone.utc),
        )
        db.add(generation)
        db.commit()
        generation_id = generation.id

    response = client.post(
        f"/products/{product['id']}/ai-generations/{generation_id}/apply",
        json={
            "expected_product_revision": product["revision"],
            "title": "Accepted title",
            "tags": ["accepted tag"],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["product"]["title"] == "Accepted title"
    assert payload["product"]["tags"] == ["accepted tag"]
    assert payload["product"]["revision"] == product["revision"] + 1
    assert payload["generation"]["status"] == "accepted"
    with session_factory() as db:
        accepted_generation = db.get(AIGeneration, generation_id)
        assert accepted_generation is not None
        assert accepted_generation.accepted_by_user_id == "default-user"


def test_apply_ai_generation_persists_normalized_selected_tags(client) -> None:
    product = _create_product(client)
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        generation = AIGeneration(
            organization_id="default-org",
            provider_product_draft_id=product["id"],
            provider_store_connection_id=product["provider_store_connection_id"],
            client_request_id="normalized-tag-apply-test",
            source_product_revision=product["revision"],
            provider_key="openrouter",
            model="test-model",
            prompt_version="etsy-listing-v2",
            input_hash="b" * 64,
            status="completed",
            output_json={"title": "Generated title", "description": "Generated description", "tags": ["generated tag"]},
            completed_at=datetime.now(timezone.utc),
        )
        db.add(generation)
        db.commit()
        generation_id = generation.id

    response = client.post(
        f"/products/{product['id']}/ai-generations/{generation_id}/apply",
        json={"expected_product_revision": product["revision"], "tags": [" modern   art "]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["product"]["tags"] == ["modern art"]


def test_generation_compresses_a_source_larger_than_the_ai_payload_limit(client, monkeypatch) -> None:
    product = _create_product(client)
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        draft = db.get(ProviderProductDraft, product["id"])
        assert draft is not None and draft.design_asset is not None
        draft.design_asset.size_bytes = settings.ai_max_image_bytes + 1
        db.commit()

    class FakeProvider:
        def __init__(self) -> None:
            self.image_data_url: str | None = None

        def generate(self, *, prompt: str, image_data_url: str | None = None) -> ProviderGenerationResult:
            self.image_data_url = image_data_url
            return ProviderGenerationResult(
                output=_valid_listing_output(
                    title="Colorful Botanical Matte Art Print with Teal Leaves and Coral Blooms for Contemporary Living Rooms, Creative Studios, or Home Offices"
                )
            )

    class FakeStorage:
        def __init__(self) -> None:
            self.max_bytes = 0

        def read_bytes_limited(self, _storage_key: str, *, max_bytes: int) -> bytes:
            self.max_bytes = max_bytes
            return VALID_PNG

    provider = FakeProvider()
    storage = FakeStorage()
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test-model")
    monkeypatch.setattr(ai_generation, "OpenRouterProvider", lambda: provider)
    monkeypatch.setattr(ai_generation, "get_storage_service", lambda: storage)

    response = client.post(
        f"/products/{product['id']}/ai-generations",
        json={
            "client_request_id": "large-source-compression-test",
            "expected_product_revision": product["revision"],
        },
    )

    assert response.status_code == 200, response.text
    assert storage.max_bytes == settings.ai_max_source_image_bytes
    assert provider.image_data_url is not None
    assert provider.image_data_url.startswith("data:image/jpeg;base64,")


def test_generation_repairs_short_output_once_without_resending_design_image(client, monkeypatch) -> None:
    product = _create_product(client)
    good_output = _valid_listing_output(
        title="Colorful Botanical Matte Art Print with Teal Leaves and Coral Blooms for Contemporary Living Rooms, Creative Studios, or Home Offices"
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []
            self.results = [
                ProviderGenerationResult(output=ListingOutput(title="Short", description="Too short", tags=[])),
                ProviderGenerationResult(output=good_output),
            ]

        def generate(self, *, prompt: str, image_data_url: str | None = None) -> ProviderGenerationResult:
            self.calls.append({"prompt": prompt, "image_data_url": image_data_url})
            return self.results.pop(0)

    class FakeStorage:
        def read_bytes_limited(self, _storage_key: str, *, max_bytes: int) -> bytes:
            assert max_bytes > 0
            return VALID_PNG

    provider = FakeProvider()
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test-model")
    monkeypatch.setattr(ai_generation, "OpenRouterProvider", lambda: provider)
    monkeypatch.setattr(ai_generation, "get_storage_service", lambda: FakeStorage())

    response = client.post(
        f"/products/{product['id']}/ai-generations",
        json={"client_request_id": "repair-output-test", "expected_product_revision": product["revision"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert len(provider.calls) == 2
    assert provider.calls[0]["image_data_url"] is not None
    assert provider.calls[1]["image_data_url"] is None
    assert "<previous_output>" in provider.calls[1]["prompt"]


def test_generation_retries_unreadable_structure_once_without_resending_design_image(client, monkeypatch) -> None:
    product = _create_product(client)
    good_output = _valid_listing_output(
        title="Colorful Botanical Matte Art Print with Teal Leaves and Coral Blooms for Contemporary Living Rooms, Creative Studios, or Home Offices"
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []
            self.results: list[Exception | ProviderGenerationResult] = [
                OpenRouterResponseError("invalid structured response"),
                ProviderGenerationResult(output=good_output),
            ]

        def generate(self, *, prompt: str, image_data_url: str | None = None) -> ProviderGenerationResult:
            self.calls.append({"prompt": prompt, "image_data_url": image_data_url})
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    class FakeStorage:
        def read_bytes_limited(self, _storage_key: str, *, max_bytes: int) -> bytes:
            assert max_bytes > 0
            return VALID_PNG

    provider = FakeProvider()
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test-model")
    monkeypatch.setattr(ai_generation, "OpenRouterProvider", lambda: provider)
    monkeypatch.setattr(ai_generation, "get_storage_service", lambda: FakeStorage())

    response = client.post(
        f"/products/{product['id']}/ai-generations",
        json={
            "client_request_id": "structured-retry-test",
            "expected_product_revision": product["revision"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert len(provider.calls) == 2
    assert provider.calls[0]["image_data_url"] is not None
    assert provider.calls[1]["image_data_url"] is None
    assert "previous attempt did not return a complete JSON object" in provider.calls[1]["prompt"]


def test_full_generation_repairs_only_invalid_title_field(client, monkeypatch) -> None:
    product = _create_product(client)
    invalid = _valid_listing_output(
        title="John Cena Championship Poster: Matte Paper Print, Signature Belt Artwork, Wrestling Fan Decor, Sports Wall Accent, Game Room Display"
    )
    repaired_title = (
        "John Cena Championship Poster, Matte Paper Wall Art, Signature Belt Pose, Wrestling Fan Decor, Sports Gift, Game Room Display, Gym Print"
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.targeted_results = [
                invalid.title,
                repaired_title,
            ]

        def generate(self, *, prompt: str, image_data_url: str | None = None) -> ProviderGenerationResult:
            self.calls.append({"prompt": prompt, "image_data_url": image_data_url, "fields": None})
            return ProviderGenerationResult(output=invalid.model_copy(deep=True))

        def generate_targeted(
            self,
            *,
            prompt: str,
            fields: list[str],
            image_data_url: str | None = None,
        ) -> ProviderTargetedGenerationResult:
            self.calls.append({"prompt": prompt, "image_data_url": image_data_url, "fields": fields})
            return ProviderTargetedGenerationResult(
                output={"title": self.targeted_results.pop(0)}
            )

    class FakeStorage:
        def read_bytes_limited(self, _storage_key: str, *, max_bytes: int) -> bytes:
            assert max_bytes > 0
            return VALID_PNG

    provider = FakeProvider()
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test-model")
    monkeypatch.setattr(ai_generation, "OpenRouterProvider", lambda: provider)
    monkeypatch.setattr(ai_generation, "get_storage_service", lambda: FakeStorage())

    response = client.post(
        f"/products/{product['id']}/ai-generations",
        json={
            "client_request_id": "focused-title-repair-test",
            "expected_product_revision": product["revision"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    assert response.json()["output"]["title"] == repaired_title
    assert len(provider.calls) == 3
    assert provider.calls[1]["fields"] == ["title"]
    assert provider.calls[2]["fields"] == ["title"]
    assert provider.calls[1]["image_data_url"] is None
    assert provider.calls[2]["image_data_url"] is None
    assert "clean product facts only" in provider.calls[1]["prompt"]
    assert "clean product facts only" in provider.calls[2]["prompt"]
    assert invalid.title not in provider.calls[1]["prompt"]
    assert invalid.title not in provider.calls[2]["prompt"]


def test_generation_context_removes_title_and_tag_anchors() -> None:
    context = {
        "design_description": "botanical print",
        "current_listing": {
            "title": "Existing keyword title",
            "description": "Keep useful description facts",
            "tags": ["existing tag"],
        },
        "previous_suggestion": {
            "title": "Previous keyword title",
            "tags": ["previous tag"],
            "seo_title": "Keep previous SEO title",
        },
    }

    clean = ai_generation._without_generation_anchors(
        context,
        {"title", "tags"},
    )

    assert clean["current_listing"] == {
        "title": "",
        "description": "Keep useful description facts",
        "tags": [],
    }
    assert clean["previous_suggestion"] == {
        "seo_title": "Keep previous SEO title"
    }
    assert context["current_listing"]["title"] == "Existing keyword title"


def test_targeted_regeneration_uses_previous_suggestion_and_repairs_repeated_output(client, monkeypatch) -> None:
    product = _create_product(client)
    original = _valid_listing_output(
        title="Colorful Botanical Matte Art Print with Teal Leaves and Coral Blooms for Contemporary Living Rooms, Creative Studios, or Home Offices"
    )
    alternative = _valid_listing_output(
        title="Abstract Garden Poster with Teal Leaves and Coral Blooms in Organic Modern Style for Living Rooms, Creative Studios, Offices and Bedrooms"
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, str | None]] = []
            self.full_results = [
                ProviderGenerationResult(output=original.model_copy(deep=True)),
            ]
            self.targeted_results = [
                ProviderTargetedGenerationResult(output={"title": original.title}),
                ProviderTargetedGenerationResult(output={"title": alternative.title}),
            ]

        def generate(self, *, prompt: str, image_data_url: str | None = None) -> ProviderGenerationResult:
            self.calls.append({"prompt": prompt, "image_data_url": image_data_url, "fields": None})
            return self.full_results.pop(0)

        def generate_targeted(
            self,
            *,
            prompt: str,
            fields: list[str],
            image_data_url: str | None = None,
        ) -> ProviderTargetedGenerationResult:
            self.calls.append({"prompt": prompt, "image_data_url": image_data_url, "fields": fields})
            return self.targeted_results.pop(0)

    class FakeStorage:
        def read_bytes_limited(self, _storage_key: str, *, max_bytes: int) -> bytes:
            assert max_bytes > 0
            return VALID_PNG

    provider = FakeProvider()
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test-model")
    monkeypatch.setattr(ai_generation, "OpenRouterProvider", lambda: provider)
    monkeypatch.setattr(ai_generation, "get_storage_service", lambda: FakeStorage())

    first = client.post(
        f"/products/{product['id']}/ai-generations",
        json={"client_request_id": "initial-variation-test", "expected_product_revision": product["revision"]},
    )
    regenerated = client.post(
        f"/products/{product['id']}/ai-generations",
        json={
            "client_request_id": "targeted-variation-test",
            "expected_product_revision": product["revision"],
            "regenerate_fields": ["title"],
        },
    )

    assert first.status_code == 200, first.text
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["status"] == "completed"
    assert regenerated.json()["output"]["title"] == alternative.title
    assert regenerated.json()["output"]["description"] == original.description
    assert len(provider.calls) == 3
    assert provider.calls[1]["fields"] == ["title"]
    assert "previous_suggestion" in provider.calls[1]["prompt"]
    assert "meaningfully different" in provider.calls[2]["prompt"]


def test_ai_generation_failure_messages_are_specific_and_safe() -> None:
    assert ai_generation._safe_generation_failure(ValueError("invalid image"))[0] == "design_image_invalid"
    assert ai_generation._safe_generation_failure(ValidationError.from_exception_data("ListingOutput", []))[0] == "provider_invalid_response"
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(429, request=request)
    assert ai_generation._safe_generation_failure(httpx.HTTPStatusError("rate limited", request=request, response=response))[0] == "provider_rate_limited"


def test_generation_enforces_database_requester_hourly_limit(
    client,
    monkeypatch,
) -> None:
    product = _create_product(client)
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        db.add(
            AIGeneration(
                organization_id="default-org",
                provider_product_draft_id=product["id"],
                provider_store_connection_id=product[
                    "provider_store_connection_id"
                ],
                client_request_id="earlier-user-limit-request",
                requested_by_user_id="default-user",
                source_product_revision=product["revision"],
                provider_key="openrouter",
                model="test-model",
                prompt_version="etsy-listing-v12",
                input_hash="d" * 64,
                status="failed",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "ai_generation_limit_per_hour", 100)
    monkeypatch.setattr(
        settings, "ai_generation_limit_per_user_per_hour", 1
    )

    response = client.post(
        f"/products/{product['id']}/ai-generations",
        json={
            "client_request_id": "blocked-user-limit-request",
            "expected_product_revision": product["revision"],
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"


def test_generation_enforces_shared_redis_burst_limit(client, monkeypatch) -> None:
    product = _create_product(client)
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "ai_generation_limit_per_hour", 100)
    monkeypatch.setattr(
        settings, "ai_generation_limit_per_user_per_hour", 100
    )
    monkeypatch.setattr(
        ai_generation,
        "try_acquire_redis_sliding_window_slots",
        lambda **_kwargs: (False, 12.2),
    )

    response = client.post(
        f"/products/{product['id']}/ai-generations",
        json={
            "client_request_id": "blocked-burst-limit-request",
            "expected_product_revision": product["revision"],
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "13"


def test_generation_falls_back_to_database_limit_when_redis_is_unavailable(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ai_generation_limit_per_hour", 100)
    monkeypatch.setattr(
        settings, "ai_generation_limit_per_user_per_hour", 100
    )

    def unavailable(**_kwargs):
        raise RateLimiterUnavailable("redis offline")

    monkeypatch.setattr(
        ai_generation,
        "try_acquire_redis_sliding_window_slots",
        unavailable,
    )
    actor = ActorContext(
        organization_id="default-org",
        actor_id="default-user",
    )
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        ai_generation._enforce_generation_limits(
            db,
            actor=actor,
            now=datetime.now(timezone.utc),
        )


def test_duplicate_pending_request_is_failed_after_timeout_without_new_charge(
    client,
    monkeypatch,
) -> None:
    product = _create_product(client)
    session_factory = client.app.state.testing_session_local
    with session_factory() as db:
        generation = AIGeneration(
            organization_id="default-org",
            provider_product_draft_id=product["id"],
            provider_store_connection_id=product[
                "provider_store_connection_id"
            ],
            client_request_id="abandoned-pending-request",
            requested_by_user_id="default-user",
            source_product_revision=product["revision"],
            provider_key="openrouter",
            model="test-model",
            prompt_version="etsy-listing-v12",
            input_hash="e" * 64,
            status="pending",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(generation)
        db.commit()
        generation_id = generation.id

    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(
        settings, "ai_generation_pending_timeout_seconds", 60
    )

    def should_not_charge(**_kwargs):
        raise AssertionError("A duplicate request must not consume a new burst slot.")

    monkeypatch.setattr(
        ai_generation,
        "try_acquire_redis_sliding_window_slots",
        should_not_charge,
    )
    response = client.post(
        f"/products/{product['id']}/ai-generations",
        json={
            "client_request_id": "abandoned-pending-request",
            "expected_product_revision": product["revision"],
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == generation_id
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "generation_abandoned"
