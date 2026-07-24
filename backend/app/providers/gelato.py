from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import html
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger, log_event, summarize_mapping_for_log
from app.models.schemas import StorefrontType
from app.providers.base import (
    BaseProviderAdapter,
    ProviderOrderPage,
    ProviderProductCreateInput,
    ProviderProductCreateResult,
    ProviderProductStatus,
    ProviderPublishResult,
    ProviderStoreRecord,
    ReferenceSnapshotResult,
    ReferenceValidationResult,
)

provider_logger = get_logger("provider")


class GelatoAdapter(BaseProviderAdapter):
    provider = "gelato"
    API_KEY_NAME = "api_key"
    RETRYABLE_STATUS_CODES = {429, 504}
    VARIANT_FAILED_CONNECTION_STATES = {"failed", "error", "disconnected"}
    VARIANT_FAILED_STATUS_STATES = {"failed", "error", "publishing_error", "rejected"}
    VARIANT_FAILURE_DETAIL_KEYS = ("publishingErrorCode", "publishingError", "failureReason", "errorMessage", "error")
    VARIANT_TEMPLATE_ID_KEYS = ("templateVariantId", "variantTemplateId", "sourceTemplateVariantId", "productTemplateVariantId")

    def __init__(self, credentials: dict[str, Any]):
        super().__init__(credentials)
        self.api_key = str(self.credentials.get(self.API_KEY_NAME) or "").strip()
        self.store_id = str(self.credentials.get("store_id") or "").strip()
        self.base_url = settings.gelato_ecommerce_base_url
        self.order_base_url = settings.gelato_order_base_url

    def _validate_api_key(self) -> None:
        if not self.api_key:
            raise ValueError("Missing Gelato credential 'api_key'.")

    def _validate_store(self) -> None:
        self._validate_api_key()
        if not self.store_id:
            raise ValueError("Missing Gelato store binding 'store_id'.")

    def _get_client(self) -> httpx.AsyncClient:
        self._validate_api_key()
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-KEY": self.api_key},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=50),
        )

    def _get_orders_client(self) -> httpx.AsyncClient:
        self._validate_api_key()
        return httpx.AsyncClient(
            base_url=self.order_base_url,
            headers={"X-API-KEY": self.api_key},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=50),
        )

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {"raw": data}
        except Exception:
            return {"raw": resp.text}

    @classmethod
    def _get_retry_delay_seconds(cls, attempt: int, retry_after_header: str | None) -> int:
        if retry_after_header:
            try:
                parsed = int(retry_after_header.strip())
                if parsed > 0:
                    return parsed
            except ValueError:
                pass
        return min(2 ** (attempt + 1), 30)

    async def _post_with_backoff(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str,
        payload: dict[str, Any],
        timeout: float,
        action: str,
    ) -> httpx.Response:
        for attempt in range(settings.gelato_max_retry_attempts + 1):
            started_at = time.perf_counter()
            try:
                response = await client.post(endpoint, json=payload, timeout=timeout)
            except httpx.RequestError as exc:
                log_event(
                    provider_logger,
                    "provider.http.request_error",
                    level=logging.WARNING,
                    verbose_only=True,
                    provider=self.provider,
                    method="POST",
                    path=endpoint,
                    attempt=attempt + 1,
                    max_retries=settings.gelato_max_retry_attempts + 1,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    payload_summary=summarize_mapping_for_log(payload),
                    error=str(exc),
                )
                if attempt == settings.gelato_max_retry_attempts:
                    raise RuntimeError(f"Failed Gelato {action} after retries: {exc}") from exc
                await asyncio.sleep(min(2 ** (attempt + 1), 30))
                continue
            response_payload = self._safe_json(response)
            will_retry = (
                response.status_code in self.RETRYABLE_STATUS_CODES
                and attempt < settings.gelato_max_retry_attempts
            )
            log_event(
                provider_logger,
                "provider.http.response",
                verbose_only=True,
                provider=self.provider,
                method="POST",
                path=endpoint,
                attempt=attempt + 1,
                max_retries=settings.gelato_max_retry_attempts + 1,
                status_code=response.status_code,
                will_retry=will_retry,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                payload_summary=summarize_mapping_for_log(payload),
                response_summary=summarize_mapping_for_log(response_payload),
            )
            if response.status_code not in self.RETRYABLE_STATUS_CODES:
                return response
            if attempt == settings.gelato_max_retry_attempts:
                return response
            await asyncio.sleep(self._get_retry_delay_seconds(attempt, response.headers.get("Retry-After")))
        raise RuntimeError("Unexpected Gelato retry loop termination.")

    async def _get_with_backoff(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str,
        timeout: float,
        action: str,
    ) -> httpx.Response:
        for attempt in range(settings.gelato_max_retry_attempts + 1):
            started_at = time.perf_counter()
            try:
                response = await client.get(endpoint, timeout=timeout)
            except httpx.RequestError as exc:
                log_event(
                    provider_logger,
                    "provider.http.request_error",
                    level=logging.WARNING,
                    verbose_only=True,
                    provider=self.provider,
                    method="GET",
                    path=endpoint,
                    attempt=attempt + 1,
                    max_retries=settings.gelato_max_retry_attempts + 1,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    error=str(exc),
                )
                if attempt == settings.gelato_max_retry_attempts:
                    raise RuntimeError(f"Failed Gelato {action} after retries: {exc}") from exc
                await asyncio.sleep(min(2 ** (attempt + 1), 30))
                continue
            response_payload = self._safe_json(response)
            will_retry = (
                response.status_code in self.RETRYABLE_STATUS_CODES
                and attempt < settings.gelato_max_retry_attempts
            )
            log_event(
                provider_logger,
                "provider.http.response",
                verbose_only=True,
                provider=self.provider,
                method="GET",
                path=endpoint,
                attempt=attempt + 1,
                max_retries=settings.gelato_max_retry_attempts + 1,
                status_code=response.status_code,
                will_retry=will_retry,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                response_summary=summarize_mapping_for_log(response_payload),
            )
            if response.status_code not in self.RETRYABLE_STATUS_CODES:
                return response
            if attempt == settings.gelato_max_retry_attempts:
                return response
            await asyncio.sleep(self._get_retry_delay_seconds(attempt, response.headers.get("Retry-After")))
        raise RuntimeError("Unexpected Gelato retry loop termination.")

    @staticmethod
    def _extract_product_id(product_response: dict[str, Any]) -> str | None:
        for candidate in (
            product_response.get("id"),
            product_response.get("productId"),
            (product_response.get("product") or {}).get("id") if isinstance(product_response.get("product"), dict) else None,
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    @staticmethod
    def _variant_identifier(variant: dict[str, Any], index: int) -> str:
        for key in ("id", "templateVariantId", "variantId", "sku"):
            value = variant.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return f"index:{index}"

    def _extract_template_variant_id(self, variant: dict[str, Any]) -> str | None:
        for key in self.VARIANT_TEMPLATE_ID_KEYS:
            value = variant.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _evaluate_expected_variant_progress(
        self,
        *,
        variants: list[Any],
        expected_template_variant_ids: set[str],
        expected_variant_count: int,
    ) -> tuple[int, str | None]:
        has_template_variant_ids = any(
            self._extract_template_variant_id(variant)
            for variant in variants
            if isinstance(variant, dict)
        )
        use_template_matching = bool(expected_template_variant_ids and has_template_variant_ids)
        connected_expected_ids: set[str] = set()
        connected_expected_count = 0
        for index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                continue
            connection_status = str(variant.get("connectionStatus") or "").strip().lower()
            status = str(variant.get("status") or "").strip().lower()
            variant_id = self._variant_identifier(variant, index)
            template_variant_id = self._extract_template_variant_id(variant)
            is_expected_variant = bool(template_variant_id and template_variant_id in expected_template_variant_ids) if use_template_matching else True
            for detail_key in self.VARIANT_FAILURE_DETAIL_KEYS:
                detail_value = variant.get(detail_key)
                if detail_value in (None, "", 0, "0"):
                    continue
                if is_expected_variant:
                    connected_count = len(connected_expected_ids) if use_template_matching else min(connected_expected_count, expected_variant_count)
                    return connected_count, f"Variant '{variant_id}' failed ({detail_key}={detail_value})."
            if not is_expected_variant:
                continue
            if connection_status in self.VARIANT_FAILED_CONNECTION_STATES:
                connected_count = len(connected_expected_ids) if use_template_matching else min(connected_expected_count, expected_variant_count)
                return connected_count, f"Variant '{variant_id}' failed (connectionStatus={connection_status})."
            if status in self.VARIANT_FAILED_STATUS_STATES:
                connected_count = len(connected_expected_ids) if use_template_matching else min(connected_expected_count, expected_variant_count)
                return connected_count, f"Variant '{variant_id}' failed (status={status})."
            if connection_status == "connected":
                if use_template_matching and template_variant_id:
                    connected_expected_ids.add(template_variant_id)
                if not use_template_matching:
                    connected_expected_count += 1
        if use_template_matching:
            return len(connected_expected_ids), None
        return min(connected_expected_count, expected_variant_count), None

    async def _get_product_with_backoff(self, client: httpx.AsyncClient, *, product_id: str) -> dict[str, Any]:
        response = await self._get_with_backoff(
            client,
            endpoint=f"/v1/stores/{self.store_id}/products/{product_id}",
            timeout=30.0,
            action=f"product status {product_id}",
        )
        payload = self._safe_json(response)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch Gelato product '{product_id}': status={response.status_code} body={payload}")
        return payload

    async def _poll_product_until_expected_connected(
        self,
        client: httpx.AsyncClient,
        *,
        product_id: str,
        expected_template_variant_ids: set[str],
        expected_variant_count: int,
    ) -> tuple[bool, str | None]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.gelato_poll_timeout_seconds
        delay_seconds = max(1, settings.gelato_poll_initial_delay_seconds)
        last_connected_count = 0
        last_total_count = 0
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False, (
                    f"Timed out waiting for connected variants on product '{product_id}' after "
                    f"{settings.gelato_poll_timeout_seconds}s "
                    f"(connected={last_connected_count}, expected={expected_variant_count}, total={last_total_count})."
                )
            await asyncio.sleep(min(delay_seconds, max(1, int(remaining))))
            product_data = await self._get_product_with_backoff(client, product_id=product_id)
            product_status = str(product_data.get("status") or "").strip().lower()
            if product_status == "publishing_error":
                return False, f"Product '{product_id}' entered publishing_error."
            variants = product_data.get("variants") if isinstance(product_data.get("variants"), list) else []
            connected_count, terminal_failure_error = self._evaluate_expected_variant_progress(
                variants=variants,
                expected_template_variant_ids=expected_template_variant_ids,
                expected_variant_count=expected_variant_count,
            )
            last_connected_count = connected_count
            last_total_count = len(variants)
            if terminal_failure_error:
                return False, terminal_failure_error
            if connected_count >= expected_variant_count:
                return True, None
            delay_seconds = min(delay_seconds * 2, settings.gelato_poll_max_delay_seconds)

    @staticmethod
    def _format_description_for_gelato(raw_description: str) -> str:
        normalized = raw_description.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return ""
        if re.search(r"<[a-zA-Z][^>]*>", normalized):
            return normalized
        paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n+", normalized) if segment.strip()]
        if not paragraphs:
            return html.escape(normalized)
        rendered: list[str] = []
        for paragraph in paragraphs:
            lines = [html.escape(line.strip()) for line in paragraph.split("\n") if line.strip()]
            if not lines:
                continue
            joined_lines = "<br>\n".join(lines)
            rendered.append(f"<p>{joined_lines}</p>")
        return "\n \n".join(rendered) or html.escape(normalized)

    @staticmethod
    def _normalize_tags(raw_tags: Any) -> list[str]:
        max_tags = 13
        max_tag_length = 20
        if raw_tags is None:
            return []
        raw_items = raw_tags if isinstance(raw_tags, list) else [raw_tags]
        normalized_tags: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, str):
                continue
            parts = re.split(r"[,;\n]+", raw_item)
            for part in parts:
                normalized = " ".join(part.strip().lstrip("#").split())
                normalized = re.sub(r"[^A-Za-z0-9\s-]", "", normalized)
                normalized = " ".join(normalized.split())
                if not normalized:
                    continue
                if len(normalized) > max_tag_length:
                    normalized = normalized[:max_tag_length].rstrip()
                if not normalized:
                    continue
                normalized_key = normalized.casefold()
                if normalized_key in seen:
                    continue
                seen.add(normalized_key)
                normalized_tags.append(normalized)
                if len(normalized_tags) >= max_tags:
                    return normalized_tags
        return normalized_tags

    @staticmethod
    def _storefront_type(channel_raw: Any) -> StorefrontType:
        channel = str(channel_raw or "").strip().lower()
        if "etsy" in channel:
            return "etsy"
        if "shopify" in channel:
            return "shopify"
        return "unknown"

    @staticmethod
    def _storefront_display_name(storefront_type: StorefrontType) -> str:
        if storefront_type == "etsy":
            return "Etsy"
        if storefront_type == "shopify":
            return "Shopify"
        return "Unknown"

    @staticmethod
    def _build_order_fallback_label(storefront_type: StorefrontType, provider_store_id: str) -> str:
        return f"{GelatoAdapter._storefront_display_name(storefront_type)} [{provider_store_id}]"

    @staticmethod
    def _parse_order_timestamp(order: dict[str, Any]) -> float:
        for key in ("createdAt", "updatedAt", "orderedAt"):
            raw_value = order.get(key)
            if not isinstance(raw_value, str):
                continue
            normalized = raw_value.strip()
            if not normalized:
                continue
            try:
                return datetime.fromisoformat(normalized.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
        return 0.0

    def _manual_store_records(self) -> list[ProviderStoreRecord]:
        raw_seeds = self.credentials.get("manual_store_seeds") or []
        stores: list[ProviderStoreRecord] = []
        for seed in raw_seeds:
            if not isinstance(seed, dict):
                continue
            provider_store_id = str(seed.get("provider_store_id") or "").strip()
            storefront_display_name = str(seed.get("storefront_display_name") or "").strip()
            if not provider_store_id or not storefront_display_name:
                continue
            label = str(seed.get("label") or "").strip() or storefront_display_name
            storefront_type = self._storefront_type(seed.get("storefront_type"))
            stores.append(
                ProviderStoreRecord(
                    provider_store_id=provider_store_id,
                    storefront_type=storefront_type,
                    storefront_display_name=storefront_display_name,
                    label=label,
                    etsy_shop_id=str(seed.get("etsy_shop_id") or "").strip() or None,
                    discovery_source="manual",
                )
            )
        return stores

    def _merge_store_records(
        self,
        *,
        manual_records: list[ProviderStoreRecord],
        order_records: list[ProviderStoreRecord],
    ) -> list[ProviderStoreRecord]:
        merged_by_store_id = {record.provider_store_id: record for record in order_records}
        for manual_record in manual_records:
            order_record = merged_by_store_id.get(manual_record.provider_store_id)
            if order_record is None:
                merged_by_store_id[manual_record.provider_store_id] = manual_record
                continue
            merged_by_store_id[manual_record.provider_store_id] = ProviderStoreRecord(
                provider_store_id=manual_record.provider_store_id,
                storefront_type=manual_record.storefront_type,
                storefront_display_name=manual_record.storefront_display_name,
                label=manual_record.label,
                etsy_shop_id=manual_record.etsy_shop_id,
                discovery_source="merged",
            )
        return list(merged_by_store_id.values())

    async def _discover_order_store_records(self) -> list[ProviderStoreRecord]:
        try:
            async with self._get_orders_client() as client:
                response = await self._post_with_backoff(
                    client,
                    endpoint="/v4/orders:search",
                    payload={},
                    timeout=30.0,
                    action="order search",
                )
        except RuntimeError as exc:
            raise RuntimeError(f"Gelato orders search failed after retries: {exc}") from exc

        payload = self._safe_json(response)
        if response.status_code == 200:
            orders = payload.get("orders") if isinstance(payload.get("orders"), list) else []
            best_orders_by_store_id: dict[str, dict[str, Any]] = {}
            for order in orders:
                if not isinstance(order, dict):
                    continue
                provider_store_id = str(order.get("storeId") or "").strip()
                if not provider_store_id:
                    continue
                storefront_type = self._storefront_type(order.get("channel"))
                candidate = {
                    "order": order,
                    "timestamp": self._parse_order_timestamp(order),
                    "storefront_type": storefront_type,
                    "recognized": storefront_type != "unknown",
                }
                current = best_orders_by_store_id.get(provider_store_id)
                if current is None:
                    best_orders_by_store_id[provider_store_id] = candidate
                    continue
                if (
                    (candidate["recognized"], candidate["timestamp"])
                    > (current["recognized"], current["timestamp"])
                ):
                    best_orders_by_store_id[provider_store_id] = candidate

            discovered_stores: list[ProviderStoreRecord] = []
            for provider_store_id, candidate in best_orders_by_store_id.items():
                storefront_type = candidate["storefront_type"]
                storefront_display_name = self._storefront_display_name(storefront_type)
                order = candidate["order"]
                discovered_stores.append(
                    ProviderStoreRecord(
                        provider_store_id=provider_store_id,
                        storefront_type=storefront_type,
                        storefront_display_name=storefront_display_name,
                        label=self._build_order_fallback_label(storefront_type, provider_store_id),
                        discovery_source="orders",
                    )
                )
            return discovered_stores

        if response.status_code in self.RETRYABLE_STATUS_CODES:
            raise RuntimeError(f"Gelato orders search failed after retries: status={response.status_code}.")
        raise RuntimeError(f"Gelato orders search failed: status={response.status_code}.")

    @staticmethod
    def _placeholder_names_from_template(template: dict[str, Any]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for variant in template.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            for placeholder in variant.get("imagePlaceholders") or []:
                if not isinstance(placeholder, dict):
                    continue
                name = str(placeholder.get("name") or "").strip()
                if not name:
                    continue
                lowered = name.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                names.append(name)
        return names

    def _resolve_design_placeholder_names(
        self,
        placement_config_json: dict[str, Any] | None,
        template: dict[str, Any],
    ) -> list[str]:
        if placement_config_json:
            raw_names = placement_config_json.get("design_placeholder_names")
            if isinstance(raw_names, list):
                names = [str(item).strip() for item in raw_names if str(item).strip()]
                if names:
                    return names
            raw_name = placement_config_json.get("design_placeholder_name")
            if isinstance(raw_name, str) and raw_name.strip():
                return [raw_name.strip()]
        credential_name = str(self.credentials.get("design_placeholder_name") or "").strip()
        if credential_name:
            return [credential_name]
        available_names = self._placeholder_names_from_template(template)
        preferred = [name for name in available_names if name.lower() == "imagefront"]
        if preferred:
            return preferred
        return available_names[:1] or ["ImageFront"]

    def _template_summary(self, template: dict[str, Any]) -> str:
        variants = template.get("variants") if isinstance(template.get("variants"), list) else []
        placeholders = self._placeholder_names_from_template(template)
        parts = [f"{len(variants)} variants"]
        if placeholders:
            parts.append(f"placeholders: {', '.join(placeholders[:4])}")
        product_type = str(template.get("productType") or "").strip()
        if product_type:
            parts.append(product_type)
        return ", ".join(parts)

    async def discover_store_connections(self) -> list[ProviderStoreRecord]:
        self._validate_api_key()
        manual_records = self._manual_store_records()
        try:
            order_records = await self._discover_order_store_records()
        except RuntimeError as exc:
            if manual_records and "after retries" in str(exc):
                log_event(
                    provider_logger,
                    "provider.store_discovery.manual_fallback",
                    level=logging.WARNING,
                    verbose_only=True,
                    provider=self.provider,
                    manual_store_count=len(manual_records),
                    error=str(exc),
                )
                return manual_records
            raise
        return self._merge_store_records(
            manual_records=manual_records,
            order_records=order_records,
        )

    async def validate_reference(
        self,
        *,
        reference_type: str,
        reference_value: str,
    ) -> ReferenceValidationResult:
        if reference_type not in {"gelato_template_id", "gelato_template"}:
            raise ValueError(f"Unsupported Gelato reference type '{reference_type}'.")
        normalized_id = reference_value.strip()
        if not normalized_id:
            raise ValueError("Gelato template id is required.")
        snapshot = await self.fetch_reference_snapshot(
            reference_type=reference_type,
            reference_value=reference_value,
            provider_resource_id=normalized_id,
        )
        return ReferenceValidationResult(
            reference_type="gelato_template_id",
            normalized_reference_value=normalized_id,
            provider_resource_id=normalized_id,
            provider_display_name=snapshot.provider_display_name,
        )

    async def fetch_reference_snapshot(
        self,
        *,
        reference_type: str,
        reference_value: str,
        provider_resource_id: str,
    ) -> ReferenceSnapshotResult:
        self._validate_api_key()
        async with self._get_client() as client:
            response = await self._get_with_backoff(
                client,
                endpoint=f"/v1/templates/{provider_resource_id}",
                timeout=30.0,
                action=f"template {provider_resource_id}",
            )
        payload = self._safe_json(response)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch Gelato template '{provider_resource_id}': {response.status_code} {payload}")
        provider_display_name = str(payload.get("templateName") or payload.get("title") or provider_resource_id).strip()
        placeholders = self._placeholder_names_from_template(payload)
        placement_name = next((name for name in placeholders if name.lower() == "imagefront"), None) or (placeholders[0] if placeholders else "ImageFront")
        return ReferenceSnapshotResult(
            provider_resource_id=provider_resource_id,
            provider_display_name=provider_display_name,
            provider_snapshot_json=payload,
            product_type=str(payload.get("productType") or "").strip() or "Gelato Template",
            configuration_summary=self._template_summary(payload),
            variant_count=len(payload.get("variants") or []),
            placement_config_json={"design_placeholder_name": placement_name, "design_placeholder_names": [placement_name]},
            base_title=provider_display_name,
            base_description=str(payload.get("description") or "").strip() or None,
        )

    async def create_provider_product(
        self,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult:
        self._validate_store()
        template_data = payload.provider_snapshot_json
        async with self._get_client() as client:
            if not template_data:
                template_snapshot = await self.fetch_reference_snapshot(
                    reference_type=payload.reference_type,
                    reference_value=payload.reference_value,
                    provider_resource_id=payload.provider_resource_id,
                )
                template_data = template_snapshot.provider_snapshot_json
            template_id = payload.provider_resource_id
            final_description = (payload.description or "").strip() or str(template_data.get("description") or "").strip() or payload.title
            final_description = self._format_description_for_gelato(final_description)
            normalized_tags = self._normalize_tags(payload.tags)
            design_placeholder_names = self._resolve_design_placeholder_names(payload.placement_config_json, template_data)
            design_placeholder_names_lc = {name.lower() for name in design_placeholder_names}
            variant_payloads: list[dict[str, Any]] = []
            for variant in template_data.get("variants") or []:
                if not isinstance(variant, dict):
                    continue
                variant_id = variant.get("id")
                if not variant_id:
                    continue
                placeholders = variant.get("imagePlaceholders") or []
                placeholder_names = [ph.get("name") for ph in placeholders if isinstance(ph, dict) and ph.get("name")]
                selected_placeholder_names = [
                    name for name in placeholder_names
                    if isinstance(name, str) and name.strip().lower() in design_placeholder_names_lc
                ]
                if not selected_placeholder_names:
                    continue
                variant_payloads.append(
                    {
                        "templateVariantId": variant_id,
                        "imagePlaceholders": [
                            {
                                "name": placeholder_name,
                                "fileUrl": payload.design_asset_url,
                                "fitMethod": settings.gelato_design_fit_method,
                            }
                            for placeholder_name in selected_placeholder_names
                        ],
                    }
                )
            if not variant_payloads:
                raise RuntimeError("Template variants do not contain the configured design placeholder names.")
            create_payload: dict[str, Any] = {
                "title": payload.title,
                "description": final_description,
                "templateId": template_id,
                "isVisibleInTheOnlineStore": False,
                "productType": template_data.get("productType", "Printable Material"),
                "vendor": template_data.get("vendor", "Gelato"),
                "variants": variant_payloads,
                "storeMockups": [{"url": url} for url in payload.mockup_urls] if payload.mockup_urls else [],
            }
            if normalized_tags:
                create_payload["tags"] = normalized_tags
            response = await self._post_with_backoff(
                client,
                endpoint=f"/v1/stores/{self.store_id}/products:create-from-template",
                payload=create_payload,
                timeout=60.0,
                action=f"product create template={template_id}",
            )
            create_data = self._safe_json(response)
            if response.status_code not in (200, 201):
                raise RuntimeError(str(create_data.get("message") or create_data))
            product_id = self._extract_product_id(create_data)
            if not product_id:
                raise RuntimeError(f"Gelato returned {response.status_code} but no product id: {create_data}")
            expected_template_variant_ids = {str(item["templateVariantId"]).strip() for item in variant_payloads if str(item.get("templateVariantId") or "").strip()}
            poll_success, poll_error = await self._poll_product_until_expected_connected(
                client,
                product_id=product_id,
                expected_template_variant_ids=expected_template_variant_ids,
                expected_variant_count=len(variant_payloads),
            )
            if not poll_success:
                raise RuntimeError(poll_error or f"Gelato product-level polling failed for product {product_id}.")
            product_status = await self._get_product_with_backoff(client, product_id=product_id)
        return ProviderProductCreateResult(
            provider_product_id=product_id,
            external_listing_id=create_data.get("externalId"),
            provider_status=str(product_status.get("status") or "created"),
            raw_provider_payload_json=product_status,
        )

    async def reconcile_provider_product(
        self,
        *,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult | None:
        self._validate_store()
        async with self._get_client() as client:
            response = await self._get_with_backoff(
                client,
                endpoint=f"/v1/stores/{self.store_id}/products?order=desc&orderBy=createdAt&offset=0&limit=100",
                timeout=30.0,
                action="product reconciliation",
            )
        data = self._safe_json(response)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to reconcile Gelato products: {response.status_code}")
        submitted_after = payload.submitted_at.astimezone(timezone.utc) - timedelta(minutes=15)
        matches: list[dict[str, Any]] = []
        for item in data.get("products") or []:
            if not isinstance(item, dict) or str(item.get("title") or "").strip() != payload.title:
                continue
            created_raw = str(item.get("createdAt") or "").strip()
            if created_raw:
                try:
                    created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                    if created_at.astimezone(timezone.utc) < submitted_after:
                        continue
                except ValueError:
                    continue
            matches.append(item)
        if len(matches) != 1:
            return None
        product = matches[0]
        provider_product_id = str(product.get("id") or "").strip()
        if not provider_product_id:
            return None
        return ProviderProductCreateResult(
            provider_product_id=provider_product_id,
            external_listing_id=product.get("externalId"),
            provider_status=str(product.get("status") or "created"),
            raw_provider_payload_json=product,
        )

    async def publish_provider_product(
        self,
        *,
        provider_product_id: str,
    ) -> ProviderPublishResult:
        status = await self.fetch_provider_product_status(provider_product_id=provider_product_id)
        return ProviderPublishResult(
            provider_product_id=status.provider_product_id,
            external_listing_id=status.external_listing_id,
            provider_product_url=status.provider_product_url,
            provider_fulfillment_url=status.provider_fulfillment_url,
            provider_status=status.provider_status,
            raw_provider_payload_json=status.raw_provider_payload_json,
        )

    async def fetch_provider_product_status(
        self,
        *,
        provider_product_id: str,
    ) -> ProviderProductStatus:
        self._validate_store()
        async with self._get_client() as client:
            product = await self._get_product_with_backoff(client, product_id=provider_product_id)
        return ProviderProductStatus(
            provider_product_id=provider_product_id,
            external_listing_id=product.get("externalId"),
            provider_status=str(product.get("status") or "created"),
            raw_provider_payload_json=product,
        )

    async def fetch_orders(
        self,
        *,
        provider_store_id: str,
        since: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ProviderOrderPage:
        self._validate_api_key()
        try:
            offset = max(int(cursor or "0"), 0)
        except ValueError as exc:
            raise ValueError("Gelato order cursor must be an offset.") from exc

        search_payload: dict[str, Any] = {
            "orderTypes": ["order"],
            "storeIds": [provider_store_id],
            "limit": limit,
            "offset": offset,
        }
        if since is not None:
            search_payload["startDate"] = since.isoformat()
        try:
            async with self._get_orders_client() as client:
                response = await self._post_with_backoff(
                    client,
                    endpoint="/v4/orders:search",
                    payload=search_payload,
                    timeout=30.0,
                    action="order search",
                )
        except RuntimeError as exc:
            raise RuntimeError(f"Gelato orders search failed: {exc}") from exc

        payload = self._safe_json(response)
        if response.status_code != 200:
            raise RuntimeError(f"Gelato order page request failed with status {response.status_code}.")

        orders = payload.get("orders") if isinstance(payload.get("orders"), list) else []
        store_orders = [
            order
            for order in orders
            if isinstance(order, dict) and str(order.get("storeId") or "") == provider_store_id
        ]
        observed_timestamps = [
            timestamp
            for timestamp in (self._parse_order_sync_timestamp(order) for order in store_orders)
            if timestamp is not None
        ]
        semaphore = asyncio.Semaphore(settings.order_sync_detail_concurrency)

        async with self._get_orders_client() as client:
            async def fetch_detail(raw_order: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
                order_id = raw_order.get("id")
                if not order_id:
                    return None, "missing_order_id"
                try:
                    async with semaphore:
                        detail_response = await self._get_with_backoff(
                            client,
                            endpoint=f"/v4/orders/{order_id}",
                            timeout=30.0,
                            action="order detail",
                        )
                except Exception:
                    return None, "detail_request_failed"
                if detail_response.status_code != 200:
                    return None, "detail_request_failed"
                detail = self._safe_json(detail_response)
                order_ref_id = detail.get("orderReferenceId")
                if order_ref_id:
                    try:
                        async with semaphore:
                            status_response = await self._get_with_backoff(
                                client,
                                endpoint=f"/v2/order/status/{order_ref_id}",
                                timeout=30.0,
                                action="order status",
                            )
                    except Exception:
                        return None, "status_request_failed"
                    if status_response.status_code != 200:
                        return None, "status_request_failed"
                    detail["_production_status"] = self._safe_json(status_response)
                return detail, None

            detail_results = await asyncio.gather(*(fetch_detail(order) for order in store_orders))

        detailed_orders: list[dict[str, Any]] = []
        skipped_count = 0
        failed_count = 0
        for detail, failure_code in detail_results:
            if detail is not None:
                detailed_orders.append(detail)
            elif failure_code == "missing_order_id":
                skipped_count += 1
            else:
                failed_count += 1

        has_more = len(orders) >= limit
        return ProviderOrderPage(
            orders=detailed_orders,
            fetched_count=len(store_orders),
            skipped_count=skipped_count,
            failed_count=failed_count,
            next_cursor=str(offset + len(orders)) if has_more else None,
            observed_watermark_at=max(observed_timestamps, default=None),
        )

    @staticmethod
    def _parse_order_sync_timestamp(raw_order: dict[str, Any]) -> datetime | None:
        for key in ("updatedAt", "createdAt", "orderedAt"):
            raw_value = raw_order.get(key)
            if not raw_value:
                continue
            try:
                return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
            except ValueError:
                continue
        return None

    def normalize_order(
        self,
        *,
        raw_order: dict[str, Any],
        organization_id: str,
        provider_store_connection_id: str,
    ) -> dict[str, Any]:
        from datetime import datetime
        external_order_id = str(raw_order.get("id") or "")
        display_order_id = str(raw_order.get("orderReferenceId") or external_order_id)
        
        customer_name = ""
        address = raw_order.get("shippingAddress") or {}
        if address:
            customer_name = f"{address.get('firstName', '')} {address.get('lastName', '')}".strip()
            if not customer_name:
                customer_name = str(address.get("companyName") or "")
                
        line_items = raw_order.get("items") or []
        product_summary = ", ".join([str(item.get("productName") or item.get("title") or "Item") for item in line_items])
        
        created_at_raw = raw_order.get("createdAt")
        order_created_at = None
        if created_at_raw:
            try:
                order_created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
            except ValueError:
                pass
                
        production_status_data = raw_order.get("_production_status") or {}
        status_raw = str(raw_order.get("fulfillmentStatus") or "").lower()
        production_status = str(production_status_data.get("status") or raw_order.get("productionStatus") or status_raw).lower()
        
        fulfillment_status = status_raw
        if status_raw in ["shipped", "fulfilled"]:
            fulfillment_status = "shipped"
            
        receipts = raw_order.get("receipts") or []
        if receipts and isinstance(receipts, list):
            total_amount = float(receipts[0].get("orderTotal") or receipts[0].get("total") or 0.0)
            currency = receipts[0].get("currency") or "USD"
        else:
            total_amount = float(raw_order.get("total") or raw_order.get("price") or 0.0)
            currency = raw_order.get("currency") or raw_order.get("retailCurrency") or "USD"
            
        shipment = raw_order.get("shipment") or {}
        packages = shipment.get("packages") or []
        tracking_url = None
        tracking_code = None
        if packages and isinstance(packages, list) and len(packages) > 0:
            tracking_url = packages[0].get("trackingUrl")
            tracking_code = packages[0].get("trackingCode")
            
        retail_amount = None
        if line_items:
            retail_sum = 0.0
            for item in line_items:
                rp = item.get("retailPriceInclVat") or item.get("retailPrice")
                if rp is not None:
                    retail_sum += float(rp)
            if retail_sum > 0:
                retail_amount = retail_sum
                
        destination_city = address.get("city")
        destination_country = address.get("country")
        
        return {
            "organization_id": organization_id,
            "provider_store_connection_id": provider_store_connection_id,
            "provider": self.provider,
            "external_order_id": external_order_id,
            "display_order_id": display_order_id,
            "marketplace_order_id": None,
            "customer_name": customer_name,
            "product_summary": product_summary,
            "fulfillment_status": fulfillment_status,
            "production_status": production_status,
            "financial_status": str(raw_order.get("financialStatus") or "paid").lower(),
            "currency": currency,
            "total_amount": total_amount,
            "retail_amount": retail_amount,
            "order_created_at": order_created_at,
            "shipped_at": None,
            "delivered_at": None,
            "cancelled_at": order_created_at if status_raw == "canceled" else None,
            "sent_to_production_at": None,
            "tracking_url": tracking_url,
            "tracking_code": tracking_code,
            "destination_city": destination_city,
            "destination_country": destination_country,
            "provider_order_url": self.get_order_url(provider_store_id=str(raw_order.get("storeId", "")), external_order_id=external_order_id),
            "raw_payload_json": raw_order,
        }

    def get_order_url(self, *, provider_store_id: str, external_order_id: str) -> str:
        return f"https://dashboard.gelato.com/orders/view/{external_order_id}"
