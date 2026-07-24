import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMarketPanelState,
  formatPublishSuccessRate,
  formatRevenueValue,
} from "./analytics-display.ts";

test("formatRevenueValue keeps single-currency totals readable", () => {
  assert.equal(
    formatRevenueValue({
      orders_last_7_days: 2,
      orders_last_30_days: 3,
      revenue_last_30_days: 108,
      revenue_currency: "USD",
      revenue_is_mixed_currency: false,
      new_drafts_last_30_days: 3,
      successful_publishes_last_30_days: 1,
    }),
    "$108.00"
  );
});

test("formatRevenueValue flags mixed-currency totals instead of pretending precision", () => {
  assert.equal(
    formatRevenueValue({
      orders_last_7_days: 2,
      orders_last_30_days: 3,
      revenue_last_30_days: 108,
      revenue_currency: null,
      revenue_is_mixed_currency: true,
      new_drafts_last_30_days: 3,
      successful_publishes_last_30_days: 1,
    }),
    "108.00 (mixed currencies)"
  );
});

test("formatPublishSuccessRate returns an em dash when there are no settled jobs", () => {
  assert.equal(
    formatPublishSuccessRate({
      published_product_count: 0,
      active_etsy_listing_count: 0,
      orders_last_30_days: 0,
      publish_success_rate_last_30_days: null,
      publish_success_count_last_30_days: 0,
      publish_settled_count_last_30_days: 0,
      listings_needing_attention_count: 0,
    }),
    "—"
  );
});

test("buildMarketPanelState surfaces the unavailable reason when Etsy metrics are blocked", () => {
  assert.deepEqual(
    buildMarketPanelState({
      available: false,
      unavailable_reason: "Main Shopify is not mapped to a discovered Etsy shop.",
      is_connected: true,
      connected_account_count: 1,
      supports_detailed_receipts: true,
      connected_shop_count: 0,
      mapped_store_count: 0,
      lifetime_sales_count: 0,
      active_listing_count: 0,
      digital_listing_count: 0,
      favorite_count: 0,
      review_count: 0,
      review_average: null,
      vacation_shop_count: 0,
      payments_onboarding_issue_count: 0,
    }),
    {
      title: "Market snapshot unavailable",
      description: "Main Shopify is not mapped to a discovered Etsy shop.",
    }
  );
});
