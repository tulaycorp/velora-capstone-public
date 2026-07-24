"use client";

import * as React from "react";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { StoreLabel, getStoreDisplayParts, groupAndSortStoreConnections } from "@/components/workspace/store-label";
import { useStoreContext } from "@/components/workspace/store-context";
import { providerLabel, type PodProviderKey } from "@/lib/backend-api";

export function StoreSwitcher() {
  const {
    selectedStoreId,
    setSelectedStoreId,
    selectedStore,
    storeConnections,
    loading
  } = useStoreContext();

  const groupedConnections = React.useMemo(() => {
    return groupAndSortStoreConnections(storeConnections);
  }, [storeConnections]);

  const selectedStoreName =
    selectedStoreId === "all"
      ? "All Stores"
      : selectedStore
        ? getStoreDisplayParts(selectedStore).name
        : "Choose store";

  return (
    <div className="flex w-full min-w-0 flex-col">
      <Select value={selectedStoreId} onValueChange={setSelectedStoreId} disabled={loading}>
        <SelectTrigger className="h-9 w-full bg-card text-sm font-medium">
          <SelectValue placeholder="Choose store">{selectedStoreName}</SelectValue>
        </SelectTrigger>
        <SelectContent className="border-border/80 bg-card max-h-[min(400px,var(--radix-select-content-available-height))]">
          <SelectItem value="all">All Stores</SelectItem>
          {Object.entries(groupedConnections).map(([provider, stores]) => (
            <SelectGroup key={provider}>
              <SelectSeparator />
              <SelectLabel className="text-muted-foreground">
                {providerLabel(provider as PodProviderKey)}
              </SelectLabel>
              {stores.map((store) => (
                <SelectItem key={store.id} value={store.id}>
                  <StoreLabel
                    source={store}
                    includeProvider={false}
                    secondaryClassName="text-[11px]"
                  />
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
