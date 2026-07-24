"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Layers3,
  LoaderCircle,
  RefreshCw,
  Trash2
} from "lucide-react";
import { PageHeader } from "@/components/workspace/page-header";
import {
  EmptyState,
  ResourceError,
  BlueprintsSkeleton
} from "@/components/workspace/resource-state";
import {
  StoreLabel,
  getStoreDisplayParts,
  groupAndSortStoreConnections
} from "@/components/workspace/store-label";
import { StatusBadge } from "@/components/workspace/status-badge";
import { useStoreContext } from "@/components/workspace/store-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  createBlueprint,
  deleteBlueprint,
  fetchBlueprints,
  formatCurrency,
  formatDateTime,
  providerLabel,
  storefrontLabel,
  type Blueprint,
  type BlueprintCreateInput,
  updateBlueprint,
  validateBlueprint
} from "@/lib/backend-api";
import {
  formatBlueprintArtworkSummary,
  formatBlueprintProductType,
  formatBlueprintVariantSummary,
  getBlueprintCardSubtitle,
  getBlueprintCardTitle,
  getRawBlueprintArtworkSummary
} from "@/lib/blueprint-display";
import { workspacePageCacheKeys } from "@/lib/workspace-page-cache-keys";
import {
  useCachedWorkspaceResource,
  type CachedWorkspaceLoadMode
} from "@/hooks/use-cached-workspace-resource";
import { useRefetchOnWindowFocus } from "@/hooks/use-refetch-on-window-focus";

const defaultFormState = {
  name: "",
  category: "",
  provider_store_connection_id: "",
  reference_value: "",
  product_code: "",
  base_title: "",
  base_description: "",
  base_tags: "",
  gelato_placeholder_name: ""
};

function formatCount(value: number, singular: string, plural = `${singular}s`) {
  return `${value} ${value === 1 ? singular : plural}`;
}

function readGelatoPlaceholderName(blueprint: Blueprint | null) {
  const config = blueprint?.placement_config_json;
  if (!config || typeof config !== "object") {
    return "";
  }

  const directValue = config.design_placeholder_name;
  if (typeof directValue === "string") {
    return directValue;
  }

  const candidateList = config.design_placeholder_names;
  if (!Array.isArray(candidateList)) {
    return "";
  }

  const firstValue = candidateList.find((value) => typeof value === "string" && value.trim());
  return typeof firstValue === "string" ? firstValue : "";
}

function buildBlueprintFormState({
  blueprint,
  defaultConnectionId
}: {
  blueprint: Blueprint | null;
  defaultConnectionId: string;
}) {
  return {
    name: blueprint?.name ?? "",
    category: blueprint?.category ?? "",
    provider_store_connection_id: blueprint?.provider_store_connection_id ?? defaultConnectionId,
    reference_value: blueprint?.reference_value ?? "",
    product_code: blueprint?.product_code ?? "",
    base_title: blueprint?.base_title ?? "",
    base_description: blueprint?.base_description ?? "",
    base_tags: (blueprint?.base_tags ?? []).join(", "),
    gelato_placeholder_name: readGelatoPlaceholderName(blueprint)
  };
}

export default function BlueprintsPage() {
  const { selectedStoreId, storeConnections } = useStoreContext();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "configure">("create");
  const [activeBlueprintId, setActiveBlueprintId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshingBlueprintId, setRefreshingBlueprintId] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formState, setFormState] = useState(defaultFormState);
  const {
    data: blueprintsData,
    error,
    isCacheFresh,
    load,
    loading,
    setData: setBlueprints
  } = useCachedWorkspaceResource<Blueprint[]>({
    cacheKey: workspacePageCacheKeys.blueprints(),
    loadResource: fetchBlueprints
  });
  const blueprints = blueprintsData ?? [];

  const filteredBlueprints =
    selectedStoreId === "all"
      ? blueprints
      : blueprints.filter(
          (blueprint) => blueprint.provider_store_connection_id === selectedStoreId
        );

  const defaultConnectionId =
    selectedStoreId !== "all" ? selectedStoreId : (storeConnections[0]?.id ?? "");

  const activeBlueprint =
    blueprints.find((blueprint) => blueprint.id === activeBlueprintId) ?? null;

  const selectedConnection =
    storeConnections.find(
      (connection) => connection.id === formState.provider_store_connection_id
    ) ?? null;

  const selectedProvider = selectedConnection?.provider ?? null;

  const groupedConnections = useMemo(() => {
    return groupAndSortStoreConnections(storeConnections);
  }, [storeConnections]);

  const loadBlueprints = useCallback(
    async (mode: CachedWorkspaceLoadMode = "blocking") => {
      setPageError(null);
      await load(mode);
    },
    [load]
  );

  useRefetchOnWindowFocus(
    useCallback(async () => {
      await load("background", "if-stale");
    }, [load]),
    {
      enabled: !dialogOpen && !submitting && refreshingBlueprintId === null,
      shouldRefetch: () => !isCacheFresh()
    }
  );

  function handleDialogChange(nextOpen: boolean) {
    setDialogOpen(nextOpen);
    if (!nextOpen) {
      setPageError(null);
      setFormError(null);
      setSubmitting(false);
      setRefreshingBlueprintId(null);
      setActiveBlueprintId(null);
      setDialogMode("create");
      setFormState(buildBlueprintFormState({ blueprint: null, defaultConnectionId }));
    }
  }

  function openCreateDialog() {
    setDialogMode("create");
    setActiveBlueprintId(null);
    setFormError(null);
    setFormState(buildBlueprintFormState({ blueprint: null, defaultConnectionId }));
    setDialogOpen(true);
  }

  function openConfigureDialog(blueprint: Blueprint) {
    setDialogMode("configure");
    setActiveBlueprintId(blueprint.id);
    setFormError(null);
    setFormState(
      buildBlueprintFormState({
        blueprint,
        defaultConnectionId: blueprint.provider_store_connection_id
      })
    );
    setDialogOpen(true);
  }

  async function handleSubmitBlueprint() {
    if (!selectedConnection) {
      setFormError("Choose a store before saving this blueprint.");
      return;
    }

    setSubmitting(true);
    setFormError(null);

    const payload: BlueprintCreateInput = {
      name: formState.name.trim(),
      category: formState.category.trim(),
      provider_store_connection_id: selectedConnection.id,
      reference_type:
        selectedConnection.provider === "printify"
          ? "printify_product_url"
          : "gelato_template_id",
      reference_value: formState.reference_value.trim(),
      product_code: formState.product_code.trim() || null,
      base_title: formState.base_title.trim() || null,
      base_description: formState.base_description.trim() || null,
      base_tags: formState.base_tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      placement_config_json:
        selectedConnection.provider === "gelato"
          ? (
              formState.gelato_placeholder_name.trim()
                ? {
                    design_placeholder_name: formState.gelato_placeholder_name.trim(),
                    design_placeholder_names: [formState.gelato_placeholder_name.trim()]
                  }
                : {}
            )
          : null
    };

    try {
      if (dialogMode === "create") {
        const createdBlueprint = await createBlueprint(payload);
        await validateBlueprint(createdBlueprint.id);
      } else if (activeBlueprint) {
        await updateBlueprint(activeBlueprint.id, {
          name: payload.name,
          category: payload.category,
          product_code: payload.product_code ?? null,
          placement_config_json:
            selectedConnection.provider === "gelato" ? payload.placement_config_json ?? {} : undefined,
          base_title: payload.base_title ?? null,
          base_description: payload.base_description ?? null,
          base_tags: payload.base_tags
        });
      }

      handleDialogChange(false);
      await loadBlueprints();
    } catch (createError) {
      setFormError(
        createError instanceof Error
          ? createError.message
          : dialogMode === "create"
            ? "Unable to create blueprint."
            : "Unable to update blueprint."
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRefreshBlueprint(blueprintId: string) {
    try {
      setRefreshingBlueprintId(blueprintId);
      await validateBlueprint(blueprintId);
      await loadBlueprints();
    } catch (validationError) {
      setPageError(
        validationError instanceof Error
          ? validationError.message
          : "Unable to refresh blueprint details."
      );
    } finally {
      setRefreshingBlueprintId(null);
    }
  }

  async function handleDelete(blueprintId: string) {
    try {
      await deleteBlueprint(blueprintId);
      handleDialogChange(false);
      await loadBlueprints();
    } catch (deleteError) {
      setPageError(
        deleteError instanceof Error
          ? deleteError.message
          : "Unable to delete blueprint."
      );
    }
  }

  if (loading) {
    return (
      <>
        <PageHeader
          title="Blueprints"
          description="Reusable product setups for each connected store."
          preserveActionSpace
        />
        <BlueprintsSkeleton />
      </>
    );
  }

  if (error || pageError) {
    return (
      <>
        <PageHeader
          title="Blueprints"
          description="Reusable product setups for each connected store."
          preserveActionSpace
        />
        <ResourceError
          message={pageError ?? error ?? "Unable to load product blueprints."}
          onRetry={() => void loadBlueprints()}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Blueprints"
        description="Reusable product setups for each connected store."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => void loadBlueprints()}>
              <RefreshCw data-icon="inline-start" />
              Refresh
            </Button>
            <Button
              onClick={openCreateDialog}
              disabled={storeConnections.length === 0}
            >
              <Layers3 data-icon="inline-start" />
              Create blueprint
            </Button>
          </div>
        }
      />

      <div className="mt-5">
        {storeConnections.length === 0 ? (
          <EmptyState
            title="No stores connected yet"
            description="Add a partner key and load at least one store in Settings before creating blueprints."
            action={
              <Button asChild className="w-fit">
                <Link href="/settings">Open Settings</Link>
              </Button>
            }
          />
        ) : filteredBlueprints.length === 0 ? (
          <EmptyState
            title="No blueprints in this store"
            description="Create your first blueprint to start building products for this store."
            action={
              <Button className="w-fit" onClick={openCreateDialog}>
                Create blueprint
              </Button>
            }
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-border bg-card">
            <Table>
              <TableHeader className="bg-muted/40 text-muted-foreground">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[30%]">Blueprint</TableHead>
                  <TableHead className="w-[20%]">Store</TableHead>
                  <TableHead className="w-[26%]">Base product</TableHead>
                  <TableHead className="w-[14%]">Code</TableHead>
                  <TableHead className="w-[10%] text-left">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredBlueprints.map((row) => (
                  <TableRow key={row.id} className="hover:bg-muted/20">
                    <TableCell className="align-top">
                      <div className="max-w-[180px] sm:max-w-[220px] md:max-w-[260px] lg:max-w-[320px] xl:max-w-[400px]">
                        <div className="truncate font-semibold text-foreground" title={row.name}>{row.name}</div>
                        <div className="mt-1 truncate text-sm text-muted-foreground" title={`${row.category || "Uncategorized"} • ${formatBlueprintProductType(row)}`}>
                          {row.category || "Uncategorized"}
                          {" • "}
                          {formatBlueprintProductType(row)}
                        </div>
                        <div className="mt-2 truncate text-xs text-muted-foreground">
                          {formatCount(row.draft_count, "draft")}
                          {" • "}
                          Updated {formatDateTime(row.updated_at)}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="align-top">
                      <div className="max-w-[140px] sm:max-w-[160px] md:max-w-[200px] lg:max-w-[240px]">
                        <StoreLabel
                          source={row}
                          includeProvider
                          nameClassName="truncate text-base"
                          secondaryClassName="truncate text-sm"
                        />
                      </div>
                    </TableCell>
                    <TableCell className="align-top">
                      <div className="max-w-[160px] sm:max-w-[200px] md:max-w-[240px] lg:max-w-[300px]">
                        <div className="truncate font-medium text-foreground" title={getBlueprintCardSubtitle(row)}>
                          {getBlueprintCardSubtitle(row)}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap break-words">
                          {formatBlueprintVariantSummary(row)}
                          {" • "}
                          {getRawBlueprintArtworkSummary(row)}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="align-top">
                      <div className="max-w-[100px] sm:max-w-[120px] lg:max-w-[160px] truncate text-sm font-medium text-foreground" title={row.product_code || undefined}>
                        {row.product_code || "—"}
                      </div>
                    </TableCell>
                    <TableCell className="align-top">
                      <div className="flex min-w-[150px] justify-start gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openConfigureDialog(row)}
                        >
                          Configure
                        </Button>
                        <Button
                          asChild
                          size="sm"
                        >
                          <Link href="/product-studio">
                            Use
                            <ArrowUpRight className="h-4 w-4" />
                          </Link>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={handleDialogChange}>
        <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {dialogMode === "create" ? "Create blueprint" : "Configure blueprint"}
            </DialogTitle>
            <DialogDescription>
              {dialogMode === "create"
                ? "Create a reusable product setup for the selected store."
                : "Adjust the editable details and review the saved product setup."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-6">
            {dialogMode === "configure" && activeBlueprint ? (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg border border-border bg-muted/20 p-4">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                    Store
                  </div>
                  <div className="mt-2 font-medium text-foreground">
                    {providerLabel(activeBlueprint.provider)} • {storefrontLabel(activeBlueprint.provider_storefront_type)}
                  </div>
                  <div className="mt-2">
                    <StoreLabel source={activeBlueprint} secondaryVariant="badge" includeStorefront={false} />
                  </div>
                  <div className="mt-3 text-xs text-muted-foreground">
                    {getBlueprintCardTitle(activeBlueprint)}
                    {" • "}
                    {formatBlueprintProductType(activeBlueprint)}
                  </div>
                </div>

                <div className="rounded-lg border border-border bg-muted/20 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                        Status
                      </div>
                      <div className="mt-2">
                        <StatusBadge value={activeBlueprint.status} />
                      </div>
                      <div className="mt-2 text-sm text-muted-foreground">
                        {activeBlueprint.validated_at
                          ? `Ready ${formatDateTime(activeBlueprint.validated_at)}`
                          : "Details have not been loaded yet"}
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void handleRefreshBlueprint(activeBlueprint.id)}
                      disabled={refreshingBlueprintId === activeBlueprint.id}
                    >
                      {refreshingBlueprintId === activeBlueprint.id ? (
                        <LoaderCircle className="animate-spin" />
                      ) : null}
                      Refresh details
                    </Button>
                  </div>
                  <div className="mt-4 text-xs text-muted-foreground">
                    {formatCount(activeBlueprint.draft_count, "draft")}
                    {" • "}
                    Updated {formatDateTime(activeBlueprint.updated_at)}
                  </div>
                </div>

                <div className="rounded-lg border border-border bg-muted/20 p-4 md:col-span-2">
                  <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                    Product details
                  </div>
                  <div className="mt-2 font-medium text-foreground">
                    {getBlueprintCardSubtitle(activeBlueprint)}
                  </div>
                  <div className="mt-2 text-sm leading-6 text-muted-foreground">
                    {formatBlueprintVariantSummary(activeBlueprint)}
                    {" • "}
                    {formatBlueprintArtworkSummary(activeBlueprint)}
                  </div>
                  <div className="mt-3 text-xs text-muted-foreground">
                    {formatBlueprintProductType(activeBlueprint)}
                    {activeBlueprint.base_cost_amount !== null
                      ? ` • ${formatCurrency(activeBlueprint.base_cost_amount, activeBlueprint.currency ?? "USD")} base`
                      : ""}
                    {activeBlueprint.product_code ? ` • Code ${activeBlueprint.product_code}` : ""}
                  </div>
                </div>
              </div>
            ) : null}

            <div className="grid gap-5 md:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="blueprint-name">Blueprint name</Label>
                <Input
                  id="blueprint-name"
                  value={formState.name}
                  onChange={(event) =>
                    setFormState((current) => ({
                      ...current,
                      name: event.target.value
                    }))
                  }
                  placeholder="Minimalist Abstract Wall Art"
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="blueprint-category">Category</Label>
                <Input
                  id="blueprint-category"
                  value={formState.category}
                  onChange={(event) =>
                    setFormState((current) => ({
                      ...current,
                      category: event.target.value
                    }))
                  }
                  placeholder="Wall art"
                />
              </div>
            </div>

            {dialogMode === "create" ? (
              <>
                <div className="flex flex-col gap-2">
                  <Label>Store</Label>
                  <Select
                    value={formState.provider_store_connection_id}
                    onValueChange={(value) =>
                      setFormState((current) => ({
                        ...current,
                        provider_store_connection_id: value
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select a store">
                        {selectedConnection ? getStoreDisplayParts(selectedConnection).name : undefined}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent className="max-h-[min(400px,var(--radix-select-content-available-height))]">
                      {Object.entries(groupedConnections).map(([provider, stores]) => (
                        <SelectGroup key={provider}>
                          <SelectLabel className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mt-1 px-2 mb-1">
                            {providerLabel(provider as any)}
                          </SelectLabel>
                          {stores.map((connection) => (
                            <SelectItem key={connection.id} value={connection.id}>
                              <StoreLabel
                                source={connection}
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

                <div className="rounded-lg border border-border bg-muted/20 p-4 text-sm">
                  <div className="font-medium text-foreground">Base product</div>
                  <div className="mt-1 text-muted-foreground">
                    {selectedProvider === "printify"
                      ? "Paste the Printify product link for the item you want to reuse. Velora will pull in its details after you save."
                      : selectedProvider === "gelato"
                        ? "Enter the Gelato template ID for the item you want to reuse."
                        : "Choose a store to unlock the correct base-product guidance."}
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <Label htmlFor="blueprint-reference">
                    {selectedProvider === "gelato" ? "Template ID" : "Product link"}
                  </Label>
                  <Input
                    id="blueprint-reference"
                    value={formState.reference_value}
                    onChange={(event) =>
                      setFormState((current) => ({
                        ...current,
                        reference_value: event.target.value
                      }))
                    }
                    placeholder={
                      selectedProvider === "gelato"
                        ? "gelato-template-id"
                        : "https://printify.com/app/product-details/..."
                    }
                  />
                </div>
              </>
            ) : (
              <div className="rounded-lg border border-border bg-muted/20 p-4 text-sm">
                <div className="font-medium text-foreground">Base product</div>
                <div className="mt-1 text-muted-foreground">
                  The store and base product stay locked after you create the blueprint.
                </div>
              </div>
            )}

            <div className="grid gap-5 md:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="blueprint-product-code">Product code</Label>
                <Input
                  id="blueprint-product-code"
                  value={formState.product_code}
                  onChange={(event) =>
                    setFormState((current) => ({
                      ...current,
                      product_code: event.target.value
                    }))
                  }
                  placeholder="SKU-100"
                />
              </div>
              {selectedProvider === "gelato" ? (
                <div className="flex flex-col gap-2">
                  <Label htmlFor="gelato-placeholder">Artwork placement</Label>
                  <Input
                    id="gelato-placeholder"
                    value={formState.gelato_placeholder_name}
                    onChange={(event) =>
                      setFormState((current) => ({
                        ...current,
                        gelato_placeholder_name: event.target.value
                      }))
                    }
                    placeholder="ImageFront"
                  />
                </div>
              ) : null}
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="blueprint-base-title">Base title</Label>
              <Input
                id="blueprint-base-title"
                value={formState.base_title}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    base_title: event.target.value
                  }))
                }
                placeholder="Neutral canvas print for living rooms"
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="blueprint-base-description">Base description</Label>
              <Textarea
                id="blueprint-base-description"
                className="min-h-28"
                value={formState.base_description}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    base_description: event.target.value
                  }))
                }
                placeholder="Reusable description context for drafts created from this blueprint."
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="blueprint-base-tags">Base tags</Label>
              <Input
                id="blueprint-base-tags"
                value={formState.base_tags}
                onChange={(event) =>
                  setFormState((current) => ({
                    ...current,
                    base_tags: event.target.value
                  }))
                }
                placeholder="neutral wall art, abstract canvas, modern decor"
              />
            </div>

            {formError ? (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {formError}
              </div>
            ) : null}
          </div>

          <DialogFooter className="mt-2 sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              {dialogMode === "configure" && activeBlueprint ? (
                <Button
                  variant="ghost"
                  onClick={() => void handleDelete(activeBlueprint.id)}
                  disabled={activeBlueprint.draft_count > 0}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </Button>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {dialogMode === "configure" && activeBlueprint ? (
                <Button asChild variant="outline">
                  <Link href="/product-studio">
                    Use blueprint
                    <ArrowUpRight className="h-4 w-4" />
                  </Link>
                </Button>
              ) : null}
              <Button onClick={() => void handleSubmitBlueprint()} disabled={submitting}>
                {submitting ? <LoaderCircle className="animate-spin" /> : null}
                {dialogMode === "create" ? "Create blueprint" : "Save changes"}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
