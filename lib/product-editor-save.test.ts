import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProductEditorListingInput,
  withProductPublishingStatus
} from "./product-editor-save.ts";

test("normalizes the shared product editor save contract", () => {
  assert.deepEqual(buildProductEditorListingInput({
    title: "  ",
    description: "  Description  ",
    designDescription: " ",
    tags: ["one"],
    retailPrice: "39.99",
    currency: " ",
    sku: "  SKU-1  "
  }, "Fallback title"), {
    title: "Fallback title",
    description: "Description",
    design_description: null,
    tags: ["one"],
    retail_price: 39.99,
    currency: "USD",
    sku: "SKU-1"
  });
});

test("updates publishing state without mutating the saved product", () => {
  const product = { id: "product-1", publishing_status: "ready" };
  const updated = withProductPublishingStatus(product, "queued");
  assert.deepEqual(updated, { id: "product-1", publishing_status: "queued" });
  assert.equal(product.publishing_status, "ready");
});
