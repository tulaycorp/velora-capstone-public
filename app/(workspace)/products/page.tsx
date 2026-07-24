"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import {
  ArrowUpRight,
  ExternalLink,
  ImageIcon,
  PlusCircle,
  RefreshCw
} from "lucide-react";
import { DeleteProductDialog } from "@/components/workspace/delete-product-dialog";
import { PageHeader } from "@/components/workspace/page-header";
import {
  EmptyState,
  ResourceError,
  ProductsSkeleton
} from "@/components/workspace/resource-state";
import { getStoreDisplayParts } from "@/components/workspace/store-label";
import { StatusBadge } from "@/components/workspace/status-badge";
import { useStoreContext } from "@/components/workspace/store-context";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import {
  fetchProducts,
  formatCurrency,
  providerLabel,
  storefrontActionLabel,
  storefrontLabel,
  type Product
} from "@/lib/backend-api";
import { workspacePageCacheKeys } from "@/lib/workspace-page-cache-keys";
import { cn } from "@/lib/utils";
import { useCachedWorkspaceResource } from "@/hooks/use-cached-workspace-resource";
import { useRefetchOnWindowFocus } from "@/hooks/use-refetch-on-window-focus";

type ProductSection = "drafts" | "published";

function productHeroUrl(product: Product) {
  return product.mockups
    .slice()
    .sort((left, right) => left.position - right.position)
    .find((mockup) => mockup.public_url)?.public_url
    ?? product.design_asset?.public_url
    ?? null;
}

function ProductHero({ product }: { product: Product }) {
  const heroUrl = productHeroUrl(product);

  return (
    <div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded-md border border-border bg-background">
      {heroUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={heroUrl}
          alt=""
          className="h-full w-full object-cover"
        />
      ) : (
        <ImageIcon className="h-5 w-5 text-muted-foreground" />
      )}
    </div>
  );
}

function CatalogTabs({
  activeSection,
  draftCount,
  publishedCount,
  onChange
}: {
  activeSection: ProductSection;
  draftCount: number;
  publishedCount: number;
  onChange: (section: ProductSection) => void;
}) {
  const tabs: Array<{ id: ProductSection; label: string; count: number }> = [
    { id: "published", label: "Published", count: publishedCount },
    { id: "drafts", label: "Drafts", count: draftCount }
  ];

  return (
    <div className="inline-flex gap-1.5 rounded-md border border-border bg-background p-1.5">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={cn(
            "inline-flex h-9 items-center gap-2 rounded px-3 text-sm font-medium transition-colors",
            activeSection === tab.id
              ? "bg-primary text-primary-foreground"
              : "border border-border bg-background/50 text-muted-foreground hover:text-foreground hover:bg-muted/50"
          )}
        >
          <span>{tab.label}</span>
          <span
            className={cn(
              "min-w-5 rounded border px-1.5 py-0.5 text-xs",
              activeSection === tab.id
                ? "border-primary-foreground/20 bg-primary-foreground/15 text-primary-foreground"
                : "border-border bg-background text-muted-foreground"
            )}
          >
            {tab.count}
          </span>
        </button>
      ))}
    </div>
  );
}

function ProductsTable({
  products,
  onProductDeleted
}: {
  products: Product[];
  onProductDeleted: (productId: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <Table className="table-fixed">
        <TableHeader className="bg-muted/55">
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-11 w-[8%] min-w-0 px-4 text-xs font-semibold" />
            <TableHead className="h-11 w-[26%] min-w-0 px-4 text-xs font-semibold">
              Title
            </TableHead>
            <TableHead className="h-11 w-[10%] min-w-0 px-4 text-xs font-semibold">
              SKU
            </TableHead>
            <TableHead className="h-11 w-[17%] min-w-0 px-4 text-xs font-semibold">
              Store
            </TableHead>
            <TableHead className="h-11 w-[24%] min-w-0 px-4 text-xs font-semibold">
              Product
            </TableHead>
            <TableHead className="h-11 w-[15%] min-w-0 px-4 text-center text-xs font-semibold">
              Actions
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {products.map((product) => {
            const store = getStoreDisplayParts(product, {
              includeProvider: true,
              includeStorefront: true
            });
            const storefront = storefrontLabel(product.provider_storefront_type);
            const pushTarget = storefrontActionLabel(product.provider_storefront_type);
            const productHref = `/products/${product.id}`;

            return (
              <TableRow
                key={product.id}
                className="border-border hover:bg-muted/35"
              >
                <TableCell className="h-[78px] min-w-0 max-w-0 overflow-hidden px-4 py-3">
                  <Link href={productHref} aria-label={`Open ${product.title}`}>
                    <ProductHero product={product} />
                  </Link>
                </TableCell>
                <TableCell className="h-[78px] min-w-0 max-w-0 overflow-hidden px-4 py-3">
                  <div className="min-w-0">
                    <Link
                      href={productHref}
                      className="group flex min-w-0 max-w-full items-center gap-2 text-sm font-semibold text-foreground hover:text-primary"
                    >
                      <span className="min-w-0 flex-1 truncate">{product.title}</span>
                      <ArrowUpRight className="h-4 w-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                    </Link>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span>{product.mockup_count} images</span>
                      <span>•</span>
                      <span>{formatCurrency(product.retail_price, product.currency ?? "USD")}</span>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="h-[78px] min-w-0 max-w-0 overflow-hidden px-4 py-3">
                  <div className="font-medium text-foreground">
                    {product.sku ?? "No SKU"}
                  </div>
                </TableCell>
                <TableCell className="h-[78px] min-w-0 max-w-0 overflow-hidden px-4 py-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-foreground">
                      {store.name}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {store.meta || storefront}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="h-[78px] min-w-0 max-w-0 overflow-hidden px-4 py-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-foreground">
                      {product.product_type}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <StatusBadge value={product.status} />
                      <span className="text-xs text-muted-foreground">
                        {providerLabel(product.provider)}
                      </span>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="h-[78px] min-w-0 max-w-0 overflow-hidden px-4 py-3 text-center">
                  <div className="flex flex-wrap items-center justify-center gap-2">
                    <DeleteProductDialog
                      productId={product.id}
                      productTitle={product.title}
                      buttonLabel="Delete"
                      ariaLabel={`Delete ${product.title} from Velora`}
                      className="h-9 w-9"
                      hasProviderRecord={Boolean(product.provider_product_id || product.external_listing_id)}
                      iconOnly
                      onDeleted={onProductDeleted}
                    />
                    {product.provider_product_url ? (
                      <Button asChild variant="outline" size="sm">
                        <a href={product.provider_product_url} target="_blank" rel="noreferrer">
                          <ExternalLink className="h-4 w-4" />
                          {pushTarget}
                        </a>
                      </Button>
                    ) : null}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export default function ProductsPage() {
  const { selectedStoreId } = useStoreContext();
  const [activeSection, setActiveSection] = useState<ProductSection>("published");
  const {
    data: productsData,
    error,
    isCacheFresh,
    load,
    loading,
    setData: setProducts
  } = useCachedWorkspaceResource<Product[]>({
    cacheKey: workspacePageCacheKeys.products(),
    loadResource: fetchProducts
  });

  useRefetchOnWindowFocus(
    useCallback(async () => {
      await load("background", "if-stale");
    }, [load]),
    { shouldRefetch: () => !isCacheFresh() }
  );

  const products = useMemo(() => productsData ?? [], [productsData]);

  function handleProductDeleted(productId: string) {
    setProducts((current) =>
      current?.filter((product) => product.id !== productId) ?? current
    );
  }

  const filteredProducts = useMemo(
    () =>
      selectedStoreId === "all"
        ? products
        : products.filter(
            (product) => product.provider_store_connection_id === selectedStoreId
          ),
    [products, selectedStoreId]
  );

  const draftProducts = filteredProducts.filter((product) => product.status !== "published");
  const publishedProducts = filteredProducts.filter((product) => product.status === "published");
  const visibleProducts =
    activeSection === "drafts" ? draftProducts : publishedProducts;

  if (loading) {
    return (
      <>
        <PageHeader
          title="Products"
          description="Drafts and published products for the active store."
          preserveActionSpace
        />
        <ProductsSkeleton />
      </>
    );
  }

  if (error) {
    return (
      <>
        <PageHeader
          title="Products"
          description="Drafts and published products for the active store."
          preserveActionSpace
        />
        <ResourceError message={error} onRetry={() => void load()} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Products"
        description="Edit saved drafts or review products already sent to your store."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw data-icon="inline-start" />
              Refresh
            </Button>
            <Button asChild>
              <Link href="/product-studio">
                <PlusCircle data-icon="inline-start" />
                New product
              </Link>
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <CatalogTabs
          activeSection={activeSection}
          draftCount={draftProducts.length}
          publishedCount={publishedProducts.length}
          onChange={setActiveSection}
        />
        <div className="text-sm text-muted-foreground">
          {visibleProducts.length} {visibleProducts.length === 1 ? "product" : "products"}
        </div>
      </div>

      {visibleProducts.length === 0 ? (
        <EmptyState
          title={
            activeSection === "drafts"
              ? "No saved drafts in this store"
              : "No published products in this store"
          }
          description={
            activeSection === "drafts"
              ? "Save a draft from Product Studio to keep editing it later."
              : "Published products appear here after you send them to a store."
          }
          action={
            <Button asChild className="w-fit">
              <Link href="/product-studio">Open Product Studio</Link>
            </Button>
          }
        />
      ) : (
        <ProductsTable products={visibleProducts} onProductDeleted={handleProductDeleted} />
      )}
    </>
  );
}
