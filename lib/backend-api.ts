import { humanizeApiErrorDetail } from "@/lib/ux-copy";
import { cleanStoreDisplayName } from "@/lib/store-display";

export type PodProviderKey = "printify" | "gelato";
export type StorefrontType = "etsy" | "shopify" | "unknown";
export type OrganizationRole = "admin" | "member";
export type OnboardingStatus = "approved" | "needs_organization" | "pending";
export type JoinRequestStatus = "pending" | "approved" | "rejected";

export type SessionContextUser = {
  id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  image_url: string | null;
  display_name: string;
};

export type SessionContextOrganization = {
  id: string;
  name: string;
  join_code: string | null;
  admin_user_id: string | null;
  admin_name: string | null;
};

export type SessionContextMembership = {
  role: OrganizationRole;
};

export type OrganizationJoinRequestSummary = {
  id: string;
  organization_id: string;
  organization_name: string;
  requested_by_user_id: string;
  requested_by_name: string;
  requested_by_email: string | null;
  status: JoinRequestStatus;
  created_at: string | null;
  reviewed_at: string | null;
};

export type OrganizationMemberSummary = {
  user_id: string;
  display_name: string;
  email: string | null;
  role: OrganizationRole;
  joined_at: string | null;
  is_current_user: boolean;
  is_removable: boolean;
};

export type SessionContext = {
  auth_mode: "local" | "clerk";
  onboarding_status: OnboardingStatus;
  user: SessionContextUser;
  organization: SessionContextOrganization | null;
  membership: SessionContextMembership | null;
  pending_join_request: OrganizationJoinRequestSummary | null;
  admin_pending_request_count: number;
};

export type PodProvider = {
  id: PodProviderKey;
  name: string;
  status: string;
  connected_stores: number;
  credentials_configured: boolean;
  required_keys: string[];
  available_storefronts: StorefrontType[];
  last_sync_at: string | null;
};

export type ProviderStoreConnection = {
  id: string;
  provider: PodProviderKey;
  credential_key: string;
  provider_store_id: string;
  label: string;
  storefront_type: StorefrontType;
  storefront_display_name: string;
  etsy_shop_id: string | null;
  status: string;
  raw_data_json: Record<string, unknown> | null;
  last_sync_at: string | null;
  order_sync_last_success_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ProviderCredentialEntry = {
  credential_key: string;
  credential_display_name: string | null;
  credential_masked_value: string | null;
  configured_keys: string[];
  missing_keys: string[];
  manual_store_seed_count: number;
  manual_store_seeds: ManualStoreSeed[];
};

export type ProviderCredentialStatus = {
  provider: PodProviderKey;
  is_configured: boolean;
  required_keys: string[];
  credential_count: number;
  credentials: ProviderCredentialEntry[];
};

export type EtsyOAuthStartResponse = {
  authorization_url: string;
  state: string;
  redirect_uri: string;
  expires_at: string;
  scopes: string[];
};

export type EtsyOAuthCallbackInput = {
  code: string;
  state: string;
};

export type EtsyShopSummary = {
  shop_id: string;
  shop_name: string;
  shop_url: string | null;
  matched_connection_id: string | null;
  matched_connection_label: string | null;
  matched_connection_ids: string[];
  matched_connection_labels: string[];
};

export type EtsyConnectedAccountSummary = {
  credential_key: string;
  seller_user_id: string;
  shop_id: string | null;
  shop_name: string | null;
  shop_url: string | null;
  last_synced_at: string | null;
  scopes: string[];
};

export type EtsyConnectionStatus = {
  is_connected: boolean;
  seller_user_id: string | null;
  last_synced_at: string | null;
  scopes: string[];
  connected_account_count: number;
  connected_accounts: EtsyConnectedAccountSummary[];
  connected_shops: EtsyShopSummary[];
  matched_connection_count: number;
  unmapped_connection_count: number;
};

export type AnalyticsScope = {
  store_connection_id: string | null;
  label: string;
  provider: PodProviderKey | null;
  storefront_type: StorefrontType | null;
  is_all_stores: boolean;
};

export type AnalyticsOverview = {
  published_product_count: number;
  active_etsy_listing_count: number;
  orders_last_30_days: number;
  publish_success_rate_last_30_days: number | null;
  publish_success_count_last_30_days: number;
  publish_settled_count_last_30_days: number;
  listings_needing_attention_count: number;
};

export type CatalogStatusCounts = {
  draft_count: number;
  ready_count: number;
  published_count: number;
  failed_publish_count: number;
};

export type CatalogIssueCounts = {
  missing_description_count: number;
  low_tag_count_count: number;
  missing_retail_price_count: number;
  missing_sku_count: number;
  zero_mockups_count: number;
};

export type CatalogNeedsAttentionItem = {
  product_id: string;
  title: string;
  provider_store_label: string;
  status: string;
  publishing_status: string;
  issue_count: number;
  issues: string[];
  updated_at: string | null;
};

export type CatalogHealth = {
  status_counts: CatalogStatusCounts;
  issue_counts: CatalogIssueCounts;
  needs_attention: CatalogNeedsAttentionItem[];
};

export type WorkflowLatestFailure = {
  product_id: string;
  title: string;
  provider_store_label: string;
  failed_at: string | null;
  error_message: string | null;
};

export type WorkflowHealth = {
  queued_job_count: number;
  in_progress_job_count: number;
  failed_job_count_last_30_days: number;
  average_publish_duration_seconds: number | null;
  latest_failure: WorkflowLatestFailure | null;
  latest_publish_activity_at: string | null;
  latest_etsy_fetch_at: string | null;
};

export type RecentActivity = {
  orders_last_7_days: number;
  orders_last_30_days: number;
  revenue_last_30_days: number;
  revenue_currency: string | null;
  revenue_is_mixed_currency: boolean;
  new_drafts_last_30_days: number;
  successful_publishes_last_30_days: number;
};

export type EtsySnapshot = {
  available: boolean;
  unavailable_reason: string | null;
  is_connected: boolean;
  connected_account_count: number;
  supports_detailed_receipts: boolean;
  connected_shop_count: number;
  mapped_store_count: number;
  lifetime_sales_count: number;
  active_listing_count: number;
  digital_listing_count: number;
  favorite_count: number;
  review_count: number;
  review_average: number | null;
  vacation_shop_count: number;
  payments_onboarding_issue_count: number;
  freshness: "missing" | "fresh" | "stale";
  refresh_status: "missing" | "succeeded" | "failed";
  fetched_at: string | null;
  expires_at: string | null;
  last_refresh_attempted_at: string | null;
};

export type StoreRollupRow = {
  shop_id: string;
  shop_name: string;
  shop_url: string | null;
  currency_code: string | null;
  lifetime_sales_count: number;
  active_listing_count: number;
  digital_listing_count: number;
  favorite_count: number;
  review_count: number;
  review_average: number | null;
  is_vacation: boolean | null;
  has_payments_onboarding_issue: boolean;
  updated_at: string | null;
  last_synced_at: string | null;
  matched_connection_ids: string[];
  matched_connection_labels: string[];
};

export type WorkspaceAnalyticsResponse = {
  generated_at: string;
  scope: AnalyticsScope;
  overview: AnalyticsOverview;
  catalog_health: CatalogHealth;
  workflow_health: WorkflowHealth;
  recent_activity: RecentActivity;
  etsy_snapshot: EtsySnapshot;
  store_rollup: StoreRollupRow[];
  warnings: string[];
};

export type AnalyticsPreset =
  | "7d"
  | "30d"
  | "90d"
  | "this_month"
  | "last_month"
  | "this_year"
  | "all_time"
  | "custom";
export type ReportingCurrency = "PHP" | "USD" | "EUR" | "JPY";

export type AnalyticsMoneyMetric = {
  amount: number | null;
  currency: ReportingCurrency;
  coverage_percent: number;
};

export type AnalyticsTrendPoint = {
  period: string;
  revenue: number | null;
  expenses: number | null;
  gross_profit: number | null;
  net_profit: number | null;
  orders: number;
  comparison_revenue: number | null;
  comparison_orders: number | null;
};

export type ProductPerformanceRow = {
  product_id: string;
  title: string;
  store_connection_id: string;
  store_label: string;
  status: string;
  active_days: number;
  units: number;
  revenue: number | null;
  gross_profit: number | null;
  net_profit: number | null;
  margin_percent: number | null;
  seo_score: number;
  seo_issues: string[];
  profitability_coverage_percent: number;
};

export type StorePerformanceRow = {
  store_connection_id: string;
  store_label: string;
  provider: string;
  storefront_type: string;
  order_count: number;
  units: number;
  revenue: number | null;
  expenses: number | null;
  net_profit: number | null;
  margin_percent: number | null;
  unmatched_line_count: number;
};

export type ExpenseRecord = {
  id: string;
  incurred_on: string;
  category: string;
  amount: number;
  currency: string;
  note: string | null;
  source: string;
  provider_store_connection_id: string | null;
  store_label: string | null;
  product_id: string | null;
  product_title: string | null;
  created_at: string | null;
};

export type UnmatchedOrderLine = {
  id: string;
  order_id: string;
  order_display_id: string;
  ordered_at: string | null;
  title: string;
  sku: string | null;
  external_listing_id: string | null;
  quantity: number;
  revenue_amount: number | null;
  currency: string | null;
  store_connection_id: string;
  store_label: string;
};

export type SeoPerformanceRow = {
  product_id: string;
  title: string;
  store_label: string;
  status: string;
  score: number;
  issues: string[];
  title_length: number;
  tag_count: number;
  has_description: boolean;
  has_mockups: boolean;
  actual_search_metrics_available: boolean;
};

export type AnalyticsDetailResource = "products" | "expenses" | "seo" | "unmatched";

export type AnalyticsDetailPage<T> = {
  resource: AnalyticsDetailResource;
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export type BusinessAnalyticsResponse = {
  generated_at: string;
  scope: AnalyticsScope;
  date_range: {
    preset: AnalyticsPreset;
    start: string;
    end: string;
    comparison_start: string | null;
    comparison_end: string | null;
  };
  currency: ReportingCurrency;
  timezone: string;
  trend_granularity: "day" | "week" | "month";
  summary: {
    revenue: AnalyticsMoneyMetric;
    expenses: AnalyticsMoneyMetric;
    gross_profit: AnalyticsMoneyMetric;
    net_profit: AnalyticsMoneyMetric;
    gross_margin_percent: number | null;
    net_margin_percent: number | null;
    order_count: number;
    unit_count: number;
    previous_revenue: number | null;
    previous_order_count: number | null;
    unmatched_line_count: number;
  };
  trend: AnalyticsTrendPoint[];
  products: ProductPerformanceRow[];
  stores: StorePerformanceRow[];
  expenses: ExpenseRecord[];
  seo: SeoPerformanceRow[];
  unmatched_lines: UnmatchedOrderLine[];
  capabilities: {
    etsy_connected: boolean;
    detailed_marketplace_finance: boolean;
    authorization_upgrade_required: boolean;
    actual_search_metrics_available: boolean;
    unavailable_metrics: string[];
  };
  warnings: string[];
};

export type ExpenseInput = {
  incurred_on: string;
  category: string;
  amount: number;
  currency: ReportingCurrency;
  note?: string | null;
  provider_store_connection_id?: string | null;
  product_id?: string | null;
};

export type ManualStoreSeed = {
  provider_store_id: string;
  storefront_type: StorefrontType;
  storefront_display_name: string;
  label: string | null;
  etsy_shop_id: string | null;
};

export type Blueprint = {
  id: string;
  name: string;
  category: string;
  provider: PodProviderKey;
  provider_store_connection_id: string;
  provider_store_label: string;
  provider_storefront_type: StorefrontType;
  reference_type: string;
  reference_value: string;
  provider_resource_id: string | null;
  provider_display_name: string | null;
  product_code: string | null;
  placement_config_json: Record<string, unknown> | null;
  provider_snapshot_json: Record<string, unknown> | null;
  product_type: string | null;
  configuration_summary: string | null;
  variant_count: number;
  base_cost_amount: number | null;
  currency: string | null;
  base_title: string | null;
  base_description: string | null;
  base_tags: string[];
  basic_design_info_json: Record<string, unknown> | null;
  draft_count: number;
  status: string;
  validated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type DesignAsset = {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  storage_key: string;
  public_url: string | null;
  checksum: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type Mockup = {
  id: string;
  provider_product_draft_id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  storage_key: string;
  public_url: string | null;
  checksum: string | null;
  position: number;
  created_at: string | null;
  updated_at: string | null;
};

export type Product = {
  id: string;
  name: string;
  product_type: string;
  provider: PodProviderKey;
  provider_store_connection_id: string;
  provider_store_label: string;
  provider_storefront_type: StorefrontType;
  status: string;
  publishing_status: string;
  validation_status: string;
  retail_price: number | null;
  cost_amount: number | null;
  margin: number | null;
  currency: string | null;
  blueprint_id: string;
  design_asset_id: string;
  provider_product_id: string | null;
  external_listing_id: string | null;
  provider_product_url: string | null;
  provider_fulfillment_url: string | null;
  provider_status: string | null;
  title: string;
  description: string | null;
  tags: string[];
  sku: string | null;
  revision: number;
  design_description: string | null;
  seo_title: string | null;
  seo_description: string | null;
  seo_keywords: string[];
  last_ai_generation_id: string | null;
  mockup_count: number;
  design_asset: DesignAsset | null;
  mockups: Mockup[];
  last_provider_sync_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type PublishingJob = {
  id: string;
  product_id: string;
  provider: PodProviderKey;
  provider_store_connection_id: string;
  status: string;
  stage: string;
  retry_count: number;
  operation: "create" | "update";
  product_revision: number;
  provider_product_id: string | null;
  error_message: string | null;
  blueprint_id: string | null;
  pod_product_id: string | null;
  raw_result_json: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ProductStudioState = {
  steps: string[];
  selected_provider: PodProviderKey | null;
  selected_store_connection_ids: string[];
  requires_blueprint: boolean;
  blueprint_count: number;
  draft_count: number;
};

export type BlueprintCreateInput = {
  name: string;
  category: string;
  provider_store_connection_id: string;
  reference_type: string;
  reference_value: string;
  product_code?: string | null;
  placement_config_json?: Record<string, unknown> | null;
  base_title?: string | null;
  base_description?: string | null;
  base_tags?: string[];
  basic_design_info_json?: Record<string, unknown> | null;
  status?: string;
};

export type BlueprintUpdateInput = {
  name?: string | null;
  category?: string | null;
  product_code?: string | null;
  placement_config_json?: Record<string, unknown> | null;
  base_title?: string | null;
  base_description?: string | null;
  base_tags?: string[] | null;
  basic_design_info_json?: Record<string, unknown> | null;
  status?: string | null;
};

export type ProductCreateInput = {
  blueprint_id: string;
  design_asset_id: string;
  title?: string | null;
  description?: string | null;
  tags?: string[];
  retail_price?: number | null;
  currency?: string | null;
  sku?: string | null;
  design_description?: string | null;
};

export type ProductUpdateInput = {
  title?: string | null;
  description?: string | null;
  tags?: string[] | null;
  retail_price?: number | null;
  currency?: string | null;
  sku?: string | null;
  design_asset_id?: string | null;
  status?: string | null;
  validation_status?: string | null;
  design_description?: string | null;
  seo_title?: string | null;
  seo_description?: string | null;
  seo_keywords?: string[] | null;
  expected_revision?: number;
};

export type AICapabilities = { enabled: boolean; model: string | null; supported_fields: string[] };
export type AIGeneration = {
  id: string; product_id: string; source_product_revision: number; status: "pending" | "completed" | "failed" | "accepted";
  output: AIGenerationOutput | null; warnings: string[]; error_code: string | null; error_message: string | null;
  created_at: string | null; completed_at: string | null; accepted_at: string | null;
};
export type AIGenerationOutput = { title: string; description: string; tags: string[]; seo_title: string; seo_description: string; seo_keywords: string[]; attributes: Record<string, unknown>; warnings: string[] };
export type AIGenerationApplyInput = { expected_product_revision: number; title?: string; description?: string; tags?: string[]; seo_title?: string; seo_description?: string; seo_keywords?: string[] };

export type ProviderCredentialsUpsertInput = {
  credential_key?: string | null;
  credentials?: Record<string, string>;
  credential_display_name?: string | null;
  manual_store_seeds?: ManualStoreSeed[];
};

export type ProviderStoreConnectionUpdateInput = {
  etsy_shop_id?: string | null;
};

export type OrganizationCreateInput = {
  name: string;
};

export type OrganizationUpdateInput = {
  name: string;
};

export type BackendApiFieldError = {
  field: string;
  code: string;
  message: string;
};

export class BackendApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly fields: BackendApiFieldError[];

  constructor({
    message,
    status,
    code = null,
    fields = []
  }: {
    message: string;
    status: number;
    code?: string | null;
    fields?: BackendApiFieldError[];
  }) {
    super(message);
    this.name = "BackendApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export type OrganizationJoinRequestCreateInput = {
  join_code: string;
};

const DEFAULT_API_BASE_URL = "/api/backend";

export function getApiBaseUrl() {
  return DEFAULT_API_BASE_URL.replace(/\/$/, "");
}

export function providerLabel(provider: string) {
  if (provider === "printify") return "Printify";
  if (provider === "gelato") return "Gelato";
  if (provider === "etsy") return "Etsy";
  if (provider === "shopify") return "Shopify";
  return provider;
}

export function storefrontLabel(type: StorefrontType) {
  if (type === "etsy") {
    return "Etsy";
  }
  if (type === "shopify") {
    return "Shopify";
  }
  return "Unknown";
}

export function storefrontActionLabel(type: StorefrontType) {
  const label = storefrontLabel(type);
  return label === "Unknown" ? "storefront" : label;
}

export function formatProviderStoreLabel(
  connection:
    | Pick<ProviderStoreConnection, "provider" | "label" | "storefront_display_name">
    | Pick<Blueprint, "provider" | "provider_store_label">
    | Pick<Product, "provider" | "provider_store_label">
) {
  if ("provider_store_label" in connection) {
    return cleanStoreDisplayName(connection.provider_store_label);
  }
  return cleanStoreDisplayName(
    connection.label,
    connection.storefront_display_name || providerLabel(connection.provider)
  );
}

export function formatCurrency(amount: number | null, currency = "USD") {
  if (amount === null || Number.isNaN(amount)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2
  }).format(amount);
}

export function formatDateTime(value: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(date);
}

export function formatDate(value: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric"
  }).format(date);
}

export function isApprovedSession(sessionContext: SessionContext) {
  return sessionContext.onboarding_status === "approved" && !!sessionContext.organization && !!sessionContext.membership;
}

export function isAdminSession(sessionContext: SessionContext) {
  return sessionContext.membership?.role === "admin";
}

async function apiRequest<T>(path: string, init?: RequestInit) {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    cache: "no-store",
    ...init
  });
  if (!response.ok) {
    throw await extractApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function extractApiError(response: Response) {
  let text = "";
  try {
    text = await response.text();
  } catch {
    // Ignore read errors and fall back to response text.
  }

  try {
    const payload = JSON.parse(text) as {
      detail?: string | {
        code?: string;
        message?: string;
        fields?: BackendApiFieldError[];
      };
    };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return new BackendApiError({
        message: humanizeApiErrorDetail(payload.detail),
        status: response.status
      });
    }
    if (payload.detail && typeof payload.detail === "object") {
      const fields = Array.isArray(payload.detail.fields)
        ? payload.detail.fields.filter(
            (field): field is BackendApiFieldError =>
              Boolean(field)
              && typeof field.field === "string"
              && typeof field.code === "string"
              && typeof field.message === "string"
          )
        : [];
      const message = payload.detail.message
        || fields[0]?.message
        || (payload.detail.code === "stale_product_revision"
          ? "This product changed after the page loaded. Refresh it before sending."
          : "Something went wrong. Please try again.");
      return new BackendApiError({
        message: humanizeApiErrorDetail(message),
        status: response.status,
        code: payload.detail.code ?? null,
        fields
      });
    }
  } catch {
    // Ignore parse errors and fall back to response text.
  }

  return new BackendApiError({
    message: humanizeApiErrorDetail(text || `${response.status} ${response.statusText}`),
    status: response.status
  });
}

export async function fetchProviders() {
  return apiRequest<PodProvider[]>("/pod-providers");
}

export async function fetchSessionContext() {
  return apiRequest<SessionContext>("/session-context");
}

export async function createOrganization(payload: OrganizationCreateInput) {
  return apiRequest<{
    status: string;
    organization: SessionContextOrganization;
    membership: SessionContextMembership;
  }>("/organizations", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function updateOrganization(payload: OrganizationUpdateInput) {
  return apiRequest<{
    status: string;
    organization: SessionContextOrganization;
  }>("/organizations", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function createOrganizationJoinRequest(payload: OrganizationJoinRequestCreateInput) {
  return apiRequest<{ status: string; join_request: OrganizationJoinRequestSummary }>(
    "/organizations/join-requests",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    }
  );
}

export async function fetchOrganizationJoinRequests() {
  return apiRequest<{
    pending_request_count: number;
    join_requests: OrganizationJoinRequestSummary[];
  }>("/organizations/join-requests");
}

export async function fetchOrganizationMembers() {
  return apiRequest<{
    member_count: number;
    members: OrganizationMemberSummary[];
  }>("/organizations/members");
}

export async function approveOrganizationJoinRequest(joinRequestId: string) {
  return apiRequest<{ status: string; join_request: OrganizationJoinRequestSummary }>(
    `/organizations/join-requests/${joinRequestId}/approve`,
    {
      method: "POST"
    }
  );
}

export async function rejectOrganizationJoinRequest(joinRequestId: string) {
  return apiRequest<{ status: string; join_request: OrganizationJoinRequestSummary }>(
    `/organizations/join-requests/${joinRequestId}/reject`,
    {
      method: "POST"
    }
  );
}

export async function removeOrganizationMember(userId: string) {
  return apiRequest<{ status: string; member: OrganizationMemberSummary }>(
    `/organizations/members/${userId}/remove`,
    {
      method: "POST"
    }
  );
}

export async function leaveCurrentOrganization() {
  return apiRequest<{ status: string; session_context: SessionContext }>("/organizations/leave", {
    method: "POST"
  });
}

export async function fetchProviderCredentialStatus(provider: PodProviderKey) {
  return apiRequest<ProviderCredentialStatus>(`/pod-providers/${provider}/credentials/status`);
}

export async function fetchEtsyConnectionStatus() {
  return apiRequest<EtsyConnectionStatus>("/etsy/connection");
}

function buildAnalyticsPath(storeConnectionId?: string) {
  const trimmedStoreConnectionId = storeConnectionId?.trim();
  if (!trimmedStoreConnectionId || trimmedStoreConnectionId === "all") {
    return "/analytics";
  }
  return `/analytics?store_connection_id=${encodeURIComponent(trimmedStoreConnectionId)}`;
}

export async function fetchWorkspaceAnalytics(storeConnectionId?: string) {
  return apiRequest<WorkspaceAnalyticsResponse>(buildAnalyticsPath(storeConnectionId));
}

export async function fetchBusinessAnalytics(options: {
  storeConnectionId?: string;
  preset: AnalyticsPreset;
  currency: ReportingCurrency;
  timezone: string;
  start?: string;
  end?: string;
}) {
  const params = new URLSearchParams({
    preset: options.preset,
    currency: options.currency,
    timezone: options.timezone,
    include_details: "false"
  });
  if (options.storeConnectionId && options.storeConnectionId !== "all") {
    params.set("store_connection_id", options.storeConnectionId);
  }
  if (options.start) params.set("start", options.start);
  if (options.end) params.set("end", options.end);
  return apiRequest<BusinessAnalyticsResponse>(`/analytics/business?${params.toString()}`);
}

export async function fetchBusinessAnalyticsDetails<T>(options: {
  resource: AnalyticsDetailResource;
  storeConnectionId?: string;
  preset: AnalyticsPreset;
  currency: ReportingCurrency;
  timezone: string;
  page: number;
  pageSize: number;
  productMeasure?: "revenue" | "units" | "gross_profit" | "net_profit";
  start?: string;
  end?: string;
}) {
  const params = new URLSearchParams({
    resource: options.resource,
    preset: options.preset,
    currency: options.currency,
    timezone: options.timezone,
    page: String(options.page),
    page_size: String(options.pageSize)
  });
  if (options.storeConnectionId && options.storeConnectionId !== "all") {
    params.set("store_connection_id", options.storeConnectionId);
  }
  if (options.productMeasure) params.set("product_measure", options.productMeasure);
  if (options.start) params.set("start", options.start);
  if (options.end) params.set("end", options.end);
  return apiRequest<AnalyticsDetailPage<T>>(
    `/analytics/business/details?${params.toString()}`
  );
}

export async function createAnalyticsExpense(payload: ExpenseInput) {
  return apiRequest<ExpenseRecord>("/analytics/expenses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteAnalyticsExpense(expenseId: string) {
  return apiRequest<void>(`/analytics/expenses/${expenseId}`, { method: "DELETE" });
}

export async function mapAnalyticsOrderLine(lineId: string, productId: string) {
  return apiRequest<void>(`/analytics/unmatched/${lineId}/map`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_id: productId })
  });
}

export async function updateAnalyticsPreferences(payload: {
  reporting_currency?: ReportingCurrency;
  reporting_timezone?: string;
}) {
  return apiRequest<{ reporting_currency: ReportingCurrency; reporting_timezone: string }>(
    "/analytics/preferences",
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
}

export async function startEtsyOAuth(expectedSellerUserId?: string) {
  const query = expectedSellerUserId
    ? `?expected_seller_user_id=${encodeURIComponent(expectedSellerUserId)}`
    : "";
  return apiRequest<EtsyOAuthStartResponse>(`/etsy/oauth/start${query}`, {
    method: "POST"
  });
}

export async function completeEtsyOAuthCallback(payload: EtsyOAuthCallbackInput) {
  return apiRequest<EtsyConnectionStatus>("/etsy/oauth/callback", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function syncEtsyConnectionShops() {
  return apiRequest<EtsyConnectionStatus>("/etsy/connection/sync", {
    method: "POST"
  });
}

export async function saveProviderCredentials(
  provider: PodProviderKey,
  payload: ProviderCredentialsUpsertInput
) {
  return apiRequest<{ status: string; credential_status: ProviderCredentialStatus }>(
    `/pod-providers/${provider}/credentials`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    }
  );
}

export async function deleteProviderCredentials(
  provider: PodProviderKey,
  credentialKey: string
) {
  return apiRequest<{ status: string; credential_status: ProviderCredentialStatus }>(
    `/pod-providers/${provider}/credentials/${credentialKey}`,
    {
      method: "DELETE"
    }
  );
}

export async function fetchStoreConnections() {
  return apiRequest<ProviderStoreConnection[]>("/provider-store-connections");
}

export async function syncStoreConnections(
  provider: PodProviderKey,
  credentialKey?: string
) {
  return apiRequest<{
    provider: PodProviderKey;
    credential_key: string;
    synced_count: number;
    created_count: number;
    updated_count: number;
    connections: ProviderStoreConnection[];
  }>(
    credentialKey
      ? `/provider-store-connections/sync/${provider}/${credentialKey}`
      : `/provider-store-connections/sync/${provider}`,
    {
    method: "POST"
    }
  );
}

export async function deleteStoreConnection(connectionId: string) {
  return apiRequest<void>(`/provider-store-connections/${connectionId}`, {
    method: "DELETE"
  });
}

export async function updateStoreConnection(
  connectionId: string,
  payload: ProviderStoreConnectionUpdateInput
) {
  return apiRequest<ProviderStoreConnection>(`/provider-store-connections/${connectionId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function fetchBlueprints() {
  return apiRequest<Blueprint[]>("/blueprints");
}

export async function createBlueprint(payload: BlueprintCreateInput) {
  return apiRequest<Blueprint>("/blueprints", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function updateBlueprint(
  blueprintId: string,
  payload: BlueprintUpdateInput
) {
  return apiRequest<Blueprint>(`/blueprints/${blueprintId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function validateBlueprint(blueprintId: string) {
  return apiRequest<{
    blueprint: Blueprint;
    validation_status: string;
    normalized_reference_value: string;
    provider_resource_id: string | null;
  }>(`/blueprints/${blueprintId}/validate-reference`, {
    method: "POST"
  });
}

export async function deleteBlueprint(blueprintId: string) {
  return apiRequest<void>(`/blueprints/${blueprintId}`, {
    method: "DELETE"
  });
}

export async function fetchProducts() {
  return apiRequest<Product[]>("/products");
}

export async function fetchProduct(productId: string) {
  return apiRequest<Product>(`/products/${productId}`);
}

export async function fetchPublishingJobs(productId?: string) {
  const query = productId ? `?product_id=${encodeURIComponent(productId)}` : "";
  return apiRequest<PublishingJob[]>(`/publishing-jobs${query}`);
}

export async function fetchPublishingJob(jobId: string) {
  return apiRequest<PublishingJob>(`/publishing-jobs/${jobId}`);
}

export async function fetchProductStudioState() {
  return apiRequest<ProductStudioState>("/product-studio");
}

export async function uploadDesignAsset(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return apiRequest<DesignAsset>("/design-assets", {
    method: "POST",
    body: formData
  });
}

export async function createProductDraft(payload: ProductCreateInput) {
  return apiRequest<Product>("/products", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function updateProduct(productId: string, payload: ProductUpdateInput) {
  return apiRequest<Product>(`/products/${productId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
}

export async function fetchAICapabilities() { return apiRequest<AICapabilities>("/ai/capabilities"); }
export async function generateProductListing(productId: string, payload: { client_request_id: string; expected_product_revision: number; regenerate_fields?: Array<"title" | "description" | "tags" | "seo_title" | "seo_description" | "seo_keywords"> }) {
  return apiRequest<AIGeneration>(`/products/${productId}/ai-generations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}
export async function applyProductListingGeneration(productId: string, generationId: string, payload: AIGenerationApplyInput) {
  return apiRequest<{ product: Product; generation: AIGeneration }>(`/products/${productId}/ai-generations/${generationId}/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function deleteProduct(productId: string) {
  return apiRequest<void>(`/products/${productId}`, {
    method: "DELETE"
  });
}

export async function uploadMockup(
  productId: string,
  file: File,
  position: number
) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("position", String(position));
  return apiRequest<Mockup>(`/products/${productId}/mockups`, {
    method: "POST",
    body: formData
  });
}

export interface Order {
  id: string;
  organization_id: string;
  provider_store_connection_id: string;
  provider: string;
  provider_store_label: string | null;
  provider_storefront_type: StorefrontType | null;
  external_order_id: string;
  display_order_id: string;
  marketplace_order_id: string | null;
  product_summary: string | null;
  fulfillment_status: string;
  production_status: string | null;
  financial_status: string | null;
  currency: string | null;
  total_amount: number;
  order_created_at: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
  sent_to_production_at: string | null;
  retail_amount: number | null;
  last_synced_at: string;
  provider_order_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderFilterStore {
  id: string;
  label: string;
  provider: string;
}

export interface OrderFilters {
  providers: string[];
  fulfillment_statuses: string[];
  stores: OrderFilterStore[];
}

export interface OrdersQuery {
  page: number;
  pageSize: number;
  storeConnectionId?: string;
  provider?: string;
  fulfillmentStatus?: string;
}

export interface OrdersPageResponse {
  items: Order[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  filters: OrderFilters;
}

export interface SyncJob {
  id: string;
  organization_id: string;
  provider: string | null;
  job_type: string;
  scope_key: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  available_at: string;
  result_json: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface EtsySalesSyncStatus {
  latest_job: SyncJob | null;
  last_successful_at: string | null;
}

export async function fetchOrders(
  query: OrdersQuery
): Promise<OrdersPageResponse> {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize)
  });
  if (query.storeConnectionId) {
    params.set("store_connection_id", query.storeConnectionId);
  }
  if (query.provider) {
    params.set("provider", query.provider);
  }
  if (query.fulfillmentStatus) {
    params.set("fulfillment_status", query.fulfillmentStatus);
  }
  return apiRequest<OrdersPageResponse>(`/orders?${params.toString()}`);
}

export async function runOrderSync(options?: { force?: boolean }): Promise<SyncJob> {
  const params = new URLSearchParams();
  if (options?.force) {
    params.set("force", "true");
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiRequest<SyncJob>(`/sync-jobs/orders/run${query}`, { method: "POST" });
}

export async function fetchLatestOrderSyncJob(): Promise<SyncJob | null> {
  return apiRequest<SyncJob | null>("/sync-jobs/orders/latest");
}

export async function fetchEtsySalesSyncStatus(): Promise<EtsySalesSyncStatus> {
  return apiRequest<EtsySalesSyncStatus>("/sync-jobs/etsy-sales/status");
}

export async function runEtsySalesSync(options?: { force?: boolean }): Promise<SyncJob> {
  const params = new URLSearchParams();
  if (options?.force) {
    params.set("force", "true");
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiRequest<SyncJob>(`/sync-jobs/etsy-sales/run${query}`, {
    method: "POST"
  });
}

export async function fetchSyncJobs(): Promise<SyncJob[]> {
  return apiRequest<SyncJob[]>("/sync-jobs");
}

export async function fetchSyncJob(jobId: string): Promise<SyncJob> {
  return apiRequest<SyncJob>(`/sync-jobs/${jobId}`);
}

export async function reorderMockups(productId: string, mockupIds: string[]) {
  return apiRequest<Product>(`/products/${productId}/mockups/order`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ mockup_ids: mockupIds })
  });
}

export async function deleteMockup(productId: string, mockupId: string) {
  return apiRequest<Product>(`/products/${productId}/mockups/${mockupId}`, {
    method: "DELETE"
  });
}

export async function publishProduct(productId: string, expectedRevision: number) {
  return apiRequest<{ job: PublishingJob }>(`/products/${productId}/publish`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ expected_revision: expectedRevision })
  });
}
