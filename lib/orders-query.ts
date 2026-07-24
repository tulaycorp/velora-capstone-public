import type { OrdersQuery, PodProviderKey } from "@/lib/backend-api";

export const ORDERS_PAGE_SIZE = 15;

export type OrdersQueryState = {
  fulfillmentStatus: string;
  page: number;
  provider: string;
  selectedStoreId: string;
  storeConnectionId: string;
};

export function buildOrdersQuery(state: OrdersQueryState): OrdersQuery {
  const storeConnectionId =
    state.selectedStoreId !== "all"
      ? state.selectedStoreId
      : state.storeConnectionId !== "all"
        ? state.storeConnectionId
        : undefined;

  return {
    page: state.page,
    pageSize: ORDERS_PAGE_SIZE,
    storeConnectionId,
    provider:
      state.selectedStoreId === "all" && state.provider !== "all"
        ? (state.provider as PodProviderKey)
        : undefined,
    fulfillmentStatus:
      state.selectedStoreId === "all" && state.fulfillmentStatus !== "all"
        ? state.fulfillmentStatus
        : undefined
  };
}

export function buildOrdersQueryCacheKey(query: OrdersQuery) {
  return [
    `page=${query.page}`,
    `pageSize=${query.pageSize}`,
    `store=${query.storeConnectionId ?? "all"}`,
    `provider=${query.provider ?? "all"}`,
    `status=${query.fulfillmentStatus ?? "all"}`
  ].join("&");
}
