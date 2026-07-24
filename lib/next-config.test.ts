import assert from "node:assert/strict";
import test from "node:test";

import nextConfig from "../next.config.mjs";

test("allows a 95 MiB Product Studio file plus multipart overhead", () => {
  assert.equal(
    nextConfig.experimental?.middlewareClientMaxBodySize,
    "100mb"
  );
});
