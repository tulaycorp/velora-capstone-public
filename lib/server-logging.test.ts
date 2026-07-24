import assert from "node:assert/strict";
import test from "node:test";

import {
  REDACTED_VALUE,
  formatServerLogLine,
  isVerboseServerLoggingEnabled,
  sanitizeServerLogFields
} from "./server-logging.ts";

test("sanitizeServerLogFields redacts nested secrets", () => {
  const payload = {
    authorization: "Bearer top-secret",
    "content-type": "application/json",
    nested: {
      api_token: "token-123",
      safe: "value"
    }
  };

  const sanitized = sanitizeServerLogFields(payload) as Record<string, unknown>;
  const nested = sanitized.nested as Record<string, unknown>;

  assert.equal(sanitized.authorization, REDACTED_VALUE);
  assert.equal(sanitized["content-type"], "application/json");
  assert.equal(nested.api_token, REDACTED_VALUE);
  assert.equal(nested.safe, "value");
});

test("isVerboseServerLoggingEnabled recognizes truthy values", () => {
  assert.equal(isVerboseServerLoggingEnabled({ VELORA_VERBOSE_LOGGING: "true" }), true);
  assert.equal(isVerboseServerLoggingEnabled({ VELORA_VERBOSE_LOGGING: "1" }), true);
  assert.equal(isVerboseServerLoggingEnabled({ VELORA_VERBOSE_LOGGING: "false" }), false);
});

test("formatServerLogLine renders stable pretty output", () => {
  const line = formatServerLogLine("pretty", {
    event: "bff.request.completed",
    level: "info",
    actor_id: "user_123",
    job_id: "job_456",
    provider_store_connection_id: "conn_789",
    request_id: "req-123",
    status: 200,
    ts: "2026-06-04T10:00:00.000Z"
  });

  assert.match(line, /actor_id=user_123/);
  assert.match(line, /bff\.request\.completed/);
  assert.match(line, /job_id=job_456/);
  assert.match(line, /provider_store_connection_id=conn_789/);
  assert.match(line, /request_id=req-123/);
  assert.match(line, /status=200/);
});
