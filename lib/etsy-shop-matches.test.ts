import assert from "node:assert/strict";
import test from "node:test";

import { resolveEtsyShopMatchedConnections } from "./etsy-shop-matches.ts";

const storeConnections = [
  {
    id: "gelato-1",
    provider: "gelato",
    label: "Peddlex",
  },
  {
    id: "printify-1",
    provider: "printify",
    label: "Peddlex -> etsy",
  }
] satisfies Parameters<typeof resolveEtsyShopMatchedConnections>[1];

test("resolveEtsyShopMatchedConnections returns provider and store labels for each matched row", () => {
  const shop = {
    shop_id: "40888999",
    shop_name: "Peddlex",
    shop_url: "https://www.etsy.com/shop/Peddlex",
    matched_connection_id: "gelato-1",
    matched_connection_label: "Peddlex",
    matched_connection_ids: ["gelato-1", "printify-1"],
    matched_connection_labels: ["Peddlex", "Peddlex -> etsy"]
  };

  assert.deepEqual(resolveEtsyShopMatchedConnections(shop, storeConnections), [
    {
      id: "gelato-1",
      provider: "Gelato",
      storeLabel: "Peddlex"
    },
    {
      id: "printify-1",
      provider: "Printify",
      storeLabel: "Peddlex"
    }
  ]);
});

test("resolveEtsyShopMatchedConnections falls back to stored labels when a connection row is unavailable", () => {
  const shop = {
    shop_id: "40888999",
    shop_name: "Peddlex",
    shop_url: "https://www.etsy.com/shop/Peddlex",
    matched_connection_id: null,
    matched_connection_label: null,
    matched_connection_ids: [],
    matched_connection_labels: ["Archived storefront -> etsy"]
  };

  assert.deepEqual(resolveEtsyShopMatchedConnections(shop, []), [
    {
      id: "Archived storefront -> etsy",
      provider: "Connected store",
      storeLabel: "Archived storefront"
    }
  ]);
});
