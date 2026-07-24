import assert from "node:assert/strict";
import test from "node:test";

import { buildEtsyDiscoverySummaryChips } from "./etsy-discovery-display.ts";

test("buildEtsyDiscoverySummaryChips returns user-facing summary metrics", () => {
  const chips = buildEtsyDiscoverySummaryChips({
    etsyStoreConnectionCount: 5,
    lastSyncedAt: "2026-06-15T12:14:00Z",
    formatDateTime: () => "Jun 15, 8:14 PM"
  });

  assert.deepEqual(chips, [
    {
      label: "Connected stores",
      value: "5"
    },
    {
      label: "Last updated",
      value: "Jun 15, 8:14 PM"
    }
  ]);
  assert.equal(chips.some((chip) => chip.value.includes("Seller")), false);
});
