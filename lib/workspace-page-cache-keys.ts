export const workspacePageCacheKeys = {
  analytics: (storeConnectionId: string) =>
    `workspace:analytics:${storeConnectionId}`,
  analyticsBusiness: (queryKey: string) =>
    `workspace:analytics-business:${queryKey}`,
  blueprints: () => "workspace:blueprints",
  dashboard: () => "workspace:dashboard",
  orders: (queryKey: string) => `workspace:orders:${queryKey}`,
  ordersPrefix: () => "workspace:orders:",
  organizationSettings: () => "workspace:organization-settings",
  product: (productId: string) => `workspace:product:${productId}`,
  productStudio: () => "workspace:product-studio",
  products: () => "workspace:products",
  storeContext: () => "workspace:store-context"
} as const;
