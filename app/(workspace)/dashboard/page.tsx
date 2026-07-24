"use client";

import Link from "next/link";
import { useCallback } from "react";
import { ArrowUpRight } from "lucide-react";
import { PageHeader } from "@/components/workspace/page-header";
import { SimpleTable } from "@/components/workspace/simple-table";
import { StoreLabel } from "@/components/workspace/store-label";
import {
  ResourceError,
  DashboardSkeleton
} from "@/components/workspace/resource-state";
import { StatusBadge } from "@/components/workspace/status-badge";
import { useStoreContext } from "@/components/workspace/store-context";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import {
  fetchBlueprints,
  fetchProductStudioState,
  fetchProducts,
  fetchProviders,
  fetchPublishingJobs,
  formatDateTime,
  providerLabel,
  type Blueprint,
  type PodProvider,
  type Product,
  type ProductStudioState,
  type PublishingJob
} from "@/lib/backend-api";
import { formatBlueprintVariantSummary } from "@/lib/blueprint-display";
import { workspacePageCacheKeys } from "@/lib/workspace-page-cache-keys";
import { useCachedWorkspaceResource } from "@/hooks/use-cached-workspace-resource";
import { useRefetchOnWindowFocus } from "@/hooks/use-refetch-on-window-focus";

type DashboardPageData = {
  blueprints: Blueprint[];
  jobs: PublishingJob[];
  products: Product[];
  providers: PodProvider[];
  studioState: ProductStudioState | null;
};

function MetricCard({
  label,
  value,
  detail
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
          {label}
        </div>
        <div className="mt-2 text-2xl font-semibold text-foreground">{value}</div>
        <div className="mt-1 text-sm text-muted-foreground">{detail}</div>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { selectedStoreId } = useStoreContext();

  const loadOverview = useCallback(async (): Promise<DashboardPageData> => {
    const [nextProducts, nextBlueprints, nextProviders, nextJobs, nextStudioState] =
      await Promise.all([
        fetchProducts(),
        fetchBlueprints(),
        fetchProviders(),
        fetchPublishingJobs(),
        fetchProductStudioState()
      ]);

    return {
      blueprints: nextBlueprints,
      jobs: nextJobs,
      products: nextProducts,
      providers: nextProviders,
      studioState: nextStudioState
    };
  }, []);

  const {
    data: overview,
    error,
    isCacheFresh,
    load,
    loading
  } = useCachedWorkspaceResource<DashboardPageData>({
    cacheKey: workspacePageCacheKeys.dashboard(),
    loadResource: loadOverview
  });

  useRefetchOnWindowFocus(
    useCallback(async () => {
      await load("background", "if-stale");
    }, [load]),
    { shouldRefetch: () => !isCacheFresh() }
  );

  if (loading) {
    return (
      <>
        <PageHeader
          title="Overview"
          description="A quick view of what needs attention in the active store."
        />
        <DashboardSkeleton />
      </>
    );
  }

  if (!overview || error) {
    return (
      <>
        <PageHeader
          title="Overview"
          description="A quick view of what needs attention in the active store."
        />
        <ResourceError message={error ?? "Unable to load dashboard data."} onRetry={() => void load()} />
      </>
    );
  }

  const { blueprints, jobs, products, providers, studioState } = overview;

  const filteredProducts =
    selectedStoreId === "all"
      ? products
      : products.filter((product) => product.provider_store_connection_id === selectedStoreId);

  const filteredBlueprints =
    selectedStoreId === "all"
      ? blueprints
      : blueprints.filter(
          (blueprint) => blueprint.provider_store_connection_id === selectedStoreId
        );

  const filteredJobs =
    selectedStoreId === "all"
      ? jobs
      : jobs.filter((job) => job.provider_store_connection_id === selectedStoreId);

  const recentProducts = filteredProducts.slice(0, 5);
  const connectedProviderCount = providers.filter((provider) => provider.credentials_configured).length;
  const queuedJobs = filteredJobs.filter((job) =>
    ["queued", "running", "pending"].includes(job.status)
  ).length;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Track saved products, reusable setups, and recent sends."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Blueprints"
          value={String(filteredBlueprints.length)}
          detail="Reusable product setups"
        />
        <MetricCard
          label="Drafts"
          value={String(filteredProducts.length)}
          detail="Saved products in progress"
        />
        <MetricCard
          label="Sending"
          value={String(queuedJobs)}
          detail="Products currently being sent"
        />
        <MetricCard
          label="Connections"
          value={String(connectedProviderCount)}
          detail="Partners ready to use"
        />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_360px]">
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle className="text-base font-medium tracking-normal">
              Recent products
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <SimpleTable
              className="rounded-none border-0"
              rows={recentProducts}
              columns={[
                {
                  key: "title",
                  label: "Product",
                  render: (row) => (
                    <div className="min-w-[260px]">
                      <Link
                        href={`/products/${row.id}`}
                        className="group inline-flex max-w-full items-center gap-2 text-sm font-semibold text-foreground hover:text-primary"
                      >
                        <span className="truncate">{row.title}</span>
                        <ArrowUpRight className="h-4 w-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                      </Link>
                      <div className="text-xs text-muted-foreground">{row.product_type}</div>
                    </div>
                  )
                },
                {
                  key: "provider",
                  label: "Partner",
                  render: (row) => providerLabel(row.provider)
                },
                {
                  key: "provider_store_label",
                  label: "Store",
                  render: (row) => <StoreLabel source={row} secondaryVariant="badge" />
                },
                {
                  key: "publishing_status",
                  label: "Sending",
                  render: (row) => <StatusBadge value={row.publishing_status} />
                },
                {
                  key: "updated_at",
                  label: "Updated",
                  render: (row) => formatDateTime(row.updated_at)
                }
              ]}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle className="text-base font-medium tracking-normal">
              Product workflow
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ol>
              {(studioState?.steps ?? []).map((item, index) => (
                <li
                  key={item}
                  className="flex gap-3 border-b border-border px-4 py-3 last:border-b-0"
                >
                  <span className="text-muted-foreground">{index + 1}</span>
                  <span>{item}</span>
                </li>
              ))}
            </ol>
          </CardContent>
          <CardFooter className="border-t border-border px-4 py-3">
            <Button asChild className="w-full">
              <Link href="/product-studio">Open Product Studio</Link>
            </Button>
          </CardFooter>
        </Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle className="text-base font-medium tracking-normal">
              Blueprints
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 p-4">
            {filteredBlueprints.slice(0, 4).map((blueprint) => (
              <div
                key={blueprint.id}
                className="flex items-start justify-between gap-3 rounded-md border border-border bg-background px-3 py-3"
              >
                <div>
                  <div className="font-medium text-foreground">{blueprint.name}</div>
                  <div className="mt-1">
                    <StoreLabel source={blueprint} secondaryVariant="badge" />
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    {formatBlueprintVariantSummary(blueprint)}
                  </div>
                </div>
                <StatusBadge value={blueprint.status} />
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border px-4 py-3">
            <CardTitle className="text-base font-medium tracking-normal">
              Recent sends
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 p-4">
            {filteredJobs.slice(0, 4).map((job) => (
              <div
                key={job.id}
                className="flex items-start justify-between gap-3 rounded-md border border-border bg-background px-3 py-3"
              >
                <div>
                  <div className="font-medium text-foreground">
                    Sending through {providerLabel(job.provider)}
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    Updated {formatDateTime(job.updated_at)}
                  </div>
                </div>
                <StatusBadge value={job.status} />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
