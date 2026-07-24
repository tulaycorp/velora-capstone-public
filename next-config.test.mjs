import assert from "node:assert/strict";
import test from "node:test";

import nextConfig from "./next.config.mjs";

test("Next config sets browser security headers and hides framework fingerprinting", async () => {
  assert.equal(nextConfig.devIndicators, false);
  assert.equal(nextConfig.poweredByHeader, false);
  assert.equal(typeof nextConfig.headers, "function");

  const headerRules = await nextConfig.headers();
  const globalRule = headerRules.find((rule) => rule.source === "/:path*");

  assert.ok(globalRule, "expected a global header rule for every route");

  const headers = new Map(
    globalRule.headers.map((header) => [header.key.toLowerCase(), header.value])
  );

  assert.equal(headers.get("x-frame-options"), "DENY");
  assert.equal(headers.get("x-content-type-options"), "nosniff");
  assert.equal(
    headers.get("strict-transport-security"),
    "max-age=63072000; includeSubDomains; preload"
  );

  assert.equal(headers.has("content-security-policy"), false);
});
