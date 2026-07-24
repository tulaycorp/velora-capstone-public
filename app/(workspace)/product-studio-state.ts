export type DraftFormState = {
  title: string;
  designDescription: string;
  productDescription: string;
  tags: string[];
  retailPrice: string;
  currency: string;
  sku: string;
};

export const ETSY_TAG_LIMIT = 13;
export const ETSY_TAG_MAX_LENGTH = 20;
export const ETSY_MOCKUP_LIMIT = 10;

export function shouldBlockProductStudioForStoreSelection({
  selectedStoreId,
  selectionReady,
  storesLoading
}: {
  selectedStoreId: string;
  selectionReady: boolean;
  storesLoading: boolean;
}) {
  return selectionReady && !storesLoading && selectedStoreId === "all";
}

function getBlueprintDesignDescription(blueprint: ProductStudioBlueprintSeed | null) {
  if (!blueprint?.basic_design_info_json) {
    return "";
  }

  const description = blueprint.basic_design_info_json.description;
  return typeof description === "string" ? description : "";
}

type ProductStudioBlueprintSeed = {
  id: string;
  name: string;
  base_title: string | null;
  base_description: string | null;
  basic_design_info_json?: Record<string, unknown> | null;
  base_tags: string[];
  base_cost_amount: number | null;
  currency: string | null;
  product_code: string | null;
};

type ProductStudioSelectionSyncInput = {
  filteredBlueprints: ProductStudioBlueprintSeed[];
  selectedBlueprintId: string;
  draftForm: DraftFormState;
};

type ProductStudioSelectionSyncResult = {
  nextSelectedBlueprintId: string;
  nextDraftForm: DraftFormState;
  shouldUpdateSelectedBlueprintId: boolean;
  shouldUpdateDraftForm: boolean;
};

export function buildDraftForm(blueprint: ProductStudioBlueprintSeed | null): DraftFormState {
  return {
    title: blueprint?.base_title ?? blueprint?.name ?? "",
    designDescription: getBlueprintDesignDescription(blueprint),
    productDescription: blueprint?.base_description ?? "",
    tags: [...(blueprint?.base_tags ?? [])],
    retailPrice:
      blueprint?.base_cost_amount !== null && blueprint?.base_cost_amount !== undefined
        ? String((blueprint.base_cost_amount + 15).toFixed(2))
        : "",
    currency: blueprint?.currency ?? "USD",
    sku: blueprint?.product_code ?? ""
  };
}

function normalizeMarketplaceTag(rawTag: string) {
  return rawTag.replace(/\s+/g, " ").trim().slice(0, ETSY_TAG_MAX_LENGTH).trim();
}

export function appendMarketplaceTags(currentTags: string[], rawInput: string) {
  if (!rawInput.trim()) {
    return currentTags;
  }

  const nextTags = [...currentTags];
  const seen = new Set(currentTags.map((tag) => tag.toLocaleLowerCase()));

  for (const token of rawInput.split(/[,\n]/)) {
    const normalized = normalizeMarketplaceTag(token);
    if (!normalized) {
      continue;
    }

    const key = normalized.toLocaleLowerCase();
    if (seen.has(key)) {
      continue;
    }

    nextTags.push(normalized);
    seen.add(key);

    if (nextTags.length >= ETSY_TAG_LIMIT) {
      break;
    }
  }

  return nextTags;
}

export function queueMarketplaceFiles<T>(
  currentCount: number,
  incomingFiles: readonly T[],
  limit = ETSY_MOCKUP_LIMIT
) {
  const availableSlots = Math.max(limit - currentCount, 0);
  const acceptedFiles = incomingFiles.slice(0, availableSlots);

  return {
    acceptedFiles,
    rejectedCount: Math.max(incomingFiles.length - acceptedFiles.length, 0),
    availableSlots
  };
}

export function hasFileTransferData(types: Iterable<string> | ArrayLike<string>) {
  return Array.from(types).includes("Files");
}

export function getMarketplaceImageStatusLabel(source: "attached" | "queued") {
  return source === "attached" ? "Attached" : null;
}

export function reorderItems<T>(items: T[], fromIndex: number, toIndex: number) {
  if (
    fromIndex < 0
    || toIndex < 0
    || fromIndex >= items.length
    || toIndex >= items.length
    || fromIndex === toIndex
  ) {
    return items;
  }

  const nextItems = [...items];
  const [movedItem] = nextItems.splice(fromIndex, 1);
  nextItems.splice(toIndex, 0, movedItem);
  return nextItems;
}

function areStringArraysEqual(left: string[], right: string[]) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function areDraftFormsEqual(left: DraftFormState, right: DraftFormState) {
  return (
    left.title === right.title
    && left.designDescription === right.designDescription
    && left.productDescription === right.productDescription
    && areStringArraysEqual(left.tags, right.tags)
    && left.retailPrice === right.retailPrice
    && left.currency === right.currency
    && left.sku === right.sku
  );
}

export function syncProductStudioSelection({
  filteredBlueprints,
  selectedBlueprintId,
  draftForm
}: ProductStudioSelectionSyncInput): ProductStudioSelectionSyncResult {
  if (filteredBlueprints.length === 0) {
    const nextDraftForm = buildDraftForm(null);

    return {
      nextSelectedBlueprintId: "",
      nextDraftForm,
      shouldUpdateSelectedBlueprintId: selectedBlueprintId !== "",
      shouldUpdateDraftForm: !areDraftFormsEqual(draftForm, nextDraftForm)
    };
  }

  const hasSelectedBlueprint = filteredBlueprints.some(
    (blueprint) => blueprint.id === selectedBlueprintId
  );

  if (hasSelectedBlueprint) {
    return {
      nextSelectedBlueprintId: selectedBlueprintId,
      nextDraftForm: draftForm,
      shouldUpdateSelectedBlueprintId: false,
      shouldUpdateDraftForm: false
    };
  }

  const nextDraftForm = buildDraftForm(null);

  return {
    nextSelectedBlueprintId: "",
    nextDraftForm,
    shouldUpdateSelectedBlueprintId: selectedBlueprintId !== "",
    shouldUpdateDraftForm: !areDraftFormsEqual(draftForm, nextDraftForm)
  };
}
