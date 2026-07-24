from __future__ import annotations

import contextvars
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings


REDACTED_VALUE = "[redacted]"
_REQUEST_ID = contextvars.ContextVar[str | None]("velora_request_id", default=None)
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "api-key",
    "api_token",
    "api-token",
    "token",
    "secret",
    "password",
    "cookie",
    "set-cookie",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.strip().lower().replace("_", "-")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    if _is_sensitive_key(key):
        return REDACTED_VALUE

    if isinstance(value, Mapping):
        return {str(item_key): sanitize_for_log(item_value, key=str(item_key)) for item_key, item_value in value.items()}

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_for_log(item) for item in value]

    return value


def summarize_mapping_for_log(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None

    summary: dict[str, Any] = {"keys": sorted(str(key) for key in payload.keys())}
    for count_key in (
        "variants",
        "print_areas",
        "tags",
        "mockup_urls",
        "sales_channel_properties",
        "manual_store_seeds",
        "imagePlaceholders",
    ):
        count_value = payload.get(count_key)
        if isinstance(count_value, list):
            summary[f"{count_key}_count"] = len(count_value)

    for bool_key in ("title", "description", "templateId", "shipping_template_id", "shipping_profile_id"):
        if bool_key in payload:
            summary[f"has_{bool_key.lower()}"] = bool(str(payload.get(bool_key) or "").strip())

    if "externalId" in payload:
        summary["has_external_id"] = bool(str(payload.get("externalId") or "").strip())
    if "status" in payload and payload.get("status") is not None:
        summary["status"] = str(payload["status"])

    return sanitize_for_log(summary)


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


def set_request_id(request_id: str | None):
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event_name", record.getMessage()),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }
        extra_fields = getattr(record, "event_fields", None)
        if isinstance(extra_fields, Mapping):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)


class PrettyLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_name = getattr(record, "event_name", record.getMessage())
        parts = [_utc_now_iso(), record.levelname.upper(), event_name]

        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            parts.append(f"request_id={request_id}")

        extra_fields = getattr(record, "event_fields", None)
        if isinstance(extra_fields, Mapping):
            for key in sorted(extra_fields):
                value = extra_fields[key]
                rendered = json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)
                parts.append(f"{key}={rendered}")

        if record.exc_info:
            parts.append(self.formatException(record.exc_info))

        return " ".join(parts)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("velora")
    handler = next(
        (item for item in logger.handlers if getattr(item, "_velora_handler", False)),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler._velora_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

    if settings.log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(PrettyLogFormatter())

    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"velora.{name}")


def log_event(
    logger: logging.Logger,
    event_name: str,
    *,
    level: int = logging.INFO,
    verbose_only: bool = False,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    if verbose_only and not settings.verbose_logging:
        return

    logger.log(
        level,
        event_name,
        extra={
            "event_name": event_name,
            "event_fields": sanitize_for_log(fields),
        },
        exc_info=exc_info,
    )
