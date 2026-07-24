import assert from "node:assert/strict";
import test from "node:test";

import {
  buildOrdersQuery,
  buildOrdersQueryCacheKey,
  ORDERS_PAGE_SIZE
} from "./orders-query.ts";

test("orders query applies local filters in all-store scope", () => {
  const query = buildOrdersQuery({
    fulfillmentStatus: "fulfilled",
    page: 2,
    provider: "printify",
    selectedStoreId: "all",
    storeConnectionId: "store-1"
  });

  assert.deepEqual(query, {
    page: 2,
    pageSize: ORDERS_PAGE_SIZE,
    storeConnectionId: "store-1",
    provider: "printify",
    fulfillmentStatus: "fulfilled"
  });
  assert.equal(
    buildOrdersQueryCacheKey(query),
    "page=2&pageSize=15&store=store-1&provider=printify&status=fulfilled"
  );
});

test("orders query lets the shared store scope override local filters", () => {
  assert.deepEqual(
    buildOrdersQuery({
      fulfillmentStatus: "fulfilled",
      page: 1,
      provider: "gelato",
      selectedStoreId: "shared-store",
      storeConnectionId: "local-store"
    }),
    {
      page: 1,
      pageSize: ORDERS_PAGE_SIZE,
      storeConnectionId: "shared-store",
      provider: undefined,
      fulfillmentStatus: undefined
    }
  );
});
