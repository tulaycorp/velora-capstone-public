import test from "node:test";
import assert from "node:assert/strict";

import { getBackendApiBaseUrl } from "./api-base-url.ts";

test("rejects an HTTP BFF upstream outside local environments", () => {
  const originalEnvironment = process.env.VELORA_ENVIRONMENT;
  const originalUrl = process.env.VELORA_API_BASE_URL;
  process.env.VELORA_ENVIRONMENT = "staging";
  process.env.VELORA_API_BASE_URL = "http://api.example";

  assert.throws(() => getBackendApiBaseUrl(), /must use HTTPS/);

  if (originalEnvironment === undefined) delete process.env.VELORA_ENVIRONMENT;
  else process.env.VELORA_ENVIRONMENT = originalEnvironment;
  if (originalUrl === undefined) delete process.env.VELORA_API_BASE_URL;
  else process.env.VELORA_API_BASE_URL = originalUrl;
});
