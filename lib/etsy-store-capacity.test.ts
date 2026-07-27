import assert from "node:assert/strict";
import test from "node:test";

import { buildEtsyStoreCapacitySummary, ETSY_STORE_LIMIT } from "./etsy-store-capacity.ts";

test("buildEtsyStoreCapacitySummary counts existing Etsy rows plus unsynced Gelato Etsy seeds", () => {
  const summary = buildEtsyStoreCapacitySummary({
    storeConnections: [
      {
        id: "gelato-1",
        provider: "gelato",
        credential_key: "gelato-key",
        provider_store_id: "gel-store-1",
        label: "Poster Shop 1",
        storefront_type: "etsy",
        storefront_display_name: "Etsy",
        etsy_shop_id: "111",
        status: "active",
        raw_data_json: null,
        last_sync_at: null,
        order_sync_last_success_at: null,
        created_at: null,
        updated_at: null
      },
      {
        id: "printify-1",
        provider: "printify",
        credential_key: "printify-key",
        provider_store_id: "pf-store-1",
        label: "Printify Shop",
        storefront_type: "etsy",
        storefront_display_name: "Etsy",
        etsy_shop_id: "222",
        status: "active",
        raw_data_json: null,
        last_sync_at: null,
        order_sync_last_success_at: null,
        created_at: null,
        updated_at: null
      },
      {
        id: "gelato-2",
        provider: "gelato",
        credential_key: "gelato-key",
        provider_store_id: "gel-store-9",
        label: "Shopify Row",
        storefront_type: "shopify",
        storefront_display_name: "Shopify",
        etsy_shop_id: null,
        status: "active",
        raw_data_json: null,
        last_sync_at: null,
        order_sync_last_success_at: null,
        created_at: null,
        updated_at: null
      }
    ],
    gelatoCredentials: [
      {
        credential_key: "gelato-key",
        credential_display_name: "Poster key",
        credential_masked_value: "gel...",
        configured_keys: ["api_key"],
        missing_keys: [],
        manual_store_seed_count: 2,
        manual_store_seeds: [
          {
            provider_store_id: "gel-store-1",
            storefront_type: "etsy",
            storefront_display_name: "Etsy",
            label: "Poster Shop 1",
            etsy_shop_id: "111"
          },
          {
            provider_store_id: "gel-store-2",
            storefront_type: "etsy",
            storefront_display_name: "Etsy",
            label: "Poster Shop 2",
            etsy_shop_id: null
          }
        ]
      }
    ]
  });

  assert.equal(summary.limit, ETSY_STORE_LIMIT);
  assert.equal(summary.current, 2);
  assert.equal(summary.projected, 3);
  assert.equal(summary.remaining, 2);
  assert.equal(summary.isAtLimit, false);
});

test("buildEtsyStoreCapacitySummary marks the organization at capacity once five Etsy slots are reserved", () => {
  const summary = buildEtsyStoreCapacitySummary({
    storeConnections: [],
    gelatoCredentials: [
      {
        credential_key: "gelato-key",
        credential_display_name: "Poster key",
        credential_masked_value: "gel...",
        configured_keys: ["api_key"],
        missing_keys: [],
        manual_store_seed_count: 5,
        manual_store_seeds: Array.from({ length: 5 }, (_, index) => ({
          provider_store_id: `gel-store-${index + 1}`,
          storefront_type: "etsy" as const,
          storefront_display_name: "Etsy",
          label: `Poster Shop ${index + 1}`,
          etsy_shop_id: null
        }))
      }
    ]
  });

  assert.equal(summary.current, 0);
  assert.equal(summary.projected, 5);
  assert.equal(summary.remaining, 0);
  assert.equal(summary.isAtLimit, true);
});
