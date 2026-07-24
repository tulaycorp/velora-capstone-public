"use client";

import { Badge } from "@/components/ui/badge";
import {
  providerLabel,
  storefrontLabel,
  type Blueprint,
  type Product,
  type Order,
  type ProviderStoreConnection
} from "@/lib/backend-api";
import {
  cleanStoreDisplayName,
  splitStoreDisplayLabel,
} from "@/lib/store-display";
import { cn } from "@/lib/utils";

type StoreLabelSource =
  | Pick<
      ProviderStoreConnection,
      "label" | "provider" | "provider_store_id" | "storefront_display_name" | "storefront_type"
    >
  | Pick<Blueprint, "provider" | "provider_store_label" | "provider_storefront_type">
  | Pick<Product, "provider" | "provider_store_label" | "provider_storefront_type">
  | Pick<Order, "provider" | "provider_store_label" | "provider_storefront_type">;

type StoreLabelOptions = {
  includeProvider?: boolean;
  includeStorefront?: boolean;
};

function isKnownStorefrontType(value: string | null | undefined): value is "etsy" | "shopify" | "unknown" {
  return value === "etsy" || value === "shopify" || value === "unknown";
}

function isKnownProvider(value: string | null | undefined): value is "printify" | "gelato" {
  return value === "printify" || value === "gelato";
}

function readPrimaryStoreName(source: StoreLabelSource) {
  if ("provider_store_label" in source) {
    return cleanStoreDisplayName(source.provider_store_label);
  }

  return (
    cleanStoreDisplayName(source.label, "")
    || source.storefront_display_name.trim()
    || source.provider_store_id.trim()
    || "Unknown store"
  );
}

function readStorefrontName(source: StoreLabelSource) {
  if ("provider_storefront_type" in source) {
    if (
      isKnownStorefrontType(source.provider_storefront_type)
      && source.provider_storefront_type !== "unknown"
    ) {
      return storefrontLabel(source.provider_storefront_type);
    }

    const parsed = splitStoreDisplayLabel(source.provider_store_label);
    return parsed.relationship || null;
  }

  if (source.storefront_type !== "unknown") {
    return storefrontLabel(source.storefront_type);
  }

  const parsed = splitStoreDisplayLabel(source.label);
  return parsed.relationship || source.storefront_display_name.trim() || null;
}

export function getStoreDisplayParts(
  source: StoreLabelSource,
  options: StoreLabelOptions = {}
) {
  const includeProvider = options.includeProvider ?? false;
  const includeStorefront = options.includeStorefront ?? true;
  const metaParts: string[] = [];

  if (includeProvider) {
    metaParts.push(isKnownProvider(source.provider) ? providerLabel(source.provider) : source.provider);
  }

  if (includeStorefront) {
    const storefront = readStorefrontName(source);
    if (storefront) {
      metaParts.push(storefront);
    }
  }

  return {
    name: readPrimaryStoreName(source),
    meta: metaParts.join(" • ")
  };
}

export function StoreLabel({
  source,
  includeProvider = false,
  includeStorefront = true,
  secondaryVariant = "text",
  className,
  nameClassName,
  secondaryClassName
}: {
  source: StoreLabelSource;
  includeProvider?: boolean;
  includeStorefront?: boolean;
  secondaryVariant?: "text" | "badge";
  className?: string;
  nameClassName?: string;
  secondaryClassName?: string;
}) {
  const { name, meta } = getStoreDisplayParts(source, {
    includeProvider,
    includeStorefront
  });

  return (
    <div className={cn("min-w-0", className)}>
      <div className={cn("truncate text-sm font-medium text-foreground", nameClassName)}>
        {name}
      </div>
      {meta ? (
        secondaryVariant === "badge" ? (
          <Badge
            variant="outline"
            className={cn(
              "mt-1 inline-flex border-border bg-background/50 text-[11px] font-medium text-muted-foreground",
              secondaryClassName
            )}
          >
            {meta}
          </Badge>
        ) : (
          <div className={cn("mt-1 truncate text-xs text-muted-foreground", secondaryClassName)}>
            {meta}
          </div>
        )
      ) : null}
    </div>
  );
}

export function groupAndSortStoreConnections(storeConnections: ProviderStoreConnection[]) {
  const groups: Record<string, typeof storeConnections> = {};
  for (const store of storeConnections) {
    if (!groups[store.provider]) {
      groups[store.provider] = [];
    }
    groups[store.provider].push(store);
  }
  
  for (const group of Object.values(groups)) {
    group.sort((a, b) => {
      const aStorefront = a.storefront_display_name?.toLowerCase() || "";
      const bStorefront = b.storefront_display_name?.toLowerCase() || "";
      if (aStorefront !== bStorefront) {
        return aStorefront.localeCompare(bStorefront);
      }
      
      const aName = getStoreDisplayParts(a).name.toLowerCase();
      const bName = getStoreDisplayParts(b).name.toLowerCase();
      return aName.localeCompare(bName);
    });
  }
  
  return groups;
}
