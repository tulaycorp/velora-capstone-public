import assert from "node:assert/strict";
import test from "node:test";

import {
  createManualStoreSeed,
  formatCredentialCount,
  formatStorefrontCount,
  groupStoreConnectionsByType,
  latestSyncedAt,
  normalizeManualStoreSeedsForSave
} from "./organization-settings-state.ts";
import type { ProviderStoreConnection } from "./backend-api.ts";

test("normalizes manual store seeds and drops blank provider ids", () => {
  assert.deepEqual(normalizeManualStoreSeedsForSave([
    createManualStoreSeed({ provider_store_id: "  shop-1  ", label: "  Main  ", etsy_shop_id: " 42 " }),
    createManualStoreSeed()
  ]), [{
    provider_store_id: "shop-1",
    storefront_type: "etsy",
    storefront_display_name: "Etsy",
    label: "Main",
    etsy_shop_id: "42"
  }]);
});

test("keeps storefront grouping order and newest valid sync timestamp", () => {
  const connections = [
    { id: "shopify", storefront_type: "shopify", last_sync_at: "2026-07-17T00:00:00Z" },
    { id: "etsy-new", storefront_type: "etsy", last_sync_at: "2026-07-18T00:00:00Z" },
    { id: "etsy-old", storefront_type: "etsy", last_sync_at: "invalid" }
  ] as ProviderStoreConnection[];

  assert.deepEqual(groupStoreConnectionsByType(connections).map((group) => group.key), ["etsy", "shopify"]);
  assert.equal(latestSyncedAt(connections), "2026-07-18T00:00:00Z");
});

test("formats singular and plural settings counts", () => {
  assert.equal(formatStorefrontCount(1), "1 store");
  assert.equal(formatStorefrontCount(2), "2 stores");
  assert.equal(formatCredentialCount(1), "1 key");
  assert.equal(formatCredentialCount(0), "0 keys");
});
