from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PodProviderKey = Literal["printify", "gelato"]
StorefrontType = Literal["etsy", "shopify", "unknown"]
DiscoverySource = Literal["provider_api", "orders", "manual", "merged", "legacy"]
OrganizationRole = Literal["admin", "member"]
OnboardingStatus = Literal["approved", "needs_organization", "pending"]
JoinRequestStatus = Literal["pending", "approved", "rejected"]
ProviderStoreConnectionStatus = Literal["connected", "disconnected"]
BlueprintStatus = Literal["draft", "active", "archived"]
ProductStatus = Literal["draft", "ready", "published"]
ProductValidationStatus = Literal["pending", "validated"]
ProductPublishingStatus = Literal[
    "not_started",
    "queued",
    "publishing",
    "succeeded",
    "failed",
]


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


class PodProvider(BaseModel):
    id: PodProviderKey
    name: str
    status: str
    connected_stores: int
    credentials_configured: bool = False
    required_keys: list[str] = []
    available_storefronts: list[StorefrontType] = ["etsy", "shopify", "unknown"]
    last_sync_at: datetime | None = None


class ProviderStoreConnection(BaseModel):
    id: str
    provider: PodProviderKey
    credential_key: str
    provider_store_id: str
    label: str
    storefront_type: StorefrontType
    storefront_display_name: str
    etsy_shop_id: str | None = None
    status: ProviderStoreConnectionStatus
    discovery_source: DiscoverySource = "legacy"
    last_sync_at: datetime | None = None
    order_sync_last_success_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ManualStoreSeed(BaseModel):
    provider_store_id: str
    storefront_type: StorefrontType = "unknown"
    storefront_display_name: str
    label: str | None = None
    etsy_shop_id: str | None = None


class ProviderStoreConnectionUpdateRequest(BaseModel):
    etsy_shop_id: str | None = None


class ProviderCredentialsUpsertRequest(BaseModel):
    credential_key: str | None = None
    credentials: dict[str, str] = Field(default_factory=dict)
    credential_display_name: str | None = None
    manual_store_seeds: list[ManualStoreSeed] = Field(default_factory=list)


class ProviderCredentialEntry(BaseModel):
    credential_key: str
    credential_display_name: str | None = None
    credential_masked_value: str | None = None
    configured_keys: list[str] = Field(default_factory=list)
    missing_keys: list[str] = Field(default_factory=list)
    manual_store_seed_count: int = 0
    manual_store_seeds: list[ManualStoreSeed] = Field(default_factory=list)


class ProviderStoreConnectionSyncResponse(BaseModel):
    provider: PodProviderKey
    credential_key: str
    synced_count: int
    created_count: int
    updated_count: int
    connections: list[ProviderStoreConnection]


class EtsyOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str
    redirect_uri: str
    expires_at: datetime
    scopes: list[str] = Field(default_factory=list)


class EtsyOAuthCallbackRequest(BaseModel):
    code: str
    state: str


class EtsyShopSummary(BaseModel):
    shop_id: str
    shop_name: str
    shop_url: str | None = None
    matched_connection_id: str | None = None
    matched_connection_label: str | None = None
    matched_connection_ids: list[str] = Field(default_factory=list)
    matched_connection_labels: list[str] = Field(default_factory=list)


class EtsyConnectedAccountSummary(BaseModel):
    credential_key: str
    seller_user_id: str
    shop_id: str | None = None
    shop_name: str | None = None
    shop_url: str | None = None
    last_synced_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)


class EtsyConnectionStatus(BaseModel):
    is_connected: bool
    seller_user_id: str | None = None
    last_synced_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    connected_account_count: int = 0
    connected_accounts: list[EtsyConnectedAccountSummary] = Field(default_factory=list)
    connected_shops: list[EtsyShopSummary] = Field(default_factory=list)
    matched_connection_count: int = 0
    unmapped_connection_count: int = 0


class AnalyticsScope(BaseModel):
    store_connection_id: str | None = None
    label: str
    provider: PodProviderKey | None = None
    storefront_type: StorefrontType | None = None
    is_all_stores: bool = True


class AnalyticsOverview(BaseModel):
    published_product_count: int = 0
    active_etsy_listing_count: int = 0
    orders_last_30_days: int = 0
    publish_success_rate_last_30_days: float | None = None
    publish_success_count_last_30_days: int = 0
    publish_settled_count_last_30_days: int = 0
    listings_needing_attention_count: int = 0


class CatalogStatusCounts(BaseModel):
    draft_count: int = 0
    ready_count: int = 0
    published_count: int = 0
    failed_publish_count: int = 0


class CatalogIssueCounts(BaseModel):
    missing_description_count: int = 0
    low_tag_count_count: int = 0
    missing_retail_price_count: int = 0
    missing_sku_count: int = 0
    zero_mockups_count: int = 0


class CatalogNeedsAttentionItem(BaseModel):
    product_id: str
    title: str
    provider_store_label: str
    status: str
    publishing_status: str
    issue_count: int
    issues: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class CatalogHealth(BaseModel):
    status_counts: CatalogStatusCounts = Field(default_factory=CatalogStatusCounts)
    issue_counts: CatalogIssueCounts = Field(default_factory=CatalogIssueCounts)
    needs_attention: list[CatalogNeedsAttentionItem] = Field(default_factory=list)


class WorkflowLatestFailure(BaseModel):
    product_id: str
    title: str
    provider_store_label: str
    failed_at: datetime | None = None
    error_message: str | None = None


class WorkflowHealth(BaseModel):
    queued_job_count: int = 0
    in_progress_job_count: int = 0
    failed_job_count_last_30_days: int = 0
    average_publish_duration_seconds: float | None = None
    latest_failure: WorkflowLatestFailure | None = None
    latest_publish_activity_at: datetime | None = None
    latest_etsy_fetch_at: datetime | None = None


class RecentActivity(BaseModel):
    orders_last_7_days: int = 0
    orders_last_30_days: int = 0
    revenue_last_30_days: float = 0.0
    revenue_currency: str | None = None
    revenue_is_mixed_currency: bool = False
    new_drafts_last_30_days: int = 0
    successful_publishes_last_30_days: int = 0


class EtsySnapshot(BaseModel):
    available: bool = False
    unavailable_reason: str | None = None
    is_connected: bool = False
    connected_account_count: int = 0
    supports_detailed_receipts: bool = False
    connected_shop_count: int = 0
    mapped_store_count: int = 0
    lifetime_sales_count: int = 0
    active_listing_count: int = 0
    digital_listing_count: int = 0
    favorite_count: int = 0
    review_count: int = 0
    review_average: float | None = None
    vacation_shop_count: int = 0
    payments_onboarding_issue_count: int = 0
    freshness: Literal["missing", "fresh", "stale"] = "missing"
    refresh_status: Literal["missing", "succeeded", "failed"] = "missing"
    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    last_refresh_attempted_at: datetime | None = None


class StoreRollupRow(BaseModel):
    shop_id: str
    shop_name: str
    shop_url: str | None = None
    currency_code: str | None = None
    lifetime_sales_count: int = 0
    active_listing_count: int = 0
    digital_listing_count: int = 0
    favorite_count: int = 0
    review_count: int = 0
    review_average: float | None = None
    is_vacation: bool | None = None
    has_payments_onboarding_issue: bool = False
    updated_at: datetime | None = None
    last_synced_at: datetime | None = None
    matched_connection_ids: list[str] = Field(default_factory=list)
    matched_connection_labels: list[str] = Field(default_factory=list)


class WorkspaceAnalyticsResponse(BaseModel):
    generated_at: datetime
    scope: AnalyticsScope
    overview: AnalyticsOverview = Field(default_factory=AnalyticsOverview)
    catalog_health: CatalogHealth = Field(default_factory=CatalogHealth)
    workflow_health: WorkflowHealth = Field(default_factory=WorkflowHealth)
    recent_activity: RecentActivity = Field(default_factory=RecentActivity)
    etsy_snapshot: EtsySnapshot = Field(default_factory=EtsySnapshot)
    store_rollup: list[StoreRollupRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


AnalyticsPreset = Literal[
    "7d",
    "30d",
    "90d",
    "this_month",
    "last_month",
    "this_year",
    "all_time",
    "custom",
]
ReportingCurrency = Literal["PHP", "USD", "EUR", "JPY"]


class AnalyticsDateRange(BaseModel):
    preset: AnalyticsPreset
    start: datetime
    end: datetime
    comparison_start: datetime | None = None
    comparison_end: datetime | None = None


class AnalyticsMoneyMetric(BaseModel):
    amount: float | None = None
    currency: ReportingCurrency
    coverage_percent: float = 0.0


class BusinessAnalyticsSummary(BaseModel):
    revenue: AnalyticsMoneyMetric
    expenses: AnalyticsMoneyMetric
    gross_profit: AnalyticsMoneyMetric
    net_profit: AnalyticsMoneyMetric
    gross_margin_percent: float | None = None
    net_margin_percent: float | None = None
    order_count: int = 0
    unit_count: int = 0
    previous_revenue: float | None = None
    previous_order_count: int | None = None
    unmatched_line_count: int = 0


class AnalyticsTrendPoint(BaseModel):
    period: str
    revenue: float | None = None
    expenses: float | None = None
    gross_profit: float | None = None
    net_profit: float | None = None
    orders: int = 0
    comparison_revenue: float | None = None
    comparison_orders: int | None = None


class ProductPerformanceRow(BaseModel):
    product_id: str
    title: str
    store_connection_id: str
    store_label: str
    status: str
    active_days: int = 0
    units: int = 0
    revenue: float | None = None
    gross_profit: float | None = None
    net_profit: float | None = None
    margin_percent: float | None = None
    seo_score: int = 0
    seo_issues: list[str] = Field(default_factory=list)
    profitability_coverage_percent: float = 0.0


class StorePerformanceRow(BaseModel):
    store_connection_id: str
    store_label: str
    provider: str
    storefront_type: str
    order_count: int = 0
    units: int = 0
    revenue: float | None = None
    expenses: float | None = None
    net_profit: float | None = None
    margin_percent: float | None = None
    unmatched_line_count: int = 0


class ExpenseRecord(BaseModel):
    id: str
    incurred_on: datetime
    category: str
    amount: float
    currency: str
    note: str | None = None
    source: str
    provider_store_connection_id: str | None = None
    store_label: str | None = None
    product_id: str | None = None
    product_title: str | None = None
    created_at: datetime | None = None


class ExpenseCreateRequest(BaseModel):
    incurred_on: datetime
    category: str = Field(min_length=1, max_length=64)
    amount: float = Field(ge=0)
    currency: ReportingCurrency = "PHP"
    note: str | None = Field(default=None, max_length=2000)
    provider_store_connection_id: str | None = None
    product_id: str | None = None


class ExpenseUpdateRequest(BaseModel):
    incurred_on: datetime | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    amount: float | None = Field(default=None, ge=0)
    currency: ReportingCurrency | None = None
    note: str | None = Field(default=None, max_length=2000)
    provider_store_connection_id: str | None = None
    product_id: str | None = None


class UnmatchedOrderLine(BaseModel):
    id: str
    order_id: str
    order_display_id: str
    ordered_at: datetime | None = None
    title: str
    sku: str | None = None
    external_listing_id: str | None = None
    quantity: int
    revenue_amount: float | None = None
    currency: str | None = None
    store_connection_id: str
    store_label: str


class OrderLineMappingRequest(BaseModel):
    product_id: str


class SeoPerformanceRow(BaseModel):
    product_id: str
    title: str
    store_label: str
    status: str
    score: int
    issues: list[str] = Field(default_factory=list)
    title_length: int
    tag_count: int
    has_description: bool
    has_mockups: bool
    actual_search_metrics_available: bool = False


AnalyticsDetailResource = Literal["products", "expenses", "seo", "unmatched"]


class AnalyticsDetailPage(BaseModel):
    resource: AnalyticsDetailResource
    items: list[
        ProductPerformanceRow | ExpenseRecord | SeoPerformanceRow | UnmatchedOrderLine
    ] = Field(default_factory=list)
    page: int
    page_size: int
    total: int
    total_pages: int


class AnalyticsCapabilities(BaseModel):
    etsy_connected: bool = False
    detailed_marketplace_finance: bool = False
    authorization_upgrade_required: bool = False
    actual_search_metrics_available: bool = False
    unavailable_metrics: list[str] = Field(default_factory=list)


class BusinessAnalyticsResponse(BaseModel):
    generated_at: datetime
    scope: AnalyticsScope
    date_range: AnalyticsDateRange
    currency: ReportingCurrency
    timezone: str
    trend_granularity: Literal["day", "week", "month"] = "day"
    summary: BusinessAnalyticsSummary
    trend: list[AnalyticsTrendPoint] = Field(default_factory=list)
    products: list[ProductPerformanceRow] = Field(default_factory=list)
    stores: list[StorePerformanceRow] = Field(default_factory=list)
    expenses: list[ExpenseRecord] = Field(default_factory=list)
    seo: list[SeoPerformanceRow] = Field(default_factory=list)
    unmatched_lines: list[UnmatchedOrderLine] = Field(default_factory=list)
    capabilities: AnalyticsCapabilities = Field(default_factory=AnalyticsCapabilities)
    warnings: list[str] = Field(default_factory=list)


class AnalyticsPreferencesUpdateRequest(BaseModel):
    reporting_currency: ReportingCurrency | None = None
    reporting_timezone: str | None = Field(default=None, min_length=1, max_length=64)


class AnalyticsPreferencesResponse(BaseModel):
    reporting_currency: ReportingCurrency
    reporting_timezone: str


class Blueprint(BaseModel):
    id: str
    name: str
    category: str
    provider: PodProviderKey
    provider_store_connection_id: str
    provider_store_label: str
    provider_storefront_type: StorefrontType
    reference_type: str
    reference_value: str
    provider_resource_id: str | None = None
    provider_display_name: str | None = None
    product_code: str | None = None
    placement_config_json: dict[str, Any] | None = None
    provider_snapshot_json: dict[str, Any] | None = None
    product_type: str | None = None
    configuration_summary: str | None = None
    variant_count: int = 0
    base_cost_amount: float | None = None
    currency: str | None = None
    base_title: str | None = None
    base_description: str | None = None
    base_tags: list[str] = []
    basic_design_info_json: dict[str, Any] | None = None
    draft_count: int
    status: BlueprintStatus
    validated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BlueprintCreateRequest(BaseModel):
    name: str
    category: str
    provider_store_connection_id: str
    reference_type: str
    reference_value: str
    product_code: str | None = None
    placement_config_json: dict[str, Any] | None = None
    base_title: str | None = None
    base_description: str | None = None
    base_tags: list[str] = Field(default_factory=list)
    basic_design_info_json: dict[str, Any] | None = None
    status: BlueprintStatus = "draft"

    @field_validator(
        "name",
        "category",
        "provider_store_connection_id",
        "reference_type",
        "reference_value",
        mode="before",
    )
    @classmethod
    def reject_blank_required_strings(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required blueprint fields cannot be blank.")
        return normalized


class BlueprintUpdateRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    product_code: str | None = None
    placement_config_json: dict[str, Any] | None = None
    base_title: str | None = None
    base_description: str | None = None
    base_tags: list[str] | None = None
    basic_design_info_json: dict[str, Any] | None = None
    status: BlueprintStatus | None = None


class BlueprintValidationResponse(BaseModel):
    blueprint: Blueprint
    validation_status: str
    normalized_reference_value: str
    provider_resource_id: str | None = None


class Product(BaseModel):
    id: str
    name: str
    product_type: str
    provider: PodProviderKey
    provider_store_connection_id: str
    provider_store_label: str
    provider_storefront_type: StorefrontType
    status: ProductStatus
    publishing_status: ProductPublishingStatus
    validation_status: ProductValidationStatus
    retail_price: float | None = None
    cost_amount: float | None = None
    margin: float | None = None
    currency: str | None = None
    blueprint_id: str
    design_asset_id: str
    provider_product_id: str | None = None
    external_listing_id: str | None = None
    provider_product_url: str | None = None
    provider_fulfillment_url: str | None = None
    provider_status: str | None = None
    title: str
    description: str | None = None
    tags: list[str] = []
    sku: str | None = None
    revision: int = 1
    design_description: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    seo_keywords: list[str] = Field(default_factory=list)
    last_ai_generation_id: str | None = None
    mockup_count: int = 0
    design_asset: "DesignAsset | None" = None
    mockups: list["Mockup"] = []
    last_provider_sync_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DesignAsset(BaseModel):
    id: str
    file_name: str
    content_type: str
    size_bytes: int
    storage_key: str
    public_url: str | None = None
    checksum: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Mockup(BaseModel):
    id: str
    provider_product_draft_id: str
    file_name: str
    content_type: str
    size_bytes: int
    storage_key: str
    public_url: str | None = None
    checksum: str | None = None
    position: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MockupOrderRequest(BaseModel):
    mockup_ids: list[str]


class ProductCreateRequest(BaseModel):
    blueprint_id: str
    design_asset_id: str
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    retail_price: float | None = None
    currency: str | None = None
    sku: str | None = None
    design_description: str | None = None


class ProductUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    retail_price: float | None = None
    currency: str | None = None
    sku: str | None = None
    design_asset_id: str | None = None
    status: ProductStatus | None = None
    validation_status: ProductValidationStatus | None = None
    design_description: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    seo_keywords: list[str] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class PublishProductResponse(BaseModel):
    job: "PublishingJob"


class PublishProductRequest(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)


class ProductStudioState(BaseModel):
    steps: list[str]
    selected_provider: PodProviderKey | None
    selected_store_connection_ids: list[str]
    requires_blueprint: bool
    blueprint_count: int = 0
    draft_count: int = 0


class AICapabilities(BaseModel):
    enabled: bool
    model: str | None = None
    supported_fields: list[str] = Field(default_factory=lambda: ["title", "description", "tags", "seo_title", "seo_description", "seo_keywords"])


class AIGenerationRequest(BaseModel):
    client_request_id: str = Field(min_length=8, max_length=64)
    expected_product_revision: int = Field(ge=1)
    regenerate_fields: list[Literal["title", "description", "tags", "seo_title", "seo_description", "seo_keywords"]] = Field(default_factory=list)


class AIGenerationApplyRequest(BaseModel):
    expected_product_revision: int = Field(ge=1)
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    seo_keywords: list[str] | None = None

    @model_validator(mode="after")
    def require_a_field(self) -> "AIGenerationApplyRequest":
        if all(value is None for value in (self.title, self.description, self.tags, self.seo_title, self.seo_description, self.seo_keywords)):
            raise ValueError("Select at least one generated field to apply.")
        return self


class AIGenerationSummary(BaseModel):
    id: str
    product_id: str
    source_product_revision: int
    status: Literal["pending", "completed", "failed", "accepted"]
    output: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    accepted_at: datetime | None = None


class AIGenerationApplyResponse(BaseModel):
    product: Product
    generation: AIGenerationSummary


class PublishingJob(BaseModel):
    id: str
    product_id: str
    provider: PodProviderKey
    provider_store_connection_id: str
    status: str
    stage: str
    retry_count: int
    operation: Literal["create", "update"]
    product_revision: int
    provider_product_id: str | None = None
    error_message: str | None = None
    blueprint_id: str | None = None
    pod_product_id: str | None = None
    raw_result_json: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProviderCredentialStatus(BaseModel):
    provider: PodProviderKey
    is_configured: bool
    required_keys: list[str]
    credential_count: int = 0
    credentials: list[ProviderCredentialEntry] = Field(default_factory=list)


class ProviderCredentialsUpsertResponse(BaseModel):
    status: str
    credential_status: ProviderCredentialStatus


class SessionContextUser(BaseModel):
    id: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    image_url: str | None = None
    display_name: str


class SessionContextOrganization(BaseModel):
    id: str
    name: str
    join_code: str | None = None
    admin_user_id: str | None = None
    admin_name: str | None = None


class SessionContextMembership(BaseModel):
    role: OrganizationRole


class OrganizationJoinRequestSummary(BaseModel):
    id: str
    organization_id: str
    organization_name: str
    requested_by_user_id: str
    requested_by_name: str
    requested_by_email: str | None = None
    status: JoinRequestStatus
    created_at: datetime | None = None
    reviewed_at: datetime | None = None


class SessionContextResponse(BaseModel):
    auth_mode: Literal["local", "clerk"]
    onboarding_status: OnboardingStatus
    user: SessionContextUser
    organization: SessionContextOrganization | None = None
    membership: SessionContextMembership | None = None
    pending_join_request: OrganizationJoinRequestSummary | None = None
    admin_pending_request_count: int = 0


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class OrganizationCreateResponse(BaseModel):
    status: str
    organization: SessionContextOrganization
    membership: SessionContextMembership


class OrganizationUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class OrganizationUpdateResponse(BaseModel):
    status: str
    organization: SessionContextOrganization


class OrganizationJoinRequestCreateRequest(BaseModel):
    join_code: str = Field(min_length=4, max_length=32)


class OrganizationJoinRequestResponse(BaseModel):
    status: str
    join_request: OrganizationJoinRequestSummary


class OrganizationJoinRequestListResponse(BaseModel):
    pending_request_count: int
    join_requests: list[OrganizationJoinRequestSummary]


class OrganizationMemberSummary(BaseModel):
    user_id: str
    display_name: str
    email: str | None = None
    role: OrganizationRole
    joined_at: datetime | None = None
    is_current_user: bool = False
    is_removable: bool = False


class OrganizationMemberListResponse(BaseModel):
    member_count: int
    members: list[OrganizationMemberSummary]


class OrganizationMemberResponse(BaseModel):
    status: str
    member: OrganizationMemberSummary


class OrganizationLeaveResponse(BaseModel):
    status: str
    session_context: SessionContextResponse


class Order(BaseModel):
    id: str
    organization_id: str
    provider_store_connection_id: str
    provider: str
    external_order_id: str
    display_order_id: str
    marketplace_order_id: str | None = None
    product_summary: str | None = None
    fulfillment_status: str
    production_status: str | None = None
    financial_status: str | None = None
    currency: str | None = None
    total_amount: float
    order_created_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    sent_to_production_at: datetime | None = None
    retail_amount: float | None = None
    provider_order_url: str | None = None
    last_synced_at: datetime | None = None
    provider_store_label: str | None = None
    provider_storefront_type: StorefrontType | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrderFilterStore(BaseModel):
    id: str
    label: str
    provider: str


class OrderFilters(BaseModel):
    providers: list[str] = Field(default_factory=list)
    fulfillment_statuses: list[str] = Field(default_factory=list)
    stores: list[OrderFilterStore] = Field(default_factory=list)


class OrderPageResponse(BaseModel):
    items: list[Order]
    page: int
    page_size: int
    total: int
    total_pages: int
    filters: OrderFilters


class SyncJob(BaseModel):
    id: str
    organization_id: str
    provider: str | None = None
    job_type: str
    scope_key: str
    status: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    result_json: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EtsySalesSyncStatus(BaseModel):
    latest_job: SyncJob | None = None
    last_successful_at: datetime | None = None


class SyncEvent(BaseModel):
    id: str
    sync_job_id: str
    organization_id: str
    provider: PodProviderKey | None = None
    provider_store_connection_id: str | None = None
    event_type: str
    message: str | None = None
    details_json: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


Product.model_rebuild()
PublishProductResponse.model_rebuild()
BlueprintValidationResponse.model_rebuild()
