"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  LoaderCircle,
  Pencil,
  Plus,
  Trash2
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { StoreLabel } from "@/components/workspace/store-label";
import { StatusBadge } from "@/components/workspace/status-badge";
import {
  formatDateTime,
  providerLabel,
  storefrontLabel,
  type ManualStoreSeed,
  type PodProvider,
  type PodProviderKey,
  type ProviderCredentialEntry,
  type ProviderCredentialStatus,
  type ProviderStoreConnection,
  type StorefrontType
} from "@/lib/backend-api";
import {
  createManualStoreSeed,
  formatStorefrontCount,
  groupStoreConnectionsByType,
  latestSyncedAt
} from "@/lib/organization-settings-state";
import { cn } from "@/lib/utils";

export function usePersistentState<T>(storageKey: string, initialValue: T) {
  const [state, setState] = useState<T>(initialValue);

  useEffect(() => {
    try {
      const savedValue = window.localStorage.getItem(storageKey);
      if (savedValue !== null) {
        setState(JSON.parse(savedValue) as T);
      }
    } catch {
      // Ignore malformed or unavailable local storage state.
    }
  }, [storageKey]);

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(state));
    } catch {
      // Ignore storage write failures.
    }
  }, [storageKey, state]);

  return [state, setState] as const;
}

export function SettingsSection({
  title,
  description,
  icon,
  children
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-md border border-border bg-card">
      <div className="border-b border-border px-5 py-4">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-base font-semibold text-foreground">{title}</h2>
        </div>
        {description ? (
          <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

export function InlineEmptyState({
  title,
  description
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-background/30 px-4 py-4">
      <div className="font-medium text-foreground">{title}</div>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

export function MetadataChip({
  label,
  value
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="inline-flex items-baseline gap-2">
      <span className="text-xs text-muted-foreground">
        {label}
      </span>
      <span className="text-sm font-medium text-foreground">{value}</span>
    </div>
  );
}

export function ProviderStatusBadge({
  isConfigured
}: {
  isConfigured: boolean;
}) {
  return (
    <Badge
      variant="outline"
      className={
        isConfigured
          ? "border-primary/25 bg-primary/10 text-primary"
          : "border-border bg-background/50 text-muted-foreground"
      }
    >
      {isConfigured ? "Ready" : "Needs setup"}
    </Badge>
  );
}

export function ProviderLogo({
  provider
}: {
  provider: PodProviderKey;
}) {
  const tones =
    provider === "printify"
      ? "border-[#2dd4bf]/25 bg-[#2dd4bf]/12 text-[#5eead4]"
      : "border-[#f97316]/25 bg-[#f97316]/12 text-[#fdba74]";

  return (
    <div
      className={cn(
        "flex size-9 items-center justify-center rounded-md border text-xs font-semibold tracking-[0.14em]",
        tones
      )}
      aria-hidden="true"
    >
      {provider === "printify" ? "PF" : "GL"}
    </div>
  );
}

export function ProviderSelectorCard({
  providerKey,
  provider,
  credentialStatus,
  storeCount,
  isSelected,
  onSelect,
  disabled
}: {
  providerKey: PodProviderKey;
  provider: PodProvider | null;
  credentialStatus: ProviderCredentialStatus;
  storeCount: number;
  isSelected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}) {
  const providerName = provider?.name ?? providerLabel(providerKey);

  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      className={cn(
        "rounded-md border bg-background/20 px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-65",
        isSelected ? "border-primary/35 bg-primary/5" : "border-border hover:border-border/80",
        disabled && "hover:border-border"
      )}
      aria-pressed={isSelected}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <ProviderLogo provider={providerKey} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <div className="font-semibold text-foreground">{providerName}</div>
              <ProviderStatusBadge isConfigured={credentialStatus.is_configured} />
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              {storeCount === 0 ? "No stores connected" : formatStorefrontCount(storeCount)}
            </div>
          </div>
        </div>

        <span
          className={cn(
            "text-xs font-medium",
            disabled || !isSelected ? "text-muted-foreground" : "text-primary"
          )}
        >
          {disabled ? "Connect Etsy first" : isSelected ? "Selected" : "Select"}
        </span>
      </div>
    </button>
  );
}

function StorefrontCard({
  connection,
  isDeleting,
  onDelete,
  onEdit,
  isEditingEtsyShopId,
  etsyShopIdDraft,
  isSavingEtsyShopId,
  onStartEditEtsyShopId,
  onCancelEditEtsyShopId,
  onChangeEtsyShopIdDraft,
  onSaveEtsyShopId
}: {
  connection: ProviderStoreConnection;
  isDeleting: boolean;
  onDelete: () => void;
  onEdit?: () => void;
  isEditingEtsyShopId?: boolean;
  etsyShopIdDraft?: string;
  isSavingEtsyShopId?: boolean;
  onStartEditEtsyShopId?: () => void;
  onCancelEditEtsyShopId?: () => void;
  onChangeEtsyShopIdDraft?: (value: string) => void;
  onSaveEtsyShopId?: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <StoreLabel
            source={connection}
            includeStorefront={false}
            className="flex-1"
            nameClassName="text-base"
          />
          <StatusBadge value={connection.status} />
        </div>

        <div className="mt-2 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="text-xs">Updated</span>
            <span className="text-foreground">{formatDateTime(connection.last_sync_at)}</span>
          </div>
        </div>

        {connection.storefront_type === "etsy" ? (
          <div className="mt-3 border-t border-border/60 pt-3">
            {isEditingEtsyShopId ? (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-muted-foreground">Etsy shop ID</div>
                  <Input
                    value={etsyShopIdDraft ?? ""}
                    onChange={(event) => onChangeEtsyShopIdDraft?.(event.target.value)}
                    placeholder="Paste the Etsy shop ID"
                    className="mt-2 max-w-sm"
                    disabled={isSavingEtsyShopId}
                  />
                  <p className="mt-2 text-xs text-muted-foreground">
                    Enter the Etsy shop ID for this store.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={onCancelEditEtsyShopId}
                    disabled={isSavingEtsyShopId}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={onSaveEtsyShopId}
                    disabled={isSavingEtsyShopId}
                  >
                    {isSavingEtsyShopId ? <LoaderCircle className="animate-spin" /> : null}
                    Save
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="text-xs font-medium text-muted-foreground">Etsy listing updates</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <StatusBadge value={connection.etsy_shop_id ? "Ready" : "Needs setup"} />
                    <span className="text-xs text-muted-foreground">
                      {connection.etsy_shop_id
                        ? "This store is ready for Etsy listing updates."
                        : "Set this up to route Etsy listing updates here."}
                    </span>
                  </div>
                </div>

                {onStartEditEtsyShopId ? (
                  <Button type="button" variant="outline" size="sm" onClick={onStartEditEtsyShopId}>
                    {connection.etsy_shop_id ? "Edit" : "Set up"}
                  </Button>
                ) : null}
              </div>
            )}
          </div>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        {onEdit ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={onEdit}
            disabled={isDeleting}
            aria-label="Edit store connection"
          >
            <Pencil className="h-4 w-4" />
          </Button>
        ) : null}
        <Button
          variant="ghost"
          size="sm"
          onClick={onDelete}
          disabled={isDeleting}
          aria-label="Delete store connection"
        >
          {isDeleting ? <LoaderCircle className="animate-spin" /> : <Trash2 className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  );
}

function StorefrontGroups({
  storageKey,
  connections,
  emptyTitle,
  emptyDescription,
  deletingStoreId,
  onDelete,
  onEdit,
  editingEtsyConnectionId,
  editingEtsyShopIdDraft,
  savingEtsyConnectionId,
  onStartEditEtsyShopId,
  onCancelEditEtsyShopId,
  onChangeEtsyShopIdDraft,
  onSaveEtsyShopId
}: {
  storageKey: string;
  connections: ProviderStoreConnection[];
  emptyTitle: string;
  emptyDescription: string;
  deletingStoreId: string | null;
  onDelete: (connectionId: string) => void;
  onEdit?: (connection: ProviderStoreConnection) => void;
  editingEtsyConnectionId: string | null;
  editingEtsyShopIdDraft: string;
  savingEtsyConnectionId: string | null;
  onStartEditEtsyShopId: (connection: ProviderStoreConnection) => void;
  onCancelEditEtsyShopId: () => void;
  onChangeEtsyShopIdDraft: (value: string) => void;
  onSaveEtsyShopId: (connection: ProviderStoreConnection) => void;
}) {
  const storefrontGroups = useMemo(() => groupStoreConnectionsByType(connections), [connections]);
  const [expandedGroups, setExpandedGroups] = usePersistentState<
    ManualStoreSeed["storefront_type"][] | null
  >(`velora.settings.storefront-groups.${storageKey}`, null);

  useEffect(() => {
    if (storefrontGroups.length === 0) {
      return;
    }

      setExpandedGroups((current) => {
      if (current === null) {
        return storefrontGroups.map((group) => group.key);
      }

      const validKeys = new Set(storefrontGroups.map((group) => group.key));
      const next = current.filter((key) => validKeys.has(key));
      if (next.length === current.length && next.every((key, index) => key === current[index])) {
        return current;
      }
      if (next.length > 0 || current.length === 0) {
        return next;
      }
      return current;
    });
  }, [setExpandedGroups, storefrontGroups]);

  if (connections.length === 0) {
    return <InlineEmptyState title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <div className="divide-y divide-border/70">
      {storefrontGroups.map((group, index) => {
        const isExpanded = expandedGroups?.includes(group.key) ?? true;

        return (
          <div key={group.key} className={cn(index > 0 && "pt-1")}>
            <button
              type="button"
              onClick={() =>
                setExpandedGroups((current) =>
                  (current ?? storefrontGroups.map((item) => item.key)).includes(group.key)
                    ? (current ?? storefrontGroups.map((item) => item.key)).filter((key) => key !== group.key)
                    : [...(current ?? storefrontGroups.map((item) => item.key)), group.key]
                )
              }
              className="flex w-full items-center justify-between gap-3 py-3 text-left"
              aria-expanded={isExpanded}
            >
              <div className="flex items-center gap-3">
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    isExpanded && "rotate-180"
                  )}
                />
                <div className="font-medium text-foreground">{group.title}</div>
              </div>
              <div className="text-sm text-muted-foreground">
                {formatStorefrontCount(group.connections.length)}
              </div>
            </button>

            {isExpanded ? (
              <div className="divide-y divide-border/70">
                {group.connections.map((connection) => (
                  <StorefrontCard
                    key={connection.id}
                    connection={connection}
                    isDeleting={deletingStoreId === connection.id}
                    onDelete={() => onDelete(connection.id)}
                    onEdit={onEdit ? () => onEdit(connection) : undefined}
                    isEditingEtsyShopId={editingEtsyConnectionId === connection.id}
                    etsyShopIdDraft={editingEtsyShopIdDraft}
                    isSavingEtsyShopId={savingEtsyConnectionId === connection.id}
                    onStartEditEtsyShopId={() => onStartEditEtsyShopId(connection)}
                    onCancelEditEtsyShopId={onCancelEditEtsyShopId}
                    onChangeEtsyShopIdDraft={onChangeEtsyShopIdDraft}
                    onSaveEtsyShopId={() => onSaveEtsyShopId(connection)}
                  />
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function CredentialCard({
  provider,
  credential,
  connections,
  setupLocked,
  isSyncing,
  isDeleting,
  deletingStoreId,
  onSync,
  onDelete,
  onDeleteStore,
  onAddStore,
  onEditStore,
  editingEtsyConnectionId,
  editingEtsyShopIdDraft,
  savingEtsyConnectionId,
  onStartEditEtsyShopId,
  onCancelEditEtsyShopId,
  onChangeEtsyShopIdDraft,
  onSaveEtsyShopId
}: {
  provider: PodProviderKey;
  credential: ProviderCredentialEntry;
  connections: ProviderStoreConnection[];
  setupLocked: boolean;
  isSyncing: boolean;
  isDeleting: boolean;
  deletingStoreId: string | null;
  onSync: () => void;
  onDelete: () => void;
  onDeleteStore: (connectionId: string) => void;
  onAddStore?: () => void;
  onEditStore?: (connection: ProviderStoreConnection) => void;
  editingEtsyConnectionId: string | null;
  editingEtsyShopIdDraft: string;
  savingEtsyConnectionId: string | null;
  onStartEditEtsyShopId: (connection: ProviderStoreConnection) => void;
  onCancelEditEtsyShopId: () => void;
  onChangeEtsyShopIdDraft: (value: string) => void;
  onSaveEtsyShopId: (connection: ProviderStoreConnection) => void;
}) {
  const canSync = credential.missing_keys.length === 0;
  const storeCount = connections.length;
  const [isExpanded, setIsExpanded] = usePersistentState<boolean>(
    `velora.settings.token-expanded.${provider}.${credential.credential_key}`,
    true
  );
  const helperText =
    credential.missing_keys.length > 0
      ? "Add the missing access key to use this connection."
      : null;

  return (
    <div className="border-t border-border/70 pt-4 first:border-t-0 first:pt-0">
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => setIsExpanded((current) => !current)}
          className="min-w-0 flex-1 text-left"
          aria-expanded={isExpanded}
        >
          <div className="flex flex-wrap items-center gap-2">
            <ChevronDown
              className={cn(
                "h-4 w-4 text-muted-foreground transition-transform",
                isExpanded && "rotate-180"
              )}
            />
            <div className="font-semibold text-foreground">
              {credential.credential_display_name ?? "Connection"}
            </div>
            <Badge
              variant="outline"
              className={
                helperText
                  ? "border-border bg-background/50 text-muted-foreground"
                  : "border-primary/25 bg-primary/10 text-primary"
              }
            >
              {helperText ? "Needs setup" : "Ready"}
            </Badge>
          </div>

          <div className="mt-2 text-xs text-muted-foreground">
            {storeCount === 0 ? "No stores connected" : formatStorefrontCount(storeCount)}
            {" · Updated "}
            {formatDateTime(latestSyncedAt(connections))}
          </div>

          {helperText ? (
            <p className="mt-2 text-sm text-muted-foreground">{helperText}</p>
          ) : null}
        </button>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onSync}
            disabled={setupLocked || !canSync || isSyncing}
          >
            {isSyncing ? <LoaderCircle className="animate-spin" /> : null}
            Refresh stores
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDelete}
            disabled={isDeleting}
            aria-label="Remove connection"
          >
            {isDeleting ? <LoaderCircle className="animate-spin" /> : <Trash2 className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {isExpanded ? (
        <div className="mt-4 border-t border-border/70 pt-4">
          {provider === "gelato" && onAddStore ? (
            <div className="mb-4 flex justify-end">
              <Button type="button" variant="outline" size="sm" onClick={onAddStore} disabled={setupLocked}>
                <Plus className="mr-2 h-4 w-4" data-icon="inline-start" /> Add store
              </Button>
            </div>
          ) : null}

          <StorefrontGroups
            storageKey={`${provider}.${credential.credential_key}`}
            connections={connections}
            emptyTitle="No stores loaded"
            emptyDescription={
              canSync
                ? provider === "gelato"
                  ? "Refresh to find stores from Gelato. Add one manually if it has no recent orders."
                  : "Refresh to find connected stores."
                : "Add the access key before refreshing stores."
            }
            deletingStoreId={deletingStoreId}
            onDelete={onDeleteStore}
            onEdit={onEditStore}
            editingEtsyConnectionId={editingEtsyConnectionId}
            editingEtsyShopIdDraft={editingEtsyShopIdDraft}
            savingEtsyConnectionId={savingEtsyConnectionId}
            onStartEditEtsyShopId={onStartEditEtsyShopId}
            onCancelEditEtsyShopId={onCancelEditEtsyShopId}
            onChangeEtsyShopIdDraft={onChangeEtsyShopIdDraft}
            onSaveEtsyShopId={onSaveEtsyShopId}
          />
        </div>
      ) : null}
    </div>
  );
}

export function StoreConnectionDialog({
  open,
  onOpenChange,
  initialSeed,
  storefrontOptions,
  etsyStoreProjectedCount,
  etsyStoreLimit,
  onSave
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSeed: ManualStoreSeed | null;
  storefrontOptions: StorefrontType[];
  etsyStoreProjectedCount: number;
  etsyStoreLimit: number;
  onSave: (seed: ManualStoreSeed) => Promise<void>;
}) {
  const [seed, setSeed] = useState<ManualStoreSeed>(() =>
    initialSeed ?? createManualStoreSeed()
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isEdit = !!initialSeed;
  const isEditingExistingEtsyStore = initialSeed?.storefront_type === "etsy";
  const etsyStoreCapacityReached =
    etsyStoreProjectedCount >= etsyStoreLimit && !isEditingExistingEtsyStore;

  useEffect(() => {
    if (open) {
      const nextSeed = initialSeed ?? createManualStoreSeed();
      if (!initialSeed && etsyStoreCapacityReached && nextSeed.storefront_type === "etsy") {
        const fallbackStorefrontType = storefrontOptions.find((option) => option !== "etsy");
        if (fallbackStorefrontType) {
          nextSeed.storefront_type = fallbackStorefrontType;
          nextSeed.storefront_display_name = storefrontLabel(fallbackStorefrontType);
        }
      }
      setSeed(nextSeed);
      setError(null);
    }
  }, [etsyStoreCapacityReached, initialSeed, open, storefrontOptions]);

  async function handleSave() {
    if (!seed.provider_store_id.trim()) {
      setError("Enter a store ID.");
      return;
    }
    if (seed.storefront_type === "etsy" && etsyStoreCapacityReached) {
      setError("You already have the maximum number of Etsy stores. Remove one before adding another.");
      return;
    }
    if (seed.storefront_type === "etsy" && !seed.label?.trim()) {
      setError("Add a name for this Etsy store.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(seed);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save this store.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit store" : "Add store"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update this store's details."
              : "Add a store from this partner."}
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="store-code">Store ID</Label>
            <Input
              id="store-code"
              value={seed.provider_store_id}
              onChange={(e) =>
                setSeed((current) => ({ ...current, provider_store_id: e.target.value }))
              }
              disabled={isEdit}
              placeholder="Enter the store ID"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="store-type">Sales channel</Label>
            <Select
              value={seed.storefront_type}
              onValueChange={(val) =>
                setSeed((current) => ({
                  ...current,
                  storefront_type: val as StorefrontType,
                  storefront_display_name: storefrontLabel(val as StorefrontType)
                }))
              }
              disabled={isEdit}
            >
              <SelectTrigger id="store-type">
                <SelectValue placeholder="Select channel" />
              </SelectTrigger>
              <SelectContent>
                {storefrontOptions.map((opt) => (
                  <SelectItem
                    key={opt}
                    value={opt}
                    disabled={opt === "etsy" && etsyStoreCapacityReached}
                  >
                    {storefrontLabel(opt)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {etsyStoreCapacityReached ? (
              <p className="text-xs text-muted-foreground">
                You already have the maximum number of Etsy stores. Remove one before adding another.
              </p>
            ) : null}
          </div>

          <div className="grid gap-2">
            <Label htmlFor="store-name">Store name</Label>
            <Input
              id="store-name"
              value={seed.label ?? ""}
              onChange={(e) =>
                setSeed((current) => ({ ...current, label: e.target.value || null }))
              }
              placeholder="e.g., My Awesome Etsy Shop"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? <LoaderCircle className="animate-spin mr-2 h-4 w-4" /> : null}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
