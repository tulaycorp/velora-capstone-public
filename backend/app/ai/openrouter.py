from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.ai.compliance import (
    ETSY_DESCRIPTION_MIN_LENGTH,
    ETSY_TAG_COUNT,
    ETSY_TAG_MAX_LENGTH,
    ETSY_TITLE_MIN_LENGTH,
    ETSY_TITLE_MAX_LENGTH,
    ETSY_TITLE_PATTERN,
    SEO_DESCRIPTION_MAX_LENGTH,
    SEO_DESCRIPTION_MIN_LENGTH,
    SEO_KEYWORD_COUNT,
    SEO_KEYWORD_MAX_LENGTH,
    SEO_TITLE_MAX_LENGTH,
    SEO_TITLE_MIN_LENGTH,
)
from app.ai.schemas import (
    ListingOutput,
    ProviderGenerationResult,
    ProviderTargetedGenerationResult,
)
from app.core.config import settings


class OpenRouterResponseError(ValueError):
    """OpenRouter returned a response that cannot be safely parsed as structured output."""


_NON_ZDR_MODELS = frozenset(
    {
        "qwen/qwen3-vl-8b-instruct",
        "qwen/qwen3-vl-8b-thinking",
    }
)

_TEXT_ONLY_MODELS = frozenset(
    {
        "deepseek/deepseek-v4-flash",
    }
)


def _provider_preferences(model: str | None) -> dict[str, object]:
    preferences: dict[str, object] = {
        "require_parameters": True,
        "data_collection": "deny",
    }
    if model not in _NON_ZDR_MODELS:
        preferences["zdr"] = True
    return preferences


def _supports_image_input(model: str | None) -> bool:
    return model not in _TEXT_ONLY_MODELS


def _reasoning_config(model: str | None) -> dict[str, str] | None:
    if model == "deepseek/deepseek-v4-flash":
        return {"effort": "none"}
    return None


def _listing_schema() -> dict[str, Any]:
    schema = ListingOutput.model_json_schema()
    properties = schema["properties"]
    properties["title"].update(
        minLength=ETSY_TITLE_MIN_LENGTH,
        maxLength=ETSY_TITLE_MAX_LENGTH,
        pattern=ETSY_TITLE_PATTERN,
    )
    properties["description"].update(minLength=ETSY_DESCRIPTION_MIN_LENGTH)
    properties["tags"].update(
        minItems=ETSY_TAG_COUNT,
        maxItems=ETSY_TAG_COUNT,
    )
    properties["tags"]["items"].update(minLength=1, maxLength=ETSY_TAG_MAX_LENGTH)
    properties["seo_title"].update(
        minLength=SEO_TITLE_MIN_LENGTH,
        maxLength=SEO_TITLE_MAX_LENGTH,
    )
    properties["seo_description"].update(
        minLength=SEO_DESCRIPTION_MIN_LENGTH,
        maxLength=SEO_DESCRIPTION_MAX_LENGTH,
    )
    properties["seo_keywords"].update(
        minItems=SEO_KEYWORD_COUNT,
        maxItems=SEO_KEYWORD_COUNT,
    )
    properties["seo_keywords"]["items"].update(
        minLength=1,
        maxLength=SEO_KEYWORD_MAX_LENGTH,
    )
    return schema


def _targeted_schema(fields: list[str]) -> dict[str, Any]:
    listing_schema = _listing_schema()
    properties = listing_schema["properties"]
    return {
        "type": "object",
        "properties": {field: properties[field] for field in fields},
        "required": fields,
        "additionalProperties": False,
    }


def _structured_content(message: dict[str, Any]) -> str:
    """Extract JSON text from OpenRouter's compatible structured-content variants."""
    parsed = message.get("parsed")
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, separators=(",", ":"))

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        if isinstance(content.get("json"), (dict, list)):
            return json.dumps(content["json"], separators=(",", ":"))
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
        if text_parts:
            return "".join(text_parts)
    raise OpenRouterResponseError("OpenRouter returned an unsupported structured-response shape.")


def _json_object(content: str) -> dict[str, Any]:
    """Decode a JSON object, including valid JSON wrapped in harmless model prose."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OpenRouterResponseError("OpenRouter returned content without a readable JSON object.")


def _listing_output(message: dict[str, Any]) -> ListingOutput:
    return ListingOutput.model_validate(_json_object(_structured_content(message)))


def _targeted_output(message: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    output = _json_object(_structured_content(message))
    if set(output) != set(fields):
        raise OpenRouterResponseError(
            "OpenRouter returned fields outside the targeted generation request."
        )
    for field in fields:
        value = output[field]
        if field in {"tags", "seo_keywords"}:
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise OpenRouterResponseError(
                    f"OpenRouter returned an invalid value for {field}."
                )
        elif not isinstance(value, str):
            raise OpenRouterResponseError(
                f"OpenRouter returned an invalid value for {field}."
            )
    return output


def _completion_message(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise OpenRouterResponseError("OpenRouter returned no completion choice.")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise OpenRouterResponseError("OpenRouter truncated the structured response.")
    if finish_reason in {"error", "content_filter"}:
        raise OpenRouterResponseError("OpenRouter did not complete the structured response.")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise OpenRouterResponseError("OpenRouter returned no structured response message.")
    return message


class OpenRouterProvider:
    def _complete(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        schema_name: str,
        image_data_url: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], str | None, int]:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        if image_data_url and _supports_image_input(settings.openrouter_model):
            content.append({"type": "image_url", "image_url": {"url": image_data_url}})
        payload = {
            "model": settings.openrouter_model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": settings.openrouter_max_output_tokens,
            "temperature": 0.2,
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            "plugins": [{"id": "response-healing"}],
            "provider": _provider_preferences(settings.openrouter_model),
        }
        reasoning = _reasoning_config(settings.openrouter_model)
        if reasoning is not None:
            payload["reasoning"] = reasoning
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if settings.openrouter_app_url:
            headers["HTTP-Referer"] = settings.openrouter_app_url
        if settings.openrouter_app_title:
            headers["X-Title"] = settings.openrouter_app_title

        retry_count = 0
        with httpx.Client(timeout=settings.openrouter_timeout_seconds) as client:
            while True:
                try:
                    response = client.post(
                        f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    break
                except (httpx.TimeoutException, httpx.RequestError):
                    if retry_count >= settings.openrouter_max_retry_attempts:
                        raise
                except httpx.HTTPStatusError as exc:
                    if (
                        exc.response.status_code != 429
                        or retry_count >= settings.openrouter_max_retry_attempts
                    ):
                        raise
                retry_count += 1
                time.sleep(min(0.25 * (2 ** (retry_count - 1)), 2.0))
        body = response.json()
        usage = {
            key: value
            for key, value in (body.get("usage") or {}).items()
            if key in {"prompt_tokens", "completion_tokens", "total_tokens", "cost"}
        }
        request_id = response.headers.get("x-request-id") or body.get("id")
        return _completion_message(body), usage, request_id, retry_count

    def generate(self, *, prompt: str, image_data_url: str | None = None) -> ProviderGenerationResult:
        message, usage, request_id, retry_count = self._complete(
            prompt=prompt,
            schema=_listing_schema(),
            schema_name="etsy_listing",
            image_data_url=image_data_url,
        )
        return ProviderGenerationResult(
            output=_listing_output(message),
            usage=usage,
            provider_request_id=request_id,
            retry_count=retry_count,
        )

    def generate_targeted(
        self,
        *,
        prompt: str,
        fields: list[str],
        image_data_url: str | None = None,
    ) -> ProviderTargetedGenerationResult:
        message, usage, request_id, retry_count = self._complete(
            prompt=prompt,
            schema=_targeted_schema(fields),
            schema_name="etsy_listing_fields",
            image_data_url=image_data_url,
        )
        return ProviderTargetedGenerationResult(
            output=_targeted_output(message, fields),
            usage=usage,
            provider_request_id=request_id,
            retry_count=retry_count,
        )
