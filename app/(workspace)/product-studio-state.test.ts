import assert from "node:assert/strict";
import test from "node:test";

import {
  appendMarketplaceTags,
  buildDraftForm,
  getMarketplaceImageStatusLabel,
  hasFileTransferData,
  queueMarketplaceFiles,
  reorderItems,
  shouldBlockProductStudioForStoreSelection,
  syncProductStudioSelection,
  ETSY_MOCKUP_LIMIT,
  ETSY_TAG_LIMIT,
  type DraftFormState
} from "./product-studio-state.ts";

const populatedDraftForm: DraftFormState = {
  title: "Filled title",
  designDescription: "Filled design description",
  productDescription: "Filled product description",
  tags: ["tag-a", "tag-b"],
  retailPrice: "42.00",
  currency: "EUR",
  sku: "SKU-1"
};

test("buildDraftForm keeps design and product descriptions separate", () => {
  const nextForm = buildDraftForm({
    id: "blueprint-1",
    name: "Nordic print",
    base_title: "Nordic print",
    base_description: "Listing description from blueprint",
    basic_design_info_json: {
      description: "Muted abstract shapes and warm neutral tones."
    },
    base_tags: [],
    base_cost_amount: 24,
    currency: "USD",
    product_code: "NP-1"
  });

  assert.equal(nextForm.productDescription, "Listing description from blueprint");
  assert.equal(nextForm.designDescription, "Muted abstract shapes and warm neutral tones.");
});

test("appendMarketplaceTags tokenizes pasted comma-separated tags and enforces Etsy tag limits", () => {
  const nextTags = appendMarketplaceTags(
    [],
    Array.from({ length: ETSY_TAG_LIMIT + 3 }, (_, index) => `tag ${index + 1}`).join(", ")
  );

  assert.equal(nextTags.length, ETSY_TAG_LIMIT);
  assert.deepEqual(nextTags, Array.from({ length: ETSY_TAG_LIMIT }, (_, index) => `tag ${index + 1}`));
});

test("appendMarketplaceTags trims, deduplicates, and truncates tags like Etsy marketplace input", () => {
  const nextTags = appendMarketplaceTags(
    ["wall art"],
    "  wall art ,  neutral decor  , 1234567890123456789012345 "
  );

  assert.deepEqual(nextTags, [
    "wall art",
    "neutral decor",
    "12345678901234567890"
  ]);
});

test("syncProductStudioSelection clears the selection and draft once when no blueprints remain", () => {
  const nextState = syncProductStudioSelection({
    filteredBlueprints: [],
    selectedBlueprintId: "blueprint-1",
    draftForm: populatedDraftForm
  });

  assert.equal(nextState.nextSelectedBlueprintId, "");
  assert.equal(nextState.shouldUpdateSelectedBlueprintId, true);
  assert.equal(nextState.shouldUpdateDraftForm, true);
  assert.deepEqual(nextState.nextDraftForm, buildDraftForm(null));
});

test("syncProductStudioSelection does not request more state updates once the form is already empty", () => {
  const nextState = syncProductStudioSelection({
    filteredBlueprints: [],
    selectedBlueprintId: "",
    draftForm: buildDraftForm(null)
  });

  assert.equal(nextState.shouldUpdateSelectedBlueprintId, false);
  assert.equal(nextState.shouldUpdateDraftForm, false);
});

test("syncProductStudioSelection leaves blueprint selection empty when blueprints are available", () => {
  const nextState = syncProductStudioSelection({
    filteredBlueprints: [
      {
        id: "blueprint-1",
        name: "Nordic print",
        base_title: "Nordic print",
        base_description: "Listing description",
        base_tags: ["wall art"],
        base_cost_amount: 24,
        currency: "USD",
        product_code: "NP-1"
      }
    ],
    selectedBlueprintId: "",
    draftForm: buildDraftForm(null)
  });

  assert.equal(nextState.nextSelectedBlueprintId, "");
  assert.equal(nextState.shouldUpdateSelectedBlueprintId, false);
  assert.equal(nextState.shouldUpdateDraftForm, false);
});

test("syncProductStudioSelection clears a blueprint that is no longer available", () => {
  const nextState = syncProductStudioSelection({
    filteredBlueprints: [
      {
        id: "blueprint-2",
        name: "Canvas print",
        base_title: null,
        base_description: null,
        base_tags: [],
        base_cost_amount: null,
        currency: "USD",
        product_code: null
      }
    ],
    selectedBlueprintId: "blueprint-1",
    draftForm: populatedDraftForm
  });

  assert.equal(nextState.nextSelectedBlueprintId, "");
  assert.equal(nextState.shouldUpdateSelectedBlueprintId, true);
  assert.equal(nextState.shouldUpdateDraftForm, true);
  assert.deepEqual(nextState.nextDraftForm, buildDraftForm(null));
});

test("Product Studio blocks only after the All Stores selection is ready", () => {
  assert.equal(
    shouldBlockProductStudioForStoreSelection({
      selectedStoreId: "all",
      selectionReady: true,
      storesLoading: false
    }),
    true
  );
  assert.equal(
    shouldBlockProductStudioForStoreSelection({
      selectedStoreId: "store-1",
      selectionReady: true,
      storesLoading: false
    }),
    false
  );
  assert.equal(
    shouldBlockProductStudioForStoreSelection({
      selectedStoreId: "all",
      selectionReady: false,
      storesLoading: true
    }),
    false
  );
});

test("Product Studio listing image limit stays aligned with the current UI cap", () => {
  assert.equal(ETSY_MOCKUP_LIMIT, 10);
});

test("queueMarketplaceFiles accepts only the remaining image slots", () => {
  const queuedFiles = queueMarketplaceFiles(8, ["a", "b", "c", "d"]);

  assert.deepEqual(queuedFiles.acceptedFiles, ["a", "b"]);
  assert.equal(queuedFiles.rejectedCount, 2);
  assert.equal(queuedFiles.availableSlots, 2);
});

test("queueMarketplaceFiles rejects new images once the limit is reached", () => {
  const queuedFiles = queueMarketplaceFiles(ETSY_MOCKUP_LIMIT, ["a"]);

  assert.deepEqual(queuedFiles.acceptedFiles, []);
  assert.equal(queuedFiles.rejectedCount, 1);
  assert.equal(queuedFiles.availableSlots, 0);
});

test("hasFileTransferData detects external file drags but ignores internal reorder payloads", () => {
  assert.equal(hasFileTransferData(["Files", "text/plain"]), true);
  assert.equal(hasFileTransferData(["application/json", "text/plain"]), false);
});

test("getMarketplaceImageStatusLabel hides queued copy but keeps attached state", () => {
  assert.equal(getMarketplaceImageStatusLabel("queued"), null);
  assert.equal(getMarketplaceImageStatusLabel("attached"), "Attached");
});

test("reorderItems moves the first image out of the hero position", () => {
  const nextItems = reorderItems(["hero", "detail", "scale"], 0, 2);

  assert.deepEqual(nextItems, ["detail", "scale", "hero"]);
});

test("reorderItems keeps the same reference for invalid moves", () => {
  const currentItems = ["hero", "detail"];
  const nextItems = reorderItems(currentItems, 3, 0);

  assert.equal(nextItems, currentItems);
});
