import { createServer } from "node:http";

const PORT = Number(process.env.VELORA_E2E_BACKEND_PORT ?? 4011);
const NOW = "2026-07-17T08:00:00Z";
const productState = new Map();
const aiGenerationAttempts = new Map();

const providers = [
  {
    id: "printify",
    name: "Printify",
    status: "connected",
    connected_stores: 1,
    credentials_configured: true,
    required_keys: ["api_token"],
    available_storefronts: ["etsy"],
    last_sync_at: NOW
  },
  {
    id: "gelato",
    name: "Gelato",
    status: "disconnected",
    connected_stores: 0,
    credentials_configured: false,
    required_keys: ["api_key"],
    available_storefronts: ["etsy"],
    last_sync_at: null
  }
];

const storeConnections = [
  {
    id: "store-1",
    provider: "printify",
    credential_key: "default",
    provider_store_id: "e2e-store",
    label: "E2E Print Shop",
    storefront_type: "etsy",
    storefront_display_name: "Etsy",
    etsy_shop_id: "e2e-shop",
    status: "active",
    raw_data_json: null,
    last_sync_at: NOW,
    order_sync_last_success_at: NOW,
    created_at: NOW,
    updated_at: NOW
  }
];

const analytics = {
  generated_at: NOW,
  scope: {
    store_connection_id: null,
    label: "All stores",
    provider: null,
    storefront_type: null,
    is_all_stores: true
  },
  overview: {
    published_product_count: 4,
    active_etsy_listing_count: 3,
    orders_last_30_days: 2,
    publish_success_rate_last_30_days: 100,
    publish_success_count_last_30_days: 1,
    publish_settled_count_last_30_days: 1,
    listings_needing_attention_count: 0
  },
  catalog_health: {
    status_counts: {
      draft_count: 1,
      ready_count: 1,
      published_count: 4,
      failed_publish_count: 0
    },
    issue_counts: {
      missing_description_count: 0,
      low_tag_count_count: 0,
      missing_retail_price_count: 0,
      missing_sku_count: 0,
      zero_mockups_count: 0
    },
    needs_attention: []
  },
  workflow_health: {
    queued_job_count: 0,
    in_progress_job_count: 0,
    failed_job_count_last_30_days: 0,
    average_publish_duration_seconds: 5,
    latest_failure: null,
    latest_publish_activity_at: NOW,
    latest_etsy_fetch_at: NOW
  },
  recent_activity: {
    orders_last_7_days: 1,
    orders_last_30_days: 2,
    revenue_last_30_days: 80,
    revenue_currency: "USD",
    revenue_is_mixed_currency: false,
    new_drafts_last_30_days: 1,
    successful_publishes_last_30_days: 1
  },
  etsy_snapshot: {
    available: false,
    unavailable_reason: "Etsy market data is not included in this fixture.",
    is_connected: false,
    connected_account_count: 0,
    supports_detailed_receipts: false,
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
    freshness: "missing",
    refresh_status: "missing",
    fetched_at: null,
    expires_at: null,
    last_refresh_attempted_at: null
  },
  store_rollup: [],
  warnings: []
};

const businessAnalytics = {
  generated_at: NOW,
  scope: {
    store_connection_id: "store-1",
    label: "E2E Print Shop",
    provider: "printify",
    storefront_type: "etsy",
    is_all_stores: false
  },
  date_range: {
    preset: "30d",
    start: "2026-06-18T00:00:00Z",
    end: "2026-07-18T00:00:00Z",
    comparison_start: "2026-05-19T00:00:00Z",
    comparison_end: "2026-06-18T00:00:00Z"
  },
  currency: "PHP",
  timezone: "Asia/Manila",
  trend_granularity: "day",
  summary: {
    revenue: { amount: 128450, currency: "PHP", coverage_percent: 100 },
    expenses: { amount: 31800, currency: "PHP", coverage_percent: 100 },
    gross_profit: { amount: 78400, currency: "PHP", coverage_percent: 92 },
    net_profit: { amount: 46600, currency: "PHP", coverage_percent: 92 },
    gross_margin_percent: 61.0,
    net_margin_percent: 36.3,
    order_count: 84,
    unit_count: 97,
    previous_revenue: 109800,
    previous_order_count: 73,
    unmatched_line_count: 1
  },
  trend: Array.from({ length: 12 }, (_, index) => ({
    period: `2026-07-${String(index + 1).padStart(2, "0")}`,
    revenue: 7200 + index * 620,
    expenses: 1900 + index * 90,
    gross_profit: 4400 + index * 400,
    net_profit: 2600 + index * 280,
    orders: 4 + (index % 5),
    comparison_revenue: 6500 + index * 510,
    comparison_orders: 3 + (index % 4)
  })),
  products: [
    {
      product_id: "product-1",
      title: "Coastal Wildflower Gallery Print",
      store_connection_id: "store-1",
      store_label: "E2E Print Shop",
      status: "published",
      active_days: 90,
      units: 42,
      revenue: 68400,
      gross_profit: 42100,
      net_profit: 35800,
      margin_percent: 52.3,
      seo_score: 88,
      seo_issues: ["Expand description"],
      profitability_coverage_percent: 100
    },
    {
      product_id: "product-2",
      title: "Midnight Botanical Canvas",
      store_connection_id: "store-1",
      store_label: "E2E Print Shop",
      status: "published",
      active_days: 18,
      units: 16,
      revenue: 29100,
      gross_profit: null,
      net_profit: null,
      margin_percent: null,
      seo_score: 61,
      seo_issues: ["Use all 13 tags", "Add listing images"],
      profitability_coverage_percent: 0
    }
  ],
  stores: [
    {
      store_connection_id: "store-1",
      store_label: "E2E Print Shop",
      provider: "printify",
      storefront_type: "etsy",
      order_count: 84,
      units: 97,
      revenue: 128450,
      expenses: 31800,
      net_profit: 46600,
      margin_percent: 36.3,
      unmatched_line_count: 1
    },
    {
      store_connection_id: "store-2",
      store_label: "Peddlex -> shopify",
      provider: "printify",
      storefront_type: "shopify",
      order_count: 12,
      units: 14,
      revenue: 18400,
      expenses: 4200,
      net_profit: 8800,
      margin_percent: 47.8,
      unmatched_line_count: 0
    },
    {
      store_connection_id: "store-3",
      store_label: "Craftarriane -> etsy",
      provider: "gelato",
      storefront_type: "etsy",
      order_count: 9,
      units: 10,
      revenue: 13200,
      expenses: 3600,
      net_profit: 5100,
      margin_percent: 38.6,
      unmatched_line_count: 0
    }
  ],
  expenses: [
    {
      id: "expense-1",
      incurred_on: "2026-07-10T00:00:00Z",
      category: "advertising",
      amount: 12500,
      currency: "PHP",
      note: "Marketplace campaign",
      source: "manual",
      provider_store_connection_id: "store-1",
      store_label: "E2E Print Shop",
      product_id: null,
      product_title: null,
      created_at: NOW
    }
  ],
  seo: [
    {
      product_id: "product-2",
      title: "Midnight Botanical Canvas",
      store_label: "E2E Print Shop",
      status: "published",
      score: 61,
      issues: ["Use all 13 tags", "Add listing images"],
      title_length: 27,
      tag_count: 8,
      has_description: true,
      has_mockups: false,
      actual_search_metrics_available: false
    },
    {
      product_id: "product-1",
      title: "Coastal Wildflower Gallery Print",
      store_label: "E2E Print Shop",
      status: "published",
      score: 88,
      issues: ["Expand description"],
      title_length: 33,
      tag_count: 13,
      has_description: true,
      has_mockups: true,
      actual_search_metrics_available: false
    }
  ],
  unmatched_lines: [
    {
      id: "line-1",
      order_id: "order-1",
      order_display_id: "#1042",
      ordered_at: NOW,
      title: "Botanical Canvas / 16x20",
      sku: "BOT-1620",
      external_listing_id: "listing-2",
      quantity: 1,
      revenue_amount: 3400,
      currency: "PHP",
      store_connection_id: "store-1",
      store_label: "E2E Print Shop"
    }
  ],
  capabilities: {
    etsy_connected: true,
    detailed_marketplace_finance: false,
    authorization_upgrade_required: true,
    actual_search_metrics_available: false,
    unavailable_metrics: [
      "Etsy impressions",
      "Etsy click-through rate",
      "Etsy search terms",
      "Authoritative keyword rank"
    ]
  },
  warnings: []
};

const sessionContext = {
  auth_mode: "local",
  onboarding_status: "approved",
  user: {
    id: "e2e-user",
    email: "seller@example.com",
    first_name: "Test",
    last_name: "Seller",
    image_url: null,
    display_name: "Test Seller"
  },
  organization: {
    id: "e2e-org",
    name: "E2E Workspace",
    join_code: "E2E-CODE",
    admin_user_id: "e2e-user",
    admin_name: "Test Seller"
  },
  membership: { role: "admin" },
  pending_join_request: null,
  admin_pending_request_count: 0
};

const blueprint = {
  id: "blueprint-1",
  name: "Validated Canvas",
  category: "Wall Art",
  provider: "printify",
  provider_store_connection_id: "store-1",
  provider_store_label: "E2E Print Shop",
  provider_storefront_type: "etsy",
  reference_type: "printify_product_url",
  reference_value: "https://printify.example/products/canvas",
  provider_resource_id: "canvas-template",
  provider_display_name: "Canvas",
  product_code: "canvas",
  placement_config_json: {},
  provider_snapshot_json: { variant_ids: [101] },
  product_type: "Canvas",
  configuration_summary: "16 × 20 in",
  variant_count: 1,
  base_cost_amount: 12,
  currency: "USD",
  base_title: "Canvas",
  base_description: "Canvas description",
  base_tags: ["canvas"],
  basic_design_info_json: {},
  draft_count: 4,
  status: "validated",
  validated_at: NOW,
  created_at: NOW,
  updated_at: NOW
};

function productFixture(id) {
  if (productState.has(id)) {
    return productState.get(id);
  }
  const incomplete = id === "incomplete-product";
  const existingEtsyListing = id === "published-edit-product";
  const imageCount = incomplete ? 0 : 1;
  return {
    id,
    name: "Architecture Review Canvas",
    product_type: "Canvas",
    provider: "printify",
    provider_store_connection_id: "store-1",
    provider_store_label: "E2E Print Shop",
    provider_storefront_type: "etsy",
    status: existingEtsyListing ? "published" : "ready",
    publishing_status: "ready",
    validation_status: "validated",
    retail_price: 39.99,
    cost_amount: 12,
    margin: 27.99,
    currency: "USD",
    blueprint_id: blueprint.id,
    design_asset_id: "design-1",
    provider_product_id: existingEtsyListing ? "provider-product-1" : null,
    external_listing_id: existingEtsyListing ? "123456789" : null,
    provider_product_url: existingEtsyListing
      ? "https://www.etsy.com/your/shops/me/listing-editor/edit/123456789"
      : null,
    provider_fulfillment_url: null,
    provider_status: null,
    title: "Architecture Review Canvas",
    description: "A saved marketplace description.",
    tags: ["canvas"],
    sku: "E2E-1",
    revision: 7,
    design_description: "Private saved artwork context.",
    seo_title: null,
    seo_description: null,
    seo_keywords: [],
    last_ai_generation_id: null,
    mockup_count: imageCount,
    design_asset: {
      id: "design-1",
      file_name: "design.png",
      content_type: "image/png",
      size_bytes: 100,
      storage_key: "e2e/design.png",
      public_url: "https://images.example/design.png",
      checksum: "design-checksum",
      created_at: NOW,
      updated_at: NOW
    },
    mockups: imageCount
      ? [{
          id: "mockup-1",
          provider_product_draft_id: id,
          file_name: "mockup.png",
          content_type: "image/png",
          size_bytes: 100,
          storage_key: "e2e/mockup.png",
          public_url: "https://images.example/mockup.png",
          checksum: "mockup-checksum",
          position: 0,
          created_at: NOW,
          updated_at: NOW
        }]
      : [],
    last_provider_sync_at: null,
    created_at: NOW,
    updated_at: NOW
  };
}

const aiOutput = {
  title: "Vel Generated Botanical Canvas Title",
  description: "Vel generated description that remains a suggestion until review and apply.",
  tags: ["botanical canvas", "garden wall art"],
  seo_title: "Botanical Canvas Wall Art for Calm Modern Rooms",
  seo_description: "Discover botanical canvas wall art with a calm modern garden composition for living rooms, studios, bedrooms, and thoughtful gifts.",
  seo_keywords: ["botanical canvas", "garden wall art", "modern room decor", "nature artwork", "calm home style"],
  attributes: { product_type: "Canvas" },
  warnings: ["Verify material and dimensions before publishing."]
};

function aiGeneration(productId, output = aiOutput) {
  return {
    id: `ai-generation-${productId}`,
    product_id: productId,
    source_product_revision: productFixture(productId).revision,
    status: "completed",
    output,
    warnings: output.warnings,
    error_code: null,
    error_message: null,
    created_at: NOW,
    completed_at: NOW,
    accepted_at: null
  };
}

function publishingJob(productId, status = "queued") {
  const product = productFixture(productId);
  return {
    id: `job-${productId}`,
    product_id: productId,
    provider: "printify",
    provider_store_connection_id: "store-1",
    status,
    retry_count: 0,
    operation: product.external_listing_id ? "update" : "create",
    product_revision: product.revision,
    provider_product_id: status === "succeeded" ? "provider-product-1" : null,
    error_message: null,
    blueprint_id: blueprint.id,
    pod_product_id: null,
    raw_result_json: null,
    started_at: status === "succeeded" ? NOW : null,
    completed_at: status === "succeeded" ? NOW : null,
    created_at: NOW,
    updated_at: NOW
  };
}

function sendJson(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(payload));
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : null;
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${PORT}`);
  const productMatch = url.pathname.match(/^\/products\/([^/]+)$/);
  const publishMatch = url.pathname.match(/^\/products\/([^/]+)\/publish$/);
  const jobMatch = url.pathname.match(/^\/publishing-jobs\/([^/]+)$/);
  const aiGenerateMatch = url.pathname.match(/^\/products\/([^/]+)\/ai-generations$/);
  const aiApplyMatch = url.pathname.match(/^\/products\/([^/]+)\/ai-generations\/([^/]+)\/apply$/);

  if (request.method === "GET" && url.pathname === "/session-context") {
    return sendJson(response, 200, sessionContext);
  }
  if (request.method === "GET" && url.pathname === "/pod-providers") {
    return sendJson(response, 200, providers);
  }
  if (request.method === "GET" && url.pathname === "/provider-store-connections") {
    return sendJson(response, 200, storeConnections);
  }
  if (request.method === "GET" && url.pathname === "/analytics") {
    return sendJson(response, 200, analytics);
  }
  if (request.method === "GET" && url.pathname === "/analytics/business") {
    return sendJson(response, 200, {
      ...businessAnalytics,
      date_range: {
        ...businessAnalytics.date_range,
        preset: url.searchParams.get("preset") ?? "30d"
      },
      currency: url.searchParams.get("currency") ?? "PHP",
      timezone: url.searchParams.get("timezone") ?? "Asia/Manila"
    });
  }
  if (request.method === "GET" && url.pathname === "/analytics/business/details") {
    const resource = url.searchParams.get("resource") ?? "products";
    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "25");
    let items =
      resource === "unmatched"
        ? businessAnalytics.unmatched_lines
        : businessAnalytics[resource] ?? [];
    if (resource === "expenses") {
      items = Array.from({ length: 52 }, (_, index) => ({
        ...businessAnalytics.expenses[0],
        id: `expense-${index + 1}`,
        note: index === 0 ? "Marketplace campaign" : `Paged expense ${index + 1}`,
        incurred_on: `2026-07-${String(23 - (index % 20)).padStart(2, "0")}T00:00:00Z`
      }));
    }
    if (resource === "products") {
      const measure = url.searchParams.get("product_measure") ?? "revenue";
      items = [...items].sort(
        (left, right) =>
          (right[measure] ?? Number.NEGATIVE_INFINITY) -
            (left[measure] ?? Number.NEGATIVE_INFINITY) ||
          left.title.localeCompare(right.title)
      );
    }
    const total = items.length;
    const start = (page - 1) * pageSize;
    return sendJson(response, 200, {
      resource,
      items: items.slice(start, start + pageSize),
      page,
      page_size: pageSize,
      total,
      total_pages: total ? Math.ceil(total / pageSize) : 0
    });
  }
  if (request.method === "PATCH" && url.pathname === "/analytics/preferences") {
    const payload = await readJson(request);
    return sendJson(response, 200, {
      reporting_currency: payload?.reporting_currency ?? "PHP",
      reporting_timezone: payload?.reporting_timezone ?? "Asia/Manila"
    });
  }
  if (request.method === "POST" && url.pathname === "/analytics/expenses") {
    const payload = await readJson(request);
    return sendJson(response, 201, {
      id: "expense-new",
      ...payload,
      note: payload?.note ?? null,
      source: "manual",
      provider_store_connection_id: payload?.provider_store_connection_id ?? null,
      store_label: "E2E Print Shop",
      product_id: payload?.product_id ?? null,
      product_title: null,
      created_at: NOW
    });
  }
  if (
    request.method === "POST" &&
    /^\/analytics\/unmatched\/[^/]+\/map$/.test(url.pathname)
  ) {
    await readJson(request);
    response.writeHead(204);
    return response.end();
  }
  if (
    request.method === "DELETE" &&
    /^\/analytics\/expenses\/[^/]+$/.test(url.pathname)
  ) {
    response.writeHead(204);
    return response.end();
  }
  if (request.method === "GET" && url.pathname === "/blueprints") {
    return sendJson(response, 200, [blueprint]);
  }
  if (request.method === "POST" && url.pathname === "/design-assets") {
    for await (const _chunk of request) {
      // Drain the multipart fixture without retaining uploaded bytes.
    }
    return sendJson(response, 201, {
      id: "studio-design-1",
      file_name: "studio-design.png",
      content_type: "image/png",
      size_bytes: 68,
      storage_key: "e2e/studio-design.png",
      public_url: "https://images.example/studio-design.png",
      checksum: "studio-design-checksum",
      created_at: NOW,
      updated_at: NOW
    });
  }
  if (request.method === "POST" && url.pathname === "/products") {
    const payload = await readJson(request);
    const product = {
      ...productFixture("studio-ai-product"),
      blueprint_id: payload.blueprint_id,
      design_asset_id: payload.design_asset_id,
      title: payload.title,
      description: payload.description,
      tags: payload.tags,
      retail_price: payload.retail_price,
      currency: payload.currency,
      sku: payload.sku,
      design_description: payload.design_description,
      revision: 1,
      design_asset: {
        ...productFixture("studio-ai-product").design_asset,
        id: payload.design_asset_id,
        file_name: "studio-design.png"
      }
    };
    productState.set(product.id, product);
    return sendJson(response, 201, product);
  }
  if (request.method === "GET" && url.pathname === "/publishing-jobs") {
    const productId = url.searchParams.get("product_id");
    return sendJson(
      response,
      200,
      productId === "published-edit-product" ? [publishingJob(productId, "succeeded")] : []
    );
  }
  if (request.method === "GET" && url.pathname === "/ai/capabilities") {
    return sendJson(response, 200, {
      enabled: true,
      model: "e2e-mocked-model",
      supported_fields: ["title", "description", "tags", "seo_title", "seo_description", "seo_keywords"]
    });
  }
  if (request.method === "POST" && aiGenerateMatch) {
    const productId = aiGenerateMatch[1];
    await readJson(request);
    const attempt = (aiGenerationAttempts.get(productId) ?? 0) + 1;
    aiGenerationAttempts.set(productId, attempt);
    if (productId === "ai-rate-limit-product" && attempt === 1) {
      return sendJson(response, 429, {
        detail: "AI generation limit reached. Try again later."
      });
    }
    return sendJson(response, 200, aiGeneration(productId));
  }
  if (request.method === "POST" && aiApplyMatch) {
    const productId = aiApplyMatch[1];
    const payload = await readJson(request);
    if (productId === "ai-stale-product") {
      return sendJson(response, 409, {
        detail: "This product changed. Refresh and regenerate the listing."
      });
    }
    const current = productFixture(productId);
    const updated = {
      ...current,
      ...Object.fromEntries(
        Object.entries(payload ?? {}).filter(([key]) => key !== "expected_product_revision")
      ),
      revision: current.revision + 1,
      last_ai_generation_id: aiApplyMatch[2]
    };
    productState.set(productId, updated);
    return sendJson(response, 200, {
      product: updated,
      generation: {
        ...aiGeneration(productId),
        id: aiApplyMatch[2],
        status: "accepted",
        accepted_at: NOW
      }
    });
  }
  if (request.method === "GET" && productMatch) {
    return sendJson(response, 200, productFixture(productMatch[1]));
  }
  if (request.method === "PATCH" && productMatch) {
    const productId = productMatch[1];
    const current = productFixture(productId);
    const payload = await readJson(request);
    const updated = {
      ...current,
      ...Object.fromEntries(
        Object.entries(payload ?? {}).filter(([key]) => !["expected_revision", "status"].includes(key))
      ),
      revision: current.revision + 1,
      updated_at: NOW
    };
    productState.set(productId, updated);
    return sendJson(response, 200, updated);
  }
  if (request.method === "GET" && jobMatch) {
    const productId = jobMatch[1].replace(/^job-/, "");
    return sendJson(response, 200, publishingJob(productId, "succeeded"));
  }
  if (request.method === "POST" && publishMatch) {
    const productId = publishMatch[1];
    const payload = await readJson(request);
    if (payload?.expected_revision !== productFixture(productId).revision) {
      return sendJson(response, 400, { detail: "The exact saved revision is required." });
    }
    if (productId === "stale-product") {
      return sendJson(response, 409, {
        detail: {
          code: "stale_product_revision",
          message: "This product changed after the page loaded. Refresh it before sending."
        }
      });
    }
    if (productId === "server-reject-product") {
      return sendJson(response, 422, {
        detail: {
          code: "publish_not_ready",
          message: "This product is not ready to send.",
          fields: [{
            field: "mockups",
            code: "required",
            message: "Upload at least one saved product image."
          }]
        }
      });
    }
    if (productId === "ready-product") {
      const current = productFixture(productId);
      productState.set(productId, {
        ...current,
        status: "published",
        publishing_status: "succeeded",
        provider_product_id: "provider-product-1",
        external_listing_id: "123456789",
        provider_product_url: "https://www.etsy.com/your/shops/me/listing-editor/edit/123456789"
      });
    }
    return sendJson(response, 200, { job: publishingJob(productId) });
  }

  return sendJson(response, 404, { detail: `No E2E fixture for ${request.method} ${url.pathname}` });
});

server.listen(PORT, "127.0.0.1");

function closeServer() {
  server.close(() => process.exit(0));
}

process.on("SIGINT", closeServer);
process.on("SIGTERM", closeServer);
