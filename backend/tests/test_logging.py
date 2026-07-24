from __future__ import annotations

import logging

from app.core.logging import (
    JsonLogFormatter,
    PrettyLogFormatter,
    REDACTED_VALUE,
    sanitize_for_log,
)


def test_sanitize_for_log_redacts_nested_sensitive_fields() -> None:
    payload = {
        "authorization": "Bearer top-secret",
        "content_type": "application/json",
        "nested": {
            "api_token": "token-123",
            "safe": "value",
        },
    }

    sanitized = sanitize_for_log(payload)

    assert sanitized["authorization"] == REDACTED_VALUE
    assert sanitized["content_type"] == "application/json"
    assert sanitized["nested"]["api_token"] == REDACTED_VALUE
    assert sanitized["nested"]["safe"] == "value"


def test_request_logging_middleware_sets_response_request_id_header(client) -> None:
    response = client.get("/health", headers={"x-request-id": "req-test-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test-123"


def test_log_formatters_include_request_and_job_correlation_fields() -> None:
    record = logging.getLogger("velora.tests").makeRecord(
        "velora.tests",
        logging.INFO,
        __file__,
        0,
        "orders.sync_job.completed",
        args=(),
        exc_info=None,
    )
    record.event_name = "orders.sync_job.completed"
    record.request_id = "req-test-456"
    record.event_fields = {
        "job_id": "job-123",
        "organization_id": "org-123",
        "provider": "printify",
        "provider_store_connection_id": "conn-123",
    }

    pretty_line = PrettyLogFormatter().format(record)
    json_line = JsonLogFormatter().format(record)

    assert "request_id=req-test-456" in pretty_line
    assert "job_id=job-123" in pretty_line
    assert "organization_id=org-123" in pretty_line
    assert '"job_id":"job-123"' in json_line
    assert '"provider_store_connection_id":"conn-123"' in json_line
