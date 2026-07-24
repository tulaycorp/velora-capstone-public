import assert from "node:assert/strict";
import test from "node:test";

import {
  createQueuedProductImage,
  isSupportedProductImage,
  truncateProductImageName
} from "./product-editor-media.ts";

test("keeps short names and preserves extensions when truncating", () => {
  assert.equal(truncateProductImageName("design.webp"), "design.webp");
  assert.equal(
    truncateProductImageName("a-very-long-marketplace-design-file.webp", 24),
    "a-very-long-mark...webp"
  );
  assert.equal(truncateProductImageName("averylongfilename", 10), "averylo...");
});

test("accepts the same safe image types and extensions used by both editors", () => {
  assert.equal(isSupportedProductImage({ name: "design.bin", type: "image/png" }), true);
  assert.equal(isSupportedProductImage({ name: "design.JPEG", type: "" }), true);
  assert.equal(isSupportedProductImage({ name: "design.svg", type: "image/svg+xml" }), false);
  assert.equal(isSupportedProductImage({ name: "design.gif", type: "image/gif" }), false);
});

test("creates a stable queue record around the original file", () => {
  const file = { name: "design.png", type: "image/png" } as File;
  assert.deepEqual(createQueuedProductImage(file, () => "queue-1"), {
    id: "queue-1",
    file
  });
});
