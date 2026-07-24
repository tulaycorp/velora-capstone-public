from __future__ import annotations

import json

import httpx
import pytest

from app.ai.compliance import ETSY_TITLE_PATTERN
from app.ai.openrouter import (
    OpenRouterProvider,
    OpenRouterResponseError,
    _completion_message,
    _json_object,
    _listing_schema,
    _provider_preferences,
    _reasoning_config,
    _structured_content,
    _supports_image_input,
    _targeted_schema,
)


def test_structured_content_accepts_openrouter_compatible_response_shapes() -> None:
    payload = '{"title":"Listing"}'

    assert _structured_content({"content": payload}) == payload
    assert _structured_content({"content": {"text": payload}}) == payload
    assert _structured_content({"content": [{"type": "text", "text": payload}]}) == payload
    assert _structured_content({"parsed": {"title": "Listing"}}) == '{"title":"Listing"}'


def test_structured_content_rejects_unknown_response_shape_without_echoing_content() -> None:
    with pytest.raises(OpenRouterResponseError, match="unsupported structured-response shape"):
        _structured_content({"content": [{"type": "refusal", "refusal": "private provider text"}]})


def test_json_object_accepts_json_wrapped_in_model_prose() -> None:
    assert _json_object('Result:\n```json\n{"title":"Listing"}\n```') == {
        "title": "Listing"
    }


def test_completion_message_rejects_truncated_or_empty_completions() -> None:
    with pytest.raises(OpenRouterResponseError, match="truncated"):
        _completion_message(
            {
                "choices": [
                    {"finish_reason": "length", "message": {"content": "{}"}}
                ]
            }
        )

    with pytest.raises(OpenRouterResponseError, match="no completion choice"):
        _completion_message({"choices": []})


def test_provider_preferences_scope_non_zdr_exception_to_qwen_model() -> None:
    assert _provider_preferences("qwen/qwen3-vl-8b-thinking") == {
        "require_parameters": True,
        "data_collection": "deny",
    }
    assert _provider_preferences("qwen/qwen3-vl-8b-instruct") == {
        "require_parameters": True,
        "data_collection": "deny",
    }
    assert _provider_preferences("google/gemini-3.1-flash-lite") == {
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
    }


def test_deepseek_v4_flash_keeps_zdr_and_uses_text_only_context() -> None:
    assert _provider_preferences("deepseek/deepseek-v4-flash") == {
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
    }
    assert _supports_image_input("deepseek/deepseek-v4-flash") is False
    assert _supports_image_input("qwen/qwen3-vl-8b-instruct") is True
    assert _reasoning_config("deepseek/deepseek-v4-flash") == {
        "effort": "none"
    }
    assert _reasoning_config("qwen/qwen3-vl-8b-instruct") is None


def test_ministral_3_8b_keeps_zdr_image_input_and_default_reasoning() -> None:
    assert _provider_preferences("mistralai/ministral-8b-2512") == {
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
    }
    assert _supports_image_input("mistralai/ministral-8b-2512") is True
    assert _reasoning_config("mistralai/ministral-8b-2512") is None


def test_listing_schema_enforces_machine_checkable_etsy_limits() -> None:
    properties = _listing_schema()["properties"]

    assert properties["title"]["minLength"] == 130
    assert properties["title"]["maxLength"] == 140
    assert properties["title"]["pattern"] == ETSY_TITLE_PATTERN
    assert properties["description"]["minLength"] == 600
    assert properties["tags"]["minItems"] == 13
    assert properties["tags"]["maxItems"] == 13
    assert properties["tags"]["items"]["maxLength"] == 20
    assert properties["seo_title"]["minLength"] == 40
    assert properties["seo_title"]["maxLength"] == 70
    assert properties["seo_description"]["minLength"] == 120
    assert properties["seo_description"]["maxLength"] == 160
    assert properties["seo_keywords"]["minItems"] == 5
    assert properties["seo_keywords"]["maxItems"] == 5


def test_targeted_schema_contains_only_requested_fields() -> None:
    schema = _targeted_schema(["seo_title", "seo_keywords"])

    assert set(schema["properties"]) == {"seo_title", "seo_keywords"}
    assert schema["required"] == ["seo_title", "seo_keywords"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["seo_title"]["minLength"] == 40
    assert schema["properties"]["seo_keywords"]["minItems"] == 5


def test_provider_enables_strict_schema_and_response_healing(monkeypatch) -> None:
    captured: dict[str, object] = {}
    listing = {
        "title": "Listing title",
        "description": "Listing description",
        "tags": [],
    }

    class FakeResponse:
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(listing)},
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: int) -> None:
            assert timeout > 0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            assert headers["Content-Type"] == "application/json"
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("app.ai.openrouter.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "app.ai.openrouter.settings.openrouter_model",
        "qwen/qwen3-vl-8b-thinking",
    )

    result = OpenRouterProvider().generate(prompt="Generate JSON")
    payload = captured["payload"]

    assert result.output.title == "Listing title"
    assert isinstance(payload, dict)
    assert payload["plugins"] == [{"id": "response-healing"}]
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["temperature"] == 0.2
    assert payload["provider"] == {
        "require_parameters": True,
        "data_collection": "deny",
    }


def test_provider_sends_attribution_and_retries_transient_connection_failure(
    monkeypatch,
) -> None:
    captured_headers: list[dict[str, str]] = []
    listing = {
        "title": "Listing title",
        "description": "Listing description",
        "tags": [],
    }

    class FakeResponse:
        headers = {"x-request-id": "request-1"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(listing)},
                    }
                ]
            }

    class FakeClient:
        calls = 0

        def __init__(self, *, timeout: int) -> None:
            assert timeout > 0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(
            self,
            _url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            del json
            self.calls += 1
            captured_headers.append(headers)
            if self.calls == 1:
                raise httpx.ConnectError("temporary connection failure")
            return FakeResponse()

    monkeypatch.setattr("app.ai.openrouter.httpx.Client", FakeClient)
    monkeypatch.setattr("app.ai.openrouter.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "app.ai.openrouter.settings.openrouter_app_url",
        "https://velora.example",
    )
    monkeypatch.setattr(
        "app.ai.openrouter.settings.openrouter_app_title",
        "Velora Staging",
    )
    monkeypatch.setattr(
        "app.ai.openrouter.settings.openrouter_max_retry_attempts",
        2,
    )

    result = OpenRouterProvider().generate(prompt="Generate JSON")

    assert result.retry_count == 1
    assert len(captured_headers) == 2
    assert captured_headers[-1]["HTTP-Referer"] == "https://velora.example"
    assert captured_headers[-1]["X-Title"] == "Velora Staging"


def test_targeted_provider_requests_and_parses_only_selected_field(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"seo_title": "Botanical Wall Art for Nature-Inspired Modern Rooms"})},
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: int) -> None:
            assert timeout > 0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("app.ai.openrouter.httpx.Client", FakeClient)

    result = OpenRouterProvider().generate_targeted(
        prompt="Regenerate the SEO title",
        fields=["seo_title"],
    )
    payload = captured["payload"]

    assert result.output == {
        "seo_title": "Botanical Wall Art for Nature-Inspired Modern Rooms"
    }
    assert isinstance(payload, dict)
    schema = payload["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]) == {"seo_title"}
    assert schema["required"] == ["seo_title"]


def test_text_only_model_omits_image_content(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"seo_title": "Botanical Wall Art for Nature-Inspired Modern Rooms"})},
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: int) -> None:
            assert timeout > 0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr("app.ai.openrouter.httpx.Client", FakeClient)
    monkeypatch.setattr(
        "app.ai.openrouter.settings.openrouter_model",
        "deepseek/deepseek-v4-flash",
    )

    OpenRouterProvider().generate_targeted(
        prompt="Regenerate the SEO title",
        fields=["seo_title"],
        image_data_url="data:image/png;base64,aW1hZ2U=",
    )
    payload = captured["payload"]

    assert isinstance(payload, dict)
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "Regenerate the SEO title"}
    ]
    assert payload["reasoning"] == {"effort": "none"}
