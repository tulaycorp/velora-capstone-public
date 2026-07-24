import assert from "node:assert/strict";
import test from "node:test";

import {
  cleanStoreDisplayName,
  splitStoreDisplayLabel,
} from "./store-display.ts";

test("cleanStoreDisplayName removes ASCII and Unicode relationship suffixes", () => {
  assert.equal(cleanStoreDisplayName("Peddlex -> etsy"), "Peddlex");
  assert.equal(cleanStoreDisplayName("Tine's Cozy Crafts → Etsy"), "Tine's Cozy Crafts");
  assert.equal(cleanStoreDisplayName("Peddlex"), "Peddlex");
});

test("splitStoreDisplayLabel preserves relationship metadata for secondary UI", () => {
  assert.deepEqual(splitStoreDisplayLabel("Peddlex -> shopify"), {
    name: "Peddlex",
    relationship: "shopify",
  });
  assert.equal(cleanStoreDisplayName("", "All Stores"), "All Stores");
});
