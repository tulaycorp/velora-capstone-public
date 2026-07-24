import assert from "node:assert/strict";
import test from "node:test";

import {
  formatBlueprintArtworkSummary,
  formatBlueprintVariantSummary,
  getBlueprintCardSubtitle,
  getBlueprintCardTitle
} from "./blueprint-display.ts";

function buildBlueprint(overrides: Record<string, unknown> = {}) {
  return {
    id: "blueprint-1",
    name: "Framed wall art",
    category: "Wall art",
    provider: "printify",
    provider_store_connection_id: "store-1",
    provider_store_label: "Peddlex",
    provider_storefront_type: "etsy",
    reference_type: "printify_product_url",
    reference_value: "https://printify.test/product",
    provider_resource_id: "resource-1",
    provider_display_name: "Abstract Canvas Template",
    product_code: "FWA-1",
    provider_snapshot_json: null,
    product_type: "Framed canvas",
    variant_count: 8,
    configuration_summary: "8 variants, 4 print placeholders, blueprint 241, provider 10",
    placement_config_json: null,
    base_cost_amount: 16.46,
    currency: "USD",
    base_title: "Framed wall art",
    base_description: "Warm neutral wall art.",
    base_tags: [],
    basic_design_info_json: null,
    draft_count: 0,
    status: "active",
    validated_at: null,
    created_at: null,
    updated_at: null,
    ...overrides
  };
}

const printifyBlueprint = buildBlueprint();

test("blueprint card title prefers the merchant-facing blueprint name", () => {
  assert.equal(getBlueprintCardTitle(printifyBlueprint), "Framed wall art");
  assert.equal(getBlueprintCardSubtitle(printifyBlueprint), "Abstract Canvas Template");
});

test("variant summary keeps only the merchant-facing count", () => {
  assert.equal(formatBlueprintVariantSummary(printifyBlueprint), "8 variants");
});

test("artwork summary removes provider ids and exposes only the placement count", () => {
  assert.equal(formatBlueprintArtworkSummary(printifyBlueprint), "4 artwork areas");
});

test("artwork summary humanizes a single saved placement name", () => {
  assert.equal(
    formatBlueprintArtworkSummary({
      ...buildBlueprint({
        id: "blueprint-2",
        name: "Poster blueprint",
        provider: "gelato",
        reference_type: "gelato_template_id",
        reference_value: "template-1",
        provider_resource_id: "template-1",
        provider_storefront_type: "shopify",
        provider_display_name: "Gelato Poster Template",
        product_type: "Poster",
        variant_count: 1,
        configuration_summary: "1 variants, placeholders: ImageFront",
        placement_config_json: {
          design_placeholder_name: "ImageFront",
          design_placeholder_names: ["ImageFront"]
        }
      })
    }),
    "Front"
  );
});
