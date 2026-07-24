from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
from collections import deque
from typing import Any, Deque
import re
from urllib.parse import urlparse

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


class PrintifyAdapter(BaseProviderAdapter):
    provider = "printify"
    API_TOKEN_NAME = "api_token"
    SHOP_ID_NAME = "shop_id"
    _global_rate_locks: dict[str, asyncio.Lock] = {}
    _global_rate_buckets: dict[str, Deque[float]] = {}
    _publish_rate_locks: dict[str, asyncio.Lock] = {}
    _publish_rate_buckets: dict[str, Deque[float]] = {}

    def __init__(self, credentials: dict[str, Any]):
        super().__init__(credentials)
        self.api_token = (
            str(self.credentials.get(self.API_TOKEN_NAME) or "").strip()
            or str(self.credentials.get("api_key") or "").strip()
        )
        self.shop_id = str(self.credentials.get(self.SHOP_ID_NAME) or "").strip()
        self.user_agent = settings.printify_user_agent
        self.base_url = settings.printify_api_base_url
        self._rate_key = self.api_token or self.shop_id or "printify-default"

    def _validate_token(self) -> None:
        if not self.api_token:
            raise ValueError("Missing Printify credential 'api_token'.")

    def _validate_shop(self) -> None:
        self._validate_token()
        if not self.shop_id:
            raise ValueError("Missing Printify store binding 'shop_id'.")

    def _get_client(self) -> httpx.AsyncClient:
        self._validate_token()
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
            },
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=40),
        )

    @classmethod
    def _get_lock(cls, lock_map: dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
        lock = lock_map.get(key)
        if lock is None:
            lock = asyncio.Lock()
            lock_map[key] = lock
        return lock

    @classmethod
    def _get_bucket(cls, bucket_map: dict[str, Deque[float]], key: str) -> Deque[float]:
        bucket = bucket_map.get(key)
        if bucket is None:
            bucket = deque()
            bucket_map[key] = bucket
        return bucket

    async def _wait_for_rate_slot(
        self,
        *,
        lock_map: dict[str, asyncio.Lock],
        bucket_map: dict[str, Deque[float]],
        key: str,
        limit: int,
        window_seconds: float,
    ) -> None:
        while True:
            lock = self._get_lock(lock_map, key)
            async with lock:
                now = time.monotonic()
                bucket = self._get_bucket(bucket_map, key)
                while bucket and (now - bucket[0]) >= window_seconds:
                    bucket.popleft()
                if len(bucket) < limit:
                    bucket.append(now)
                    return
                wait_for = max(0.05, window_seconds - (now - bucket[0]))
            await asyncio.sleep(wait_for)

    async def _throttle_request(self, path: str) -> None:
        await self._wait_for_rate_slot(
            lock_map=self._global_rate_locks,
            bucket_map=self._global_rate_buckets,
            key=self._rate_key,
            limit=settings.printify_max_requests_per_min,
            window_seconds=60.0,
        )
        if path.endswith("/publish.json"):
            await self._wait_for_rate_slot(
                lock_map=self._publish_rate_locks,
                bucket_map=self._publish_rate_buckets,
                key=self._rate_key,
                limit=settings.printify_publish_max_requests_per_30_min,
                window_seconds=1800.0,
            )

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {"raw": data}
        except Exception:
            return {"raw": resp.text}

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_on_429: bool = True,
    ) -> httpx.Response:
        transient_status_codes = {500, 502, 503, 504}
        for attempt in range(max_retries + 1):
            started_at = time.perf_counter()
            try:
                await self._throttle_request(path)
                response = await client.request(method, path, json=json_payload, timeout=timeout)
            except httpx.RequestError as exc:
                log_event(
                    provider_logger,
                    "provider.http.request_error",
                    level=logging.WARNING,
                    verbose_only=True,
                    provider=self.provider,
                    method=method,
                    path=path,
                    attempt=attempt + 1,
                    max_retries=max_retries + 1,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    payload_summary=summarize_mapping_for_log(json_payload),
                    error=str(exc),
                )
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(2**attempt)
                continue

            response_payload = self._safe_json(response)
            should_retry = (
                (response.status_code == 429 and retry_on_429)
                or response.status_code in transient_status_codes
            )
            log_event(
                provider_logger,
                "provider.http.response",
                verbose_only=True,
                provider=self.provider,
                method=method,
                path=path,
                attempt=attempt + 1,
                max_retries=max_retries + 1,
                status_code=response.status_code,
                will_retry=should_retry and attempt < max_retries,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                payload_summary=summarize_mapping_for_log(json_payload),
                response_summary=summarize_mapping_for_log(response_payload),
            )
            if should_retry and attempt < max_retries:
                retry_after_raw = response.headers.get("Retry-After", str(2**attempt))
                try:
                    retry_after = int(retry_after_raw)
                except Exception:
                    retry_after = 2**attempt
                await asyncio.sleep(retry_after)
                continue
            return response

        raise RuntimeError("Unexpected Printify retry loop termination.")

    @staticmethod
    def _normalize_reference(reference_value: str) -> str:
        trimmed = reference_value.strip()
        if not trimmed:
            raise ValueError("Printify reference is required.")
        from_path = re.search(r"/product-details/([A-Za-z0-9_-]+)", trimmed, re.IGNORECASE)
        if from_path:
            return from_path.group(1)
        if re.fullmatch(r"[A-Za-z0-9_-]+", trimmed):
            return trimmed
        raise ValueError("Printify references must be a product-details URL or product id.")

    @staticmethod
    def _normalize_upload_id(raw_id: Any) -> int | str:
        if isinstance(raw_id, int):
            return raw_id
        if isinstance(raw_id, str):
            stripped = raw_id.strip()
            if not stripped:
                raise RuntimeError("Printify upload returned an empty id.")
            return int(stripped) if stripped.isdigit() else stripped
        if raw_id is None:
            raise RuntimeError("Printify upload returned no id.")
        return str(raw_id)

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
    def _storefront_type(channel_raw: str) -> StorefrontType:
        channel = channel_raw.strip().lower()
        if "etsy" in channel:
            return "etsy"
        if "shopify" in channel:
            return "shopify"
        return "unknown"

    @staticmethod
    def _extract_etsy_shop_id(storefront_type: StorefrontType, payload: dict[str, Any]) -> str | None:
        if storefront_type != "etsy":
            return None

        direct_candidates = (
            payload.get("etsy_shop_id"),
            payload.get("marketplace_shop_id"),
            payload.get("etsyShopId"),
            payload.get("marketplaceShopId"),
        )
        for candidate in direct_candidates:
            normalized = str(candidate or "").strip()
            if normalized:
                return normalized

        for container_key in ("sales_channel_properties", "marketplace", "marketplace_data", "external"):
            container = payload.get(container_key)
            if isinstance(container, dict):
                candidate = next(
                    (
                        value
                        for value in (
                            container.get("etsy_shop_id"),
                            container.get("marketplace_shop_id"),
                            container.get("shop_id"),
                            container.get("shopId"),
                            container.get("etsyShopId"),
                            container.get("marketplaceShopId"),
                        )
                        if str(value or "").strip()
                    ),
                    None,
                )
                if candidate is not None:
                    return str(candidate).strip()
        return None

    @staticmethod
    def _build_configuration_summary(product: dict[str, Any]) -> str:
        variant_count = len(product.get("variants") or [])
        placeholder_count = sum(
            len(area.get("placeholders") or [])
            for area in product.get("print_areas") or []
            if isinstance(area, dict)
        )
        parts = [f"{variant_count} variants"]
        if placeholder_count:
            parts.append(f"{placeholder_count} print placeholders")
        blueprint_id = product.get("blueprint_id")
        print_provider_id = product.get("print_provider_id")
        if blueprint_id and print_provider_id:
            parts.append(f"blueprint {blueprint_id}")
            parts.append(f"provider {print_provider_id}")
        return ", ".join(parts)

    @staticmethod
    def _payload_has_shipping_metadata(payload: dict[str, Any]) -> bool:
        if any(payload.get(key) is not None for key in ("shipping_template_id", "shipping_profile_id", "shipping_template")):
            return True
        external = payload.get("external")
        if isinstance(external, dict) and external.get("shipping_template_id") is not None:
            return True
        return False

    @staticmethod
    def _product_has_expected_tags(product: dict[str, Any], expected_tags: list[str]) -> bool:
        if not expected_tags:
            return True
        product_tags = PrintifyAdapter._normalize_tags(product.get("tags"))
        if not product_tags:
            return False
        return {tag.casefold() for tag in expected_tags}.issubset({tag.casefold() for tag in product_tags})

    @classmethod
    def _product_has_shipping_metadata(cls, product: dict[str, Any]) -> bool:
        if any(product.get(key) is not None for key in ("shipping_template_id", "shipping_profile_id", "shipping_template")):
            return True
        external = product.get("external")
        if isinstance(external, dict) and external.get("shipping_template_id") is not None:
            return True
        return False

    @staticmethod
    def _build_metadata_update_payload(
        *,
        source_payload: dict[str, Any],
        include_tags: bool,
        include_shipping: bool,
    ) -> dict[str, Any]:
        update_payload: dict[str, Any] = {}
        if include_tags and source_payload.get("tags") is not None:
            update_payload["tags"] = source_payload.get("tags")
        if include_shipping:
            for key in ("shipping_template_id", "shipping_profile_id", "shipping_template"):
                if source_payload.get(key) is not None:
                    update_payload[key] = source_payload.get(key)
            external = source_payload.get("external")
            if isinstance(external, dict) and external.get("shipping_template_id") is not None:
                update_payload["external"] = {"shipping_template_id": external.get("shipping_template_id")}
        return update_payload

    @staticmethod
    def _normalize_external_listing_id(value: Any) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if normalized.startswith(("http://", "https://")):
            parsed = urlparse(normalized)
            if parsed.hostname and parsed.hostname.lower().endswith("etsy.com"):
                match = re.search(r"/listing/(\d+)(?:/|$)", parsed.path)
                return match.group(1) if match else None
        return normalized

    @staticmethod
    def _extract_external_listing_id(data: dict[str, Any]) -> str | None:
        external = data.get("external")
        if isinstance(external, dict):
            for key in ("id", "handle", "url"):
                normalized = PrintifyAdapter._normalize_external_listing_id(external.get(key))
                if normalized:
                    return normalized
        channel_props = data.get("sales_channel_properties")
        if isinstance(channel_props, list):
            for item in channel_props:
                if not isinstance(item, dict):
                    continue
                for key in ("id", "external_id", "listing_id", "channel_listing_id", "handle", "url"):
                    value = item.get(key)
                    if value:
                        normalized = PrintifyAdapter._normalize_external_listing_id(value)
                        if normalized:
                            return normalized
        return None

    @staticmethod
    def _extract_publish_error(data: dict[str, Any]) -> str | None:
        status_candidates = (
            data.get("publishing_status"),
            data.get("publish_status"),
            data.get("status"),
        )
        failed_statuses = {"failed", "error", "publishing_failed", "publish_failed"}
        if not any(str(value or "").strip().lower() in failed_statuses for value in status_candidates):
            return None

        for key in ("error", "error_message", "message", "detail"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for nested_key in ("message", "detail", "error"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, str) and nested_value.strip():
                        return nested_value.strip()
        return "Printify reported that storefront publishing failed."

    async def _get_product(self, client: httpx.AsyncClient, product_id: str) -> dict[str, Any]:
        response = await self._request_with_retry(
            client,
            "GET",
            f"/v1/shops/{self.shop_id}/products/{product_id}.json",
            timeout=30.0,
        )
        payload = self._safe_json(response)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch Printify product '{product_id}': {response.status_code} {payload}")
        return payload

    async def _upload_design_asset(
        self,
        client: httpx.AsyncClient,
        *,
        image_url: str,
        file_name: str,
    ) -> dict[str, Any]:
        separator = "&" if "?" in image_url else "?"
        cache_busting_url = f"{image_url}{separator}cb={int(time.time())}"
        response = await self._request_with_retry(
            client,
            "POST",
            "/v1/uploads/images.json",
            json_payload={"file_name": file_name, "url": cache_busting_url},
            timeout=60.0,
        )
        response_payload = self._safe_json(response)
        if response.status_code != 200:
            raise RuntimeError(f"Printify design upload failed: {response.status_code} {response_payload}")
        return {
            "id": self._normalize_upload_id(response_payload.get("id")),
            "width": response_payload.get("width"),
            "height": response_payload.get("height"),
        }

    @staticmethod
    def _variant_ids_with_artwork(source: dict[str, Any]) -> set[int]:
        variant_ids_with_artwork: set[int] = set()
        for area in source.get("print_areas", []):
            if not isinstance(area, dict):
                continue
            variant_ids = {int(value) for value in area.get("variant_ids", []) if value is not None}
            placeholders = area.get("placeholders") or []
            if variant_ids and any(
                isinstance(placeholder, dict) and bool(placeholder.get("images"))
                for placeholder in placeholders
            ):
                variant_ids_with_artwork.update(variant_ids)
        return variant_ids_with_artwork

    @staticmethod
    def _resolve_default_variant_id(
        source_variants: list[dict[str, Any]],
        *,
        artwork_variant_ids: set[int],
    ) -> int:
        def pick_variant_id(*, require_default: bool, require_artwork: bool) -> int | None:
            for variant in source_variants:
                if not variant.get("is_enabled"):
                    continue
                if require_default and not variant.get("is_default"):
                    continue
                variant_id = int(variant["id"])
                if require_artwork and variant_id not in artwork_variant_ids:
                    continue
                return variant_id
            return None

        for require_default, require_artwork in (
            (True, True),
            (False, True),
            (True, False),
            (False, False),
        ):
            selected_variant_id = pick_variant_id(
                require_default=require_default,
                require_artwork=require_artwork,
            )
            if selected_variant_id is not None:
                return selected_variant_id

        raise RuntimeError("Source Printify product has no enabled variants.")

    @staticmethod
    def _build_upload_file_name(*, product_id: str, image_url: str) -> str:
        file_name = urlparse(image_url).path.rsplit("/", 1)[-1]
        extension = f".{file_name.rsplit('.', 1)[-1]}" if "." in file_name else ""
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", extension or ""):
            extension = ".png"
        return f"velora-{product_id}{extension}"

    def _build_create_payload(
        self,
        *,
        source: dict[str, Any],
        payload: ProviderProductCreateInput,
        design_upload: dict[str, Any],
    ) -> dict[str, Any]:
        blueprint_id = source.get("blueprint_id")
        print_provider_id = source.get("print_provider_id")
        if blueprint_id is None or print_provider_id is None:
            raise RuntimeError("Printify source product is missing blueprint_id or print_provider_id.")

        variants: list[dict[str, Any]] = []
        normalized_sku = (payload.sku or "").strip()
        source_variants = [variant for variant in source.get("variants", []) if isinstance(variant, dict)]
        default_variant_id = self._resolve_default_variant_id(
            source_variants,
            artwork_variant_ids=self._variant_ids_with_artwork(source),
        )
        for variant in source_variants:
            variant_id = int(variant["id"])
            variant_payload = {
                "id": variant_id,
                "price": int(variant["price"]),
                "is_enabled": bool(variant["is_enabled"]),
                "is_default": variant_id == default_variant_id,
            }
            if normalized_sku:
                source_variant_sku = str(variant.get("sku") or "").strip()
                numeric_suffix = "".join(ch for ch in source_variant_sku if ch.isdigit())[-5:]
                source_suffix = numeric_suffix or (source_variant_sku[-5:] if source_variant_sku else str(variant_id)[-5:])
                variant_payload["sku"] = f"{normalized_sku}{source_suffix}"
            variants.append(variant_payload)
        if not variants:
            raise RuntimeError("Source Printify product has no variants.")

        print_areas: list[dict[str, Any]] = []
        for area in source.get("print_areas", []):
            if not isinstance(area, dict):
                continue
            variant_ids = [int(value) for value in area.get("variant_ids", []) if value is not None]
            if not variant_ids:
                raise RuntimeError("Source Printify print area is missing variant_ids.")
            placeholders: list[dict[str, Any]] = []
            for placeholder in area.get("placeholders", []):
                if not isinstance(placeholder, dict):
                    continue
                position = str(placeholder.get("position") or "").strip()
                if not position:
                    raise RuntimeError("Source Printify print area has a placeholder without position.")
                original_images = placeholder.get("images") or []
                placement = original_images[0] if original_images and isinstance(original_images[0], dict) else {}
                placeholders.append(
                    {
                        "position": position,
                        "images": [
                            {
                                "id": design_upload["id"],
                                "x": float(placement.get("x", 0.5)),
                                "y": float(placement.get("y", 0.5)),
                                "scale": float(placement.get("scale", 1.0)),
                                "angle": float(placement.get("angle", 0)),
                            }
                        ],
                    }
                )
            if not placeholders:
                placeholders = [
                    {
                        "position": "front",
                        "images": [{"id": design_upload["id"], "x": 0.5, "y": 0.5, "scale": 1.0, "angle": 0}],
                    }
                ]
            area_payload: dict[str, Any] = {"variant_ids": variant_ids, "placeholders": placeholders}
            if area.get("background") is not None:
                area_payload["background"] = area["background"]
            print_areas.append(area_payload)
        if not print_areas:
            raise RuntimeError("Source Printify product has no print areas for the fulfillment design.")

        create_payload: dict[str, Any] = {
            "title": payload.title,
            "blueprint_id": int(blueprint_id),
            "print_provider_id": int(print_provider_id),
            "variants": variants,
            "print_areas": print_areas,
            "visible": False,
        }
        normalized_description = (payload.description or "").strip()
        normalized_tags = self._normalize_tags(payload.tags)
        source_tags = self._normalize_tags(source.get("tags"))
        if normalized_description:
            create_payload["description"] = normalized_description
        elif source.get("description") is not None:
            create_payload["description"] = source.get("description")
        if normalized_tags:
            create_payload["tags"] = normalized_tags
        elif source_tags:
            create_payload["tags"] = source_tags
        if source.get("safety_information") is not None:
            create_payload["safety_information"] = source.get("safety_information")
        if source.get("shipping_template_id") is not None:
            create_payload["shipping_template_id"] = source.get("shipping_template_id")
        if source.get("shipping_profile_id") is not None:
            create_payload["shipping_profile_id"] = source.get("shipping_profile_id")
        if source.get("shipping_template") is not None:
            create_payload["shipping_template"] = source.get("shipping_template")
        source_external = source.get("external")
        if isinstance(source_external, dict) and source_external.get("shipping_template_id") is not None:
            create_payload["external"] = {"shipping_template_id": source_external.get("shipping_template_id")}
        return create_payload

    async def _apply_metadata_update(
        self,
        client: httpx.AsyncClient,
        *,
        product_id: str,
        update_payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request_with_retry(
            client,
            "PUT",
            f"/v1/shops/{self.shop_id}/products/{product_id}.json",
            json_payload=update_payload,
            timeout=60.0,
        )
        payload = self._safe_json(response)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Update product metadata failed: {response.status_code} {payload}")
        if payload.get("id"):
            return payload
        return await self._get_product(client, product_id)

    async def discover_store_connections(self) -> list[ProviderStoreRecord]:
        self._validate_token()
        async with self._get_client() as client:
            response = await self._request_with_retry(client, "GET", "/v1/shops.json", timeout=30.0)
        payload = response.json()
        if response.status_code != 200 or not isinstance(payload, list):
            raise RuntimeError(f"Failed to fetch Printify shops: {response.status_code} {payload}")
        stores: list[ProviderStoreRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            shop_id = str(item.get("id") or "").strip()
            if not shop_id:
                continue
            title = str(item.get("title") or "").strip() or f"Printify Shop {shop_id}"
            channel_raw = str(item.get("sales_channel") or item.get("channel") or "").strip()
            storefront_type = self._storefront_type(channel_raw)
            channel_name = channel_raw or "Unknown"
            stores.append(
                ProviderStoreRecord(
                    provider_store_id=shop_id,
                    storefront_type=storefront_type,
                    storefront_display_name=channel_name,
                    label=f"{title} -> {channel_name}",
                    etsy_shop_id=self._extract_etsy_shop_id(storefront_type, item),
                    discovery_source="provider_api",
                )
            )
        return stores

    async def validate_reference(
        self,
        *,
        reference_type: str,
        reference_value: str,
    ) -> ReferenceValidationResult:
        if reference_type not in {"printify_product_url", "printify_product_id"}:
            raise ValueError(f"Unsupported Printify reference type '{reference_type}'.")
        normalized_id = self._normalize_reference(reference_value)
        snapshot = await self.fetch_reference_snapshot(
            reference_type=reference_type,
            reference_value=reference_value,
            provider_resource_id=normalized_id,
        )
        return ReferenceValidationResult(
            reference_type="printify_product_url",
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
        self._validate_shop()
        async with self._get_client() as client:
            product = await self._get_product(client, provider_resource_id)
        variants = product.get("variants") or []
        costs = [variant.get("cost") for variant in variants if isinstance(variant, dict) and variant.get("cost") is not None]
        min_cost = min(costs) / 100 if costs else None
        return ReferenceSnapshotResult(
            provider_resource_id=provider_resource_id,
            provider_display_name=str(product.get("title") or "").strip() or f"Printify Product {provider_resource_id}",
            provider_snapshot_json=product,
            product_type=str(product.get("title") or "").strip() or "Printify Product",
            configuration_summary=self._build_configuration_summary(product),
            variant_count=len(variants),
            base_cost_amount=min_cost,
            currency="USD" if min_cost is not None else None,
            base_title=str(product.get("title") or "").strip() or None,
            base_description=str(product.get("description") or "").strip() or None,
            base_tags=self._normalize_tags(product.get("tags")),
        )

    async def create_provider_product(
        self,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult:
        self._validate_shop()
        source_product = payload.provider_snapshot_json
        async with self._get_client() as client:
            if not source_product:
                source_product = await self._get_product(client, payload.provider_resource_id)
            return await self._sync_provider_product(
                client,
                source_product=source_product,
                payload=payload,
            )

    async def reconcile_provider_product(
        self,
        *,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult | None:
        self._validate_shop()
        async with self._get_client() as client:
            response = await self._request_with_retry(
                client,
                "GET",
                f"/v1/shops/{self.shop_id}/products.json?page=1&limit=50",
                timeout=30.0,
            )
        data = self._safe_json(response)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to reconcile Printify products: {response.status_code}")
        source = payload.provider_snapshot_json or {}
        submitted_after = payload.submitted_at.astimezone(timezone.utc) - timedelta(minutes=15)
        matches: list[dict[str, Any]] = []
        for item in data.get("data") or []:
            if not isinstance(item, dict) or str(item.get("title") or "").strip() != payload.title:
                continue
            if source.get("blueprint_id") and item.get("blueprint_id") != source.get("blueprint_id"):
                continue
            if source.get("print_provider_id") and item.get("print_provider_id") != source.get("print_provider_id"):
                continue
            created_raw = str(item.get("created_at") or "").strip()
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
            external_listing_id=self._extract_external_listing_id(product),
            provider_status="published" if product.get("is_locked") or product.get("external") else "created",
            raw_provider_payload_json=product,
        )

    async def update_provider_product(
        self,
        *,
        provider_product_id: str,
        payload: ProviderProductCreateInput,
    ) -> ProviderProductCreateResult:
        self._validate_shop()
        source_product = payload.provider_snapshot_json
        async with self._get_client() as client:
            if not source_product:
                source_product = await self._get_product(client, provider_product_id)
            return await self._sync_provider_product(
                client,
                source_product=source_product,
                payload=payload,
                provider_product_id=provider_product_id,
            )

    async def _sync_provider_product(
        self,
        client: httpx.AsyncClient,
        *,
        source_product: dict[str, Any],
        payload: ProviderProductCreateInput,
        provider_product_id: str | None = None,
    ) -> ProviderProductCreateResult:
        design_upload = await self._upload_design_asset(
            client,
            image_url=payload.design_asset_url,
            file_name=self._build_upload_file_name(
                product_id=payload.product_id,
                image_url=payload.design_asset_url,
            ),
        )
        product_payload = self._build_create_payload(
            source=source_product,
            payload=payload,
            design_upload=design_upload,
        )
        if provider_product_id:
            # Printify accepts these catalog/state fields when creating a product,
            # but documents them as read-only once the product exists. Sending
            # them on an update can turn an otherwise valid fulfillment update
            # into a 400 response.
            for read_only_field in ("blueprint_id", "print_provider_id", "visible"):
                product_payload.pop(read_only_field, None)
        expected_tags = self._normalize_tags(product_payload.get("tags"))
        expected_shipping = self._payload_has_shipping_metadata(product_payload)

        if provider_product_id:
            response = await self._request_with_retry(
                client,
                "PUT",
                f"/v1/shops/{self.shop_id}/products/{provider_product_id}.json",
                json_payload=product_payload,
                timeout=60.0,
            )
            response_data = self._safe_json(response)
            if response.status_code not in (200, 201):
                raise RuntimeError(f"Update product failed: {response.status_code} {response_data}")
            product_id = provider_product_id
            synced_product = response_data if response_data.get("id") else await self._get_product(client, product_id)
        else:
            response = await self._request_with_retry(
                client,
                "POST",
                f"/v1/shops/{self.shop_id}/products.json",
                json_payload=product_payload,
                timeout=60.0,
            )
            response_data = self._safe_json(response)
            if response.status_code not in (200, 201):
                raise RuntimeError(f"Create product failed: {response.status_code} {response_data}")
            product_id = str(response_data.get("id") or "").strip()
            if not product_id:
                raise RuntimeError(f"Printify create succeeded but no product id was returned: {response_data}")
            synced_product = await self._get_product(client, product_id)

        missing_tags = bool(expected_tags) and not self._product_has_expected_tags(synced_product, expected_tags)
        missing_shipping = expected_shipping and not self._product_has_shipping_metadata(synced_product)
        if missing_tags or missing_shipping:
            metadata_update_payload = self._build_metadata_update_payload(
                source_payload=product_payload,
                include_tags=missing_tags,
                include_shipping=missing_shipping,
            )
            if metadata_update_payload:
                synced_product = await self._apply_metadata_update(
                    client,
                    product_id=product_id,
                    update_payload=metadata_update_payload,
                )

        external_listing_id = (
            self._extract_external_listing_id(response_data)
            or self._extract_external_listing_id(synced_product)
        )
        return ProviderProductCreateResult(
            provider_product_id=product_id,
            external_listing_id=external_listing_id,
            provider_status="published" if external_listing_id else "created",
            raw_provider_payload_json=synced_product,
        )

    async def _wait_for_publish_completion(
        self,
        client: httpx.AsyncClient,
        *,
        provider_product_id: str,
    ) -> dict[str, Any]:
        """Wait for Printify to finish its asynchronous storefront publish."""
        timeout_seconds = max(1.0, float(settings.printify_poll_timeout_seconds))
        delay_seconds = max(0.1, float(settings.printify_poll_initial_delay_seconds))
        max_delay_seconds = max(delay_seconds, float(settings.printify_poll_max_delay_seconds))
        deadline = time.monotonic() + timeout_seconds
        poll_count = 0
        last_product: dict[str, Any] = {}

        while time.monotonic() < deadline:
            last_product = await self._get_product(client, provider_product_id)
            poll_count += 1
            external_listing_id = self._extract_external_listing_id(last_product)
            publish_error = self._extract_publish_error(last_product)
            log_event(
                provider_logger,
                "provider.publish.poll",
                verbose_only=True,
                provider=self.provider,
                provider_product_id=provider_product_id,
                poll_count=poll_count,
                provider_status=last_product.get("publishing_status") or last_product.get("status"),
                is_locked=last_product.get("is_locked"),
                external_listing_id_present=bool(external_listing_id),
            )
            if external_listing_id:
                return last_product
            if publish_error:
                raise RuntimeError(publish_error)

            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                break
            await asyncio.sleep(min(delay_seconds, remaining_seconds))
            delay_seconds = min(max_delay_seconds, delay_seconds * 1.5)

        raise RuntimeError(
            "Printify did not return the connected storefront listing id before the publish timeout."
        )

    async def publish_provider_product(
        self,
        *,
        provider_product_id: str,
    ) -> ProviderPublishResult:
        self._validate_shop()
        publish_payload = {
            "title": True,
            "description": True,
            "variants": True,
            "tags": True,
            "keyFeatures": True,
            "shipping_template": True,
            "category": True,
            "categories": True,
            "attributes": True,
        }
        async with self._get_client() as client:
            response = await self._request_with_retry(
                client,
                "POST",
                f"/v1/shops/{self.shop_id}/products/{provider_product_id}/publish.json",
                json_payload=publish_payload,
                timeout=60.0,
            )
            payload = self._safe_json(response)
            if response.status_code != 200:
                raise RuntimeError(f"Publish product failed: {response.status_code} {payload}")
            refreshed_product = await self._wait_for_publish_completion(
                client,
                provider_product_id=provider_product_id,
            )
        external_listing_id = self._extract_external_listing_id(payload) or self._extract_external_listing_id(refreshed_product)
        return ProviderPublishResult(
            provider_product_id=provider_product_id,
            external_listing_id=external_listing_id,
            provider_status="published",
            raw_provider_payload_json=refreshed_product,
        )

    async def fetch_provider_product_status(
        self,
        *,
        provider_product_id: str,
    ) -> ProviderProductStatus:
        self._validate_shop()
        async with self._get_client() as client:
            product = await self._get_product(client, provider_product_id)
        return ProviderProductStatus(
            provider_product_id=provider_product_id,
            external_listing_id=self._extract_external_listing_id(product),
            provider_status="published" if product.get("is_locked") or product.get("external") else "created",
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
        self._validate_token()
        try:
            page_number = max(int(cursor or "1"), 1)
        except ValueError as exc:
            raise ValueError("Printify order cursor must be a page number.") from exc

        async with self._get_client() as client:
            response = await self._request_with_retry(
                client,
                "GET",
                f"/v1/shops/{provider_store_id}/orders.json?page={page_number}&limit={limit}",
                timeout=30.0,
            )
            payload = self._safe_json(response)
            if response.status_code != 200:
                raise RuntimeError(f"Printify order page request failed with status {response.status_code}.")

            raw_orders = payload.get("data") if isinstance(payload.get("data"), list) else []
            eligible_orders: list[dict[str, Any]] = []
            observed_timestamps: list[datetime] = []
            reached_since_boundary = False
            for raw_order in raw_orders:
                if not isinstance(raw_order, dict):
                    continue
                observed_at = self._parse_order_sync_timestamp(raw_order)
                if observed_at is not None:
                    observed_timestamps.append(observed_at)
                if since is not None and observed_at is not None and observed_at < since:
                    reached_since_boundary = True
                    continue
                eligible_orders.append(raw_order)

            semaphore = asyncio.Semaphore(settings.order_sync_detail_concurrency)

            async def fetch_detail(raw_order: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
                order_id = raw_order.get("id")
                if not order_id:
                    return None, "missing_order_id"
                try:
                    async with semaphore:
                        detail_response = await self._request_with_retry(
                            client,
                            "GET",
                            f"/v1/shops/{provider_store_id}/orders/{order_id}.json",
                            timeout=30.0,
                        )
                except Exception:
                    return None, "detail_request_failed"
                if detail_response.status_code != 200:
                    return None, "detail_request_failed"
                return self._safe_json(detail_response), None

            detail_results = await asyncio.gather(*(fetch_detail(order) for order in eligible_orders))
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

            current_page = int(payload.get("current_page") or page_number)
            last_page_raw = payload.get("last_page")
            has_more = (
                current_page < int(last_page_raw)
                if isinstance(last_page_raw, int) or str(last_page_raw or "").isdigit()
                else len(raw_orders) >= limit
            )
            if reached_since_boundary:
                has_more = False

            return ProviderOrderPage(
                orders=detailed_orders,
                fetched_count=len(eligible_orders),
                skipped_count=skipped_count,
                failed_count=failed_count,
                next_cursor=str(current_page + 1) if has_more else None,
                observed_watermark_at=max(observed_timestamps, default=None),
            )

    @staticmethod
    def _parse_order_sync_timestamp(raw_order: dict[str, Any]) -> datetime | None:
        for key in ("updated_at", "created_at"):
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
        metadata = raw_order.get("metadata") or {}
        display_order_id = str(metadata.get("shop_order_label") or metadata.get("shop_order_id") or external_order_id)
        
        customer_name = ""
        address = raw_order.get("address_to") or {}
        if address:
            customer_name = f"{address.get('first_name', '')} {address.get('last_name', '')}".strip()
            
        line_items = raw_order.get("line_items") or []
        product_summary = ", ".join([str(item.get("metadata", {}).get("title") or "Item") for item in line_items])
        
        created_at_raw = raw_order.get("created_at")
        order_created_at = None
        if created_at_raw:
            try:
                order_created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
            except ValueError:
                pass
                
        sent_raw = raw_order.get("sent_to_production_at")
        sent_to_production_at = None
        if sent_raw:
            try:
                sent_to_production_at = datetime.fromisoformat(str(sent_raw).replace("Z", "+00:00"))
            except ValueError:
                pass
                
        shipped_at = None
        shipments = raw_order.get("shipments") or []
        tracking_url = None
        tracking_code = None
        if shipments and isinstance(shipments, list) and len(shipments) > 0:
            shipment_time = shipments[0].get("shipment_date")
            if shipment_time:
                try:
                    shipped_at = datetime.fromisoformat(str(shipment_time).replace("Z", "+00:00"))
                except ValueError:
                    pass
            tracking_url = shipments[0].get("url")
            tracking_code = shipments[0].get("number")

        status_raw = str(raw_order.get("status") or "").lower()
        fulfillment_status = status_raw
        if status_raw in ["fulfilled", "shipped"]:
            fulfillment_status = "shipped"
            
        total_amount = float(raw_order.get("total_price") or 0.0) / 100.0
        
        retail_amount = None
        if line_items:
            retail_amount = sum((float(item.get("metadata", {}).get("price") or 0.0) / 100.0) for item in line_items)
            
        destination_city = address.get("city")
        destination_country = address.get("country")
        
        return {
            "organization_id": organization_id,
            "provider_store_connection_id": provider_store_connection_id,
            "provider": self.provider,
            "external_order_id": external_order_id,
            "display_order_id": display_order_id,
            "marketplace_order_id": str(metadata.get("shop_order_id") or ""),
            "customer_name": customer_name,
            "product_summary": product_summary,
            "fulfillment_status": fulfillment_status,
            "production_status": status_raw,
            "financial_status": "paid",
            "currency": "USD",
            "total_amount": total_amount,
            "retail_amount": retail_amount,
            "order_created_at": order_created_at,
            "shipped_at": shipped_at,
            "delivered_at": None,
            "cancelled_at": order_created_at if status_raw == "canceled" else None,
            "sent_to_production_at": sent_to_production_at,
            "tracking_url": tracking_url,
            "tracking_code": tracking_code,
            "destination_city": destination_city,
            "destination_country": destination_country,
            "provider_order_url": self.get_order_url(provider_store_id=str(raw_order.get("shop_id") or provider_store_id), external_order_id=external_order_id),
            "raw_payload_json": raw_order,
        }

    def get_order_url(self, *, provider_store_id: str, external_order_id: str) -> str:
        return f"https://printify.com/app/store/{provider_store_id}/order/{external_order_id}"
