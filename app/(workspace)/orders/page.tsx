"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import { useAppSessionContext } from "@/components/auth/app-session-context";
import { PageHeader } from "@/components/workspace/page-header";
import { useStoreContext } from "@/components/workspace/store-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SimpleTable } from "@/components/workspace/simple-table";
import { EmptyState, GenericPageSkeleton, ResourceError } from "@/components/workspace/resource-state";
import { StoreLabel } from "@/components/workspace/store-label";
import {
  fetchLatestOrderSyncJob,
  fetchOrders,
  fetchSyncJob,
  formatCurrency,
  formatDate,
  formatDateTime,
  providerLabel,
  type OrderFilterStore,
  runOrderSync,
  type Order,
  type OrdersPageResponse,
  type SyncJob
} from "@/lib/backend-api";
import {
  clearWorkspacePageCache
} from "@/lib/workspace-page-cache";
import { workspacePageCacheKeys } from "@/lib/workspace-page-cache-keys";
import { cleanStoreDisplayName } from "@/lib/store-display";
import { useCachedWorkspaceResource } from "@/hooks/use-cached-workspace-resource";
import { useRefetchOnWindowFocus } from "@/hooks/use-refetch-on-window-focus";
import {
  buildOrdersQuery,
  buildOrdersQueryCacheKey
} from "@/lib/orders-query";
import {
  getLastSuccessfulOrderSyncAt,
  getLatestSyncJobActivityAt,
  getOrderSyncOutcomeCounts,
  isSyncJobActiveStatus,
  ORDER_SYNC_AUTO_STALE_AFTER_MS,
  pollSyncJobUntilSettled,
  shouldAutoStartSync
} from "@/lib/sync-job-status";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const ORDER_SYNC_POLL_INTERVAL_MS = 3000;
const ORDER_SYNC_POLL_TIMEOUT_MS = 180000;

function formatStatus(status: string | null | undefined) {
  if (!status) return "Unknown";
  return status.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

export default function OrdersPage() {
  const { sessionContext } = useAppSessionContext();
  const { selectedStoreId, selectionReady } = useStoreContext();
  const [currentPage, setCurrentPage] = useState(1);
  const [providerFilter, setProviderFilter] = useState("all");
  const [storeFilter, setStoreFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [latestSyncJob, setLatestSyncJob] = useState<SyncJob | null>(null);
  const latestSyncJobRef = useRef<SyncJob | null>(null);
  const syncInitializedRef = useRef(false);
  const syncFlowRef = useRef<Promise<void> | null>(null);
  const cacheScope = useMemo(
    () => ({
      organizationId: sessionContext.organization?.id ?? null,
      userId: sessionContext.user.id
    }),
    [sessionContext.organization?.id, sessionContext.user.id]
  );
  const ordersQuery = useMemo(
    () =>
      buildOrdersQuery({
        fulfillmentStatus: statusFilter,
        page: currentPage,
        provider: providerFilter,
        selectedStoreId,
        storeConnectionId: storeFilter
      }),
    [currentPage, providerFilter, selectedStoreId, statusFilter, storeFilter]
  );
  const cacheKey = workspacePageCacheKeys.orders(
    buildOrdersQueryCacheKey(ordersQuery)
  );
  const loadOrdersResource = useCallback(
    () => fetchOrders(ordersQuery),
    [ordersQuery]
  );
  const {
    data: ordersPage,
    error,
    load,
    loading
  } = useCachedWorkspaceResource<OrdersPageResponse>({
    cacheKey,
    loadResource: loadOrdersResource
  });
  const orders = ordersPage?.items ?? [];

  const updateLatestSyncJob = useCallback((job: SyncJob | null) => {
    latestSyncJobRef.current = job;
    setLatestSyncJob(job);
  }, []);

  const invalidateOrdersCache = useCallback(() => {
    clearWorkspacePageCache({
      keyPrefix: workspacePageCacheKeys.ordersPrefix(),
      scope: cacheScope
    });
  }, [cacheScope]);

  const loadOrders = useCallback(
    async ({
      resetPage = false,
    }: {
      resetPage?: boolean;
    } = {}) => {
      if (resetPage && currentPage !== 1) {
        setCurrentPage(1);
        return;
      }

      await load("background");
    },
    [currentPage, load]
  );

  const loadLatestSyncState = useCallback(async () => {
    const job = await fetchLatestOrderSyncJob();
    updateLatestSyncJob(job);
    return job;
  }, [updateLatestSyncJob]);

  const monitorOrderSync = useCallback(
    async (job: SyncJob) => {
      const pollResult = await pollSyncJobUntilSettled({
        jobId: job.id,
        fetchJob: fetchSyncJob,
        intervalMs: ORDER_SYNC_POLL_INTERVAL_MS,
        timeoutMs: ORDER_SYNC_POLL_TIMEOUT_MS,
        onJob: (nextJob) => {
          updateLatestSyncJob(nextJob);
          if (nextJob.status !== "failed") {
            setSyncError(null);
          }
        }
      });

      const freshestJob = (await loadLatestSyncState().catch(() => pollResult.job)) ?? pollResult.job ?? null;
      if (freshestJob) {
        updateLatestSyncJob(freshestJob);
      }

      if (freshestJob?.status === "completed" || freshestJob?.status === "partial") {
        invalidateOrdersCache();
        await loadOrders({ resetPage: false });
      }

      if (freshestJob?.status === "failed" && freshestJob.error_message) {
        setSyncError(`Last sync failed: ${freshestJob.error_message}`);
        return;
      }

      if (pollResult.timedOut) {
        setSyncError("Order sync is still running in the background.");
      }
    },
    [invalidateOrdersCache, loadLatestSyncState, loadOrders, updateLatestSyncJob]
  );

  const ensureOrderSync = useCallback(
    async ({
      force = false,
      refreshLatestState = false,
    }: {
      force?: boolean;
      refreshLatestState?: boolean;
    } = {}) => {
      if (syncFlowRef.current) {
        await syncFlowRef.current;
        return;
      }

      const syncFlow = (async () => {
        let currentJob = latestSyncJobRef.current;

        if (refreshLatestState) {
          try {
            currentJob = await loadLatestSyncState();
          } catch {
            currentJob = latestSyncJobRef.current;
          }
        }

        const shouldMonitorActiveJob = currentJob !== null && isSyncJobActiveStatus(currentJob.status);
        const shouldStartNewJob =
          force ||
          shouldAutoStartSync(currentJob, {
            staleAfterMs: ORDER_SYNC_AUTO_STALE_AFTER_MS,
          });

        if (!shouldMonitorActiveJob && !shouldStartNewJob) {
          return;
        }

        setSyncing(true);
        setSyncError(null);

        try {
          let nextJob = currentJob;

          if (force || shouldStartNewJob) {
            nextJob = await runOrderSync({ force });
            updateLatestSyncJob(nextJob);
          }

          if (!nextJob) {
            return;
          }

          if (isSyncJobActiveStatus(nextJob.status)) {
            await monitorOrderSync(nextJob);
            return;
          }

          updateLatestSyncJob(nextJob);
          if (nextJob.status === "completed" || nextJob.status === "partial") {
            invalidateOrdersCache();
            await loadOrders({ resetPage: false });
          } else if (nextJob.status === "failed" && nextJob.error_message) {
            setSyncError(`Last sync failed: ${nextJob.error_message}`);
          }
        } catch (nextError) {
          setSyncError(nextError instanceof Error ? nextError.message : "Unable to refresh orders right now.");
        } finally {
          setSyncing(false);
        }
      })();

      syncFlowRef.current = syncFlow;

      try {
        await syncFlow;
      } finally {
        if (syncFlowRef.current === syncFlow) {
          syncFlowRef.current = null;
        }
      }
    },
    [invalidateOrdersCache, loadLatestSyncState, loadOrders, monitorOrderSync, updateLatestSyncJob]
  );

  const loadInitialSyncState = useCallback(async () => {
    try {
      const latestJob = await loadLatestSyncState();
      if (latestJob?.status === "failed" && latestJob.error_message) {
        setSyncError(`Last sync failed: ${latestJob.error_message}`);
      } else {
        setSyncError(null);
      }
      void ensureOrderSync();
    } catch (nextError) {
      setSyncError(
        nextError instanceof Error
          ? nextError.message
          : "Unable to load order sync status."
      );
    }
  }, [ensureOrderSync, loadLatestSyncState]);

  useEffect(() => {
    if (syncInitializedRef.current) {
      return;
    }
    syncInitializedRef.current = true;
    void loadInitialSyncState();
  }, [loadInitialSyncState]);

  useRefetchOnWindowFocus(
    useCallback(async () => {
      await ensureOrderSync({ refreshLatestState: true });
    }, [ensureOrderSync])
  );

  useEffect(() => {
    setProviderFilter("all");
    setStoreFilter("all");
    setStatusFilter("all");
    setCurrentPage(1);
  }, [selectedStoreId]);

  async function handleSync() {
    await ensureOrderSync({ force: true });
  }

  if (loading) {
    return (
      <>
        <PageHeader
          title="Orders"
          description="Order and fulfillment updates will appear here."
          preserveActionSpace
        />
        <GenericPageSkeleton />
      </>
    );
  }

  if (error) {
    return (
      <>
        <PageHeader
          title="Orders"
          description="Order and fulfillment updates will appear here."
          preserveActionSpace
        />
        <ResourceError message={error} onRetry={() => void load()} />
      </>
    );
  }

  const handleFilterChange = (type: "provider" | "store" | "status", value: string) => {
    if (type === "provider") {
      setProviderFilter(value);
      setStoreFilter("all");
    } else if (type === "store") {
      setStoreFilter(value);
    } else if (type === "status") {
      setStatusFilter(value);
    }
    setCurrentPage(1);
  };

  const providers = ordersPage?.filters.providers ?? [];
  const statuses = ordersPage?.filters.fulfillment_statuses ?? [];
  const storesByProvider = new Map<string, OrderFilterStore[]>();
  for (const store of ordersPage?.filters.stores ?? []) {
    const providerStores = storesByProvider.get(store.provider) ?? [];
    providerStores.push(store);
    storesByProvider.set(store.provider, providerStores);
  }
  const isStoreScoped = selectionReady && selectedStoreId !== "all";
  const showOrderFilters = selectionReady;
  const showProviderAndStoreFilters = selectedStoreId === "all";
  const hasScopedOrders = isStoreScoped
    ? (ordersPage?.total ?? 0) > 0
    : providers.length > 0 ||
      statuses.length > 0 ||
      (ordersPage?.filters.stores.length ?? 0) > 0;

  const totalPages = ordersPage?.total_pages ?? 0;
  const latestSyncTimestamp = getLatestSyncJobActivityAt(latestSyncJob);
  const lastSuccessfulSyncAt = getLastSuccessfulOrderSyncAt(latestSyncJob);
  const latestOutcomeCounts = getOrderSyncOutcomeCounts(latestSyncJob);
  const latestSyncCopy = latestSyncTimestamp
    ? `${
        latestSyncJob && isSyncJobActiveStatus(latestSyncJob.status)
          ? "Latest sync started"
          : latestSyncJob?.status === "failed" || latestSyncJob?.status === "partial"
            ? "Last sync attempt"
            : "Last successful sync"
      } ${formatDateTime(latestSyncTimestamp)}`
    : "Orders haven't been synced yet.";
  const lastSuccessfulSyncCopy =
    lastSuccessfulSyncAt && latestSyncJob?.status !== "completed"
      ? `Last successful sync ${formatDateTime(lastSuccessfulSyncAt)}`
      : null;
  const latestSyncWarning =
    latestSyncJob?.status === "partial"
      ? latestOutcomeCounts
        ? latestOutcomeCounts.failed > 0
          ? `Partial sync: ${latestOutcomeCounts.fetched} fetched, ${
              latestOutcomeCounts.inserted + latestOutcomeCounts.updated
            } saved, ${latestOutcomeCounts.skipped} skipped, ${latestOutcomeCounts.failed} failed.`
          : `Partial sync: ${latestOutcomeCounts.fetched} fetched and ${
              latestOutcomeCounts.inserted + latestOutcomeCounts.updated
            } saved. Remaining pages will resume from saved progress.`
        : "The last sync completed partially and will resume from its saved progress."
      : null;
  const latestSyncFailure =
    latestSyncJob?.status === "failed" && latestSyncJob.error_message
      ? `Last sync failed: ${latestSyncJob.error_message}`
      : null;
  const statusMessage = syncing
    ? "Syncing orders..."
    : latestSyncJob && isSyncJobActiveStatus(latestSyncJob.status)
      ? "Order sync is still running."
      : null;
  const statusError = latestSyncFailure ?? syncError;

  return (
    <>
      <PageHeader
        title="Orders"
        description="Order and fulfillment updates will appear here as this workspace expands."
        action={
          <Button onClick={() => void handleSync()} disabled={syncing}>
            {syncing ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            {syncing ? "Syncing..." : "Refresh Now"}
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
        {statusMessage ? (
          <span className="inline-flex items-center gap-2 font-medium text-foreground">
            <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            {statusMessage}
          </span>
        ) : null}
        <span>{latestSyncCopy}</span>
        {lastSuccessfulSyncCopy ? <span>{lastSuccessfulSyncCopy}</span> : null}
        {latestSyncWarning ? <span className="font-medium text-amber-600 dark:text-amber-400">{latestSyncWarning}</span> : null}
        {statusError ? <span className="text-destructive">{statusError}</span> : null}
      </div>

      {!hasScopedOrders ? (
        <EmptyState
          title="No orders found"
          description={
            isStoreScoped
              ? "No orders match the selected store yet."
              : "Orders will appear here after the workspace syncs its connected stores."
          }
          action={
            <Button className="w-fit" onClick={() => void handleSync()} disabled={syncing}>
              Refresh Now
            </Button>
          }
        />
      ) : (
        <div className="space-y-4">
          {showOrderFilters ? (
            <div className="flex flex-wrap items-center gap-3">
              {showProviderAndStoreFilters ? (
                <>
                  <Select value={providerFilter} onValueChange={(value) => handleFilterChange("provider", value)}>
                    <SelectTrigger className="w-[180px]">
                      <SelectValue placeholder="All Providers" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Providers</SelectItem>
                      {providers.map((provider) => (
                        <SelectItem key={provider as string} value={provider as string}>
                          {providerLabel(provider)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Select value={storeFilter} onValueChange={(value) => handleFilterChange("store", value)}>
                    <SelectTrigger className="w-[180px]">
                      <SelectValue placeholder="All Stores" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Stores</SelectItem>
                      {providerFilter === "all" ? (
                        Array.from(storesByProvider.entries()).map(([provider, providerStores]) => {
                          if (providerStores.length === 0) return null;
                          return (
                            <SelectGroup key={provider}>
                              <SelectSeparator className="my-1" />
                              <SelectLabel className="text-xs font-normal text-muted-foreground">
                                {providerLabel(provider)}
                              </SelectLabel>
                              {providerStores.map((store) => (
                                <SelectItem key={store.id} value={store.id}>
                                  {cleanStoreDisplayName(store.label)}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          );
                        })
                      ) : (
                        (storesByProvider.get(providerFilter) || []).map((store) => (
                          <SelectItem key={store.id} value={store.id}>
                            {cleanStoreDisplayName(store.label)}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                </>
              ) : null}

              <Select value={statusFilter} onValueChange={(value) => handleFilterChange("status", value)}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="All Statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Statuses</SelectItem>
                  {statuses.map((status) => (
                    <SelectItem key={status as string} value={status as string}>
                      {formatStatus(status as string)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          <SimpleTable
            tableClassName="table-fixed w-full"
            rows={orders}
            columns={[
              {
                key: "display_order_id",
                label: "Order ID",
                className: "!pl-4 !pr-1.5 w-[9%]",
                render: (row: Order) => <span className="block truncate font-medium">{row.display_order_id}</span>,
              },
              {
                key: "date",
                label: "Date",
                className: "!px-1.5 w-[10%]",
                render: (row: Order) => {
                  if (row.provider === "printify") {
                    return row.sent_to_production_at ? formatDate(row.sent_to_production_at) : "Pending";
                  }
                  return row.order_created_at ? formatDate(row.order_created_at) : "Pending";
                },
              },
              {
                key: "product",
                label: "Product",
                className: "!px-1.5 w-[20%]",
                render: (row: Order) => <span className="block max-w-full truncate">{row.product_summary || "—"}</span>,
              },
              {
                key: "total_cost",
                label: "Total Cost",
                className: "!px-1.5 w-[9%]",
                render: (row: Order) => formatCurrency(row.total_amount, row.currency ?? "USD"),
              },
              {
                key: "status",
                label: "Status",
                className: "!px-1 w-[12%]",
                render: (row: Order) => (
                  <Badge variant="secondary" className="whitespace-nowrap px-1.5 py-0.5 text-[11px] font-normal">
                    {formatStatus(row.fulfillment_status)}
                  </Badge>
                ),
              },
              {
                key: "store",
                label: "Store",
                className: "!pl-1 !pr-1.5 w-[16%]",
                render: (row: Order) => (
                  <StoreLabel source={row} includeProvider={false} secondaryVariant="badge" />
                ),
              },
              {
                key: "provider",
                label: "Provider",
                className: "!px-1.5 w-[10%]",
                render: (row: Order) => providerLabel(row.provider),
              },
              {
                key: "action",
                label: "",
                className: "!pl-1 !pr-3 w-[4%] text-right",
                render: (row: Order) =>
                  row.provider_order_url ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-foreground"
                      asChild
                    >
                      <a
                        href={row.provider_order_url}
                        target="_blank"
                        rel="noreferrer"
                        title={`Open in ${providerLabel(row.provider)}`}
                      >
                        <ArrowUpRight className="h-4 w-4" />
                        <span className="sr-only">Open in {providerLabel(row.provider)}</span>
                      </a>
                    </Button>
                  ) : (
                    <span className="text-sm text-muted-foreground">—</span>
                  ),
              },
            ]}
          />

          {totalPages > 1 ? (
            <Pagination className="justify-end">
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    href="#"
                    onClick={(event) => {
                      event.preventDefault();
                      if (currentPage > 1) setCurrentPage(currentPage - 1);
                    }}
                    className={currentPage === 1 ? "pointer-events-none opacity-50" : ""}
                  />
                </PaginationItem>

                {currentPage > 2 ? (
                  <PaginationItem>
                    <PaginationLink
                      href="#"
                      onClick={(event) => {
                        event.preventDefault();
                        setCurrentPage(1);
                      }}
                    >
                      1
                    </PaginationLink>
                  </PaginationItem>
                ) : null}

                {currentPage > 3 ? (
                  <PaginationItem>
                    <PaginationEllipsis />
                  </PaginationItem>
                ) : null}

                {Array.from({ length: 3 }, (_, index) => currentPage - 1 + index)
                  .filter((page) => page >= 1 && page <= totalPages)
                  .map((page) => (
                    <PaginationItem key={page}>
                      <PaginationLink
                        href="#"
                        isActive={currentPage === page}
                        onClick={(event) => {
                          event.preventDefault();
                          setCurrentPage(page);
                        }}
                      >
                        {page}
                      </PaginationLink>
                    </PaginationItem>
                  ))}

                {currentPage < totalPages - 2 ? (
                  <PaginationItem>
                    <PaginationEllipsis />
                  </PaginationItem>
                ) : null}

                {currentPage < totalPages - 1 ? (
                  <PaginationItem>
                    <PaginationLink
                      href="#"
                      onClick={(event) => {
                        event.preventDefault();
                        setCurrentPage(totalPages);
                      }}
                    >
                      {totalPages}
                    </PaginationLink>
                  </PaginationItem>
                ) : null}

                <PaginationItem>
                  <PaginationNext
                    href="#"
                    onClick={(event) => {
                      event.preventDefault();
                      if (currentPage < totalPages) setCurrentPage(currentPage + 1);
                    }}
                    className={currentPage === totalPages ? "pointer-events-none opacity-50" : ""}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          ) : null}
        </div>
      )}
    </>
  );
}
