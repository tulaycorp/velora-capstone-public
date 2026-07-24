"use client";

import { useRouter } from "next/navigation";
import {
  GripVertical,
  ImagePlus,
  LoaderCircle,
  RefreshCw,
  Upload,
  X
} from "lucide-react";
import type { ChangeEvent, DragEvent, KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PageHeader } from "@/components/workspace/page-header";
import { ProductControlsPanel } from "@/components/workspace/product-controls-panel";
import {
  ProductEditorRailRow as RailRow,
  ProductEditorSection as SurfaceSection
} from "@/components/workspace/product-editor-primitives";
import { AIListingAssistant, type AIListingAssistantHandle } from "@/components/workspace/ai-listing-assistant";
import { AIFieldRegenerateButton } from "@/components/workspace/ai-field-regenerate-button";
import {
  EmptyState,
  ResourceError,
  ProductStudioSkeleton
} from "@/components/workspace/resource-state";
import {
  buildOrderedMockupIds,
  serializeOrderedMockupItem,
  syncOrderedMockups,
  type OrderedMockupItem
} from "../product-detail-mockup-state";
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
} from "../product-studio-state";
import {
  StoreLabel,
  groupAndSortStoreConnections
} from "@/components/workspace/store-label";
import { StatusBadge } from "@/components/workspace/status-badge";
import { useStoreContext } from "@/components/workspace/store-context";
import { Button } from "@/components/ui/button";
import { AutoResizeTextarea } from "@/components/ui/auto-resize-textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { Textarea } from "@/components/ui/textarea";
import type { AIGenerationField } from "@/lib/ai-generation-review";
import {
  BackendApiError,
  createProductDraft,
  fetchBlueprints,
  fetchProduct,
  fetchPublishingJob,
  formatCurrency,
  formatDateTime,
  providerLabel,
  publishProduct,
  reorderMockups,
  storefrontActionLabel,
  updateProduct,
  uploadDesignAsset,
  uploadMockup,
  type Blueprint,
  type PodProviderKey,
  type Product,
  type PublishingJob
} from "@/lib/backend-api";
import {
  formatBlueprintArtworkSummary,
  formatBlueprintProductType,
  formatBlueprintVariantSummary,
  getBlueprintCardSubtitle,
  getBlueprintCardTitle
} from "@/lib/blueprint-display";
import { workspacePageCacheKeys } from "@/lib/workspace-page-cache-keys";
import {
  formatPushHelperCopy,
  formatPushStatusMessage,
  formatQueuedPushMessage
} from "@/lib/ux-copy";
import {
  hasPendingStorefrontChanges,
  isPublishingActiveStatus,
  pollPublishingJobUntilSettled
} from "@/lib/publishing-status";
import {
  buildPublishReadiness,
  focusPublishReadinessField,
  isProductEditorDirty
} from "@/lib/product-publish-readiness";
import {
  buildProductEditorListingInput,
  withProductPublishingStatus
} from "@/lib/product-editor-save";
import { useCachedWorkspaceResource } from "@/hooks/use-cached-workspace-resource";
import {
  createQueuedProductImage as createQueuedMockup,
  extractSupportedProductImages as extractImageFiles,
  truncateProductImageName as truncateFileName,
  type QueuedProductImage as QueuedMockup
} from "@/lib/product-editor-media";

export default function ProductStudioPage() {
  const aiListingAssistantRef = useRef<AIListingAssistantHandle>(null);
  const [regeneratingField, setRegeneratingField] =
    useState<AIGenerationField | null>(null);
  const router = useRouter();
  const {
    selectedStoreId,
    setSelectedStoreId,
    storeConnections,
    selectionReady,
    loading: storesLoading
  } = useStoreContext();
  const [selectedBlueprintId, setSelectedBlueprintId] = useState("");
  const [designFile, setDesignFile] = useState<File | null>(null);
  const [designPreviewUrl, setDesignPreviewUrl] = useState<string | null>(null);
  const [designDropActive, setDesignDropActive] = useState(false);
  const [queuedMockups, setQueuedMockups] = useState<QueuedMockup[]>([]);
  const [mockupPreviewUrls, setMockupPreviewUrls] = useState<Record<string, string>>({});
  const [mockupDropActive, setMockupDropActive] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [draggedMockupKey, setDraggedMockupKey] = useState<string | null>(null);
  const [mockupOrder, setMockupOrder] = useState<OrderedMockupItem[]>([]);
  const [mockupOrderDirty, setMockupOrderDirty] = useState(false);
  const [draftForm, setDraftForm] = useState<DraftFormState>(buildDraftForm(null));
  const [createdProduct, setCreatedProduct] = useState<Product | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [savingDraft, setSavingDraft] = useState(false);
  const [uploadingMockups, setUploadingMockups] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [latestPublishingJob, setLatestPublishingJob] = useState<PublishingJob | null>(null);
  const [jobStatusMessage, setJobStatusMessage] = useState<string | null>(null);
  const {
    data: blueprintsData,
    error,
    load,
    loading
  } = useCachedWorkspaceResource<Blueprint[]>({
    cacheKey: workspacePageCacheKeys.productStudio(),
    loadResource: fetchBlueprints
  });
  const blueprints = useMemo(() => blueprintsData ?? [], [blueprintsData]);
  const groupedStoreConnections = useMemo(
    () => groupAndSortStoreConnections(storeConnections),
    [storeConnections]
  );

  const filteredBlueprints = useMemo(
    () =>
      selectedStoreId === "all"
        ? blueprints
        : blueprints.filter(
            (blueprint) => blueprint.provider_store_connection_id === selectedStoreId
          ),
    [blueprints, selectedStoreId]
  );

  const selectedBlueprint =
    filteredBlueprints.find((blueprint) => blueprint.id === selectedBlueprintId) ?? null;
  const storefrontAction =
    createdProduct
      ? storefrontActionLabel(createdProduct.provider_storefront_type)
      : selectedBlueprint
        ? storefrontActionLabel(selectedBlueprint.provider_storefront_type)
        : "store";
  const createdProductId = createdProduct?.id ?? null;
  const createdProductPublishingStatus = createdProduct?.publishing_status ?? null;
  const publishingActive = isPublishingActiveStatus(createdProduct?.publishing_status);
  const productControlsMetaText = createdProduct
    ? `Last saved ${formatDateTime(createdProduct.updated_at)}`
    : "Save your draft to unlock store push.";
  const submittedMetaText = latestPublishingJob
    ? `Submitted revision ${latestPublishingJob.product_revision} ${formatDateTime(latestPublishingJob.created_at)}${
        createdProduct && createdProduct.revision > latestPublishingJob.product_revision
          ? ` · Current saved revision ${createdProduct.revision} is newer; this send uses revision ${latestPublishingJob.product_revision}`
          : ""
      }`
    : null;

  const uploadedMockups = useMemo(
    () => [...(createdProduct?.mockups ?? [])].sort((left, right) => left.position - right.position),
    [createdProduct?.mockups]
  );

  const existingMockupCount = createdProduct?.mockup_count ?? 0;
  const totalMockupCount = existingMockupCount + queuedMockups.length;
  const remainingMockupSlots = Math.max(
    ETSY_MOCKUP_LIMIT - totalMockupCount,
    0
  );
  const canQueueMoreMockups = totalMockupCount < ETSY_MOCKUP_LIMIT;

  const attachedMockupsById = useMemo(
    () => new Map(uploadedMockups.map((mockup) => [mockup.id, mockup])),
    [uploadedMockups]
  );
  const queuedMockupFilesById = useMemo(
    () => new Map(queuedMockups.map((item) => [item.id, item.file])),
    [queuedMockups]
  );
  const queuedMockupIds = useMemo(
    () => queuedMockups.map((item) => item.id),
    [queuedMockups]
  );
  const attachedMockupIds = useMemo(
    () => uploadedMockups.map((mockup) => mockup.id),
    [uploadedMockups]
  );
  const mockupPreviewItems = useMemo(
    () =>
      mockupOrder
        .map((orderedItem, index) => {
          if (orderedItem.source === "attached") {
            const mockup = attachedMockupsById.get(orderedItem.id);
            if (!mockup) {
              return null;
            }

            return {
              id: serializeOrderedMockupItem(orderedItem),
              orderKey: serializeOrderedMockupItem(orderedItem),
              mockupId: mockup.id,
              queueId: null,
              url: mockup.public_url,
              badge: index === 0 ? "Hero" : `${index + 1}`,
              detail: getMarketplaceImageStatusLabel("attached"),
              source: "attached" as const
            };
          }

          const previewUrl = mockupPreviewUrls[orderedItem.id] ?? null;
          if (!queuedMockupFilesById.has(orderedItem.id) || !previewUrl) {
            return null;
          }

          return {
            id: serializeOrderedMockupItem(orderedItem),
            orderKey: serializeOrderedMockupItem(orderedItem),
            mockupId: null,
            queueId: orderedItem.id,
            url: previewUrl,
            badge: index === 0 ? "Hero" : `${index + 1}`,
            detail: getMarketplaceImageStatusLabel("queued"),
            source: "queued" as const
          };
        })
        .filter((item): item is NonNullable<typeof item> => item !== null)
        .slice(0, ETSY_MOCKUP_LIMIT),
    [attachedMockupsById, mockupOrder, mockupPreviewUrls, queuedMockupFilesById]
  );

  const designSurfacePreviewUrl =
    designPreviewUrl ?? createdProduct?.design_asset?.public_url ?? null;
  const parsedRetailPrice = Number(draftForm.retailPrice);
  const hasRetailPrice =
    draftForm.retailPrice.trim() !== "" && Number.isFinite(parsedRetailPrice);
  const projectedMargin =
    hasRetailPrice
      && selectedBlueprint?.base_cost_amount !== null
      && selectedBlueprint?.base_cost_amount !== undefined
      ? parsedRetailPrice - selectedBlueprint.base_cost_amount
      : null;

  const editorDirty = isProductEditorDirty({
    product: createdProduct,
    values: {
      title: draftForm.title,
      description: draftForm.productDescription,
      designDescription: draftForm.designDescription,
      tags: draftForm.tags,
      retailPrice: draftForm.retailPrice,
      currency: draftForm.currency,
      sku: draftForm.sku
    },
    pendingDesign: Boolean(designFile),
    pendingMockups: queuedMockups.length > 0,
    mockupOrderDirty
  });
  const readiness = buildPublishReadiness({
    blueprintReady: Boolean(
      selectedBlueprint?.validated_at && selectedBlueprint.variant_count > 0
    ),
    designSaved: Boolean(createdProduct?.design_asset?.public_url),
    mockupCount: uploadedMockups.filter((mockup) => Boolean(mockup.public_url)).length,
    title: draftForm.title,
    retailPrice: draftForm.retailPrice,
    currency: draftForm.currency,
    editorDirty
  });
  const publishDisabled =
    !createdProduct
    || publishing
    || publishingActive
    || savingDraft
    || uploadingMockups
    || !hasPendingStorefrontChanges(createdProduct?.revision ?? 0, latestPublishingJob)
    || readiness.some((item) => !item.complete);
  const hasEditorChanges = createdProduct
    ? editorDirty
    : Boolean(
        selectedBlueprintId
        || designFile
        || queuedMockups.length > 0
        || mockupOrderDirty
        || draftForm.title.trim()
        || draftForm.productDescription.trim()
        || draftForm.designDescription.trim()
        || draftForm.tags.length > 0
        || draftForm.retailPrice.trim()
        || draftForm.sku.trim()
        || draftForm.currency.trim() !== "USD"
      );
  const saveDisabled =
    !hasEditorChanges
    || publishingActive;

  const loadStudio = useCallback(async () => {
    await load();
  }, [load]);

  useEffect(() => {
    const nextSelectionState = syncProductStudioSelection({
      filteredBlueprints,
      selectedBlueprintId,
      draftForm
    });

    if (nextSelectionState.shouldUpdateSelectedBlueprintId) {
      setSelectedBlueprintId(nextSelectionState.nextSelectedBlueprintId);
    }

    if (nextSelectionState.shouldUpdateDraftForm) {
      setDraftForm(nextSelectionState.nextDraftForm);
    }
  }, [draftForm, filteredBlueprints, selectedBlueprintId]);

  useEffect(() => {
    if (!designFile) {
      setDesignPreviewUrl(null);
      return;
    }

    const nextPreviewUrl = URL.createObjectURL(designFile);
    setDesignPreviewUrl(nextPreviewUrl);

    return () => {
      URL.revokeObjectURL(nextPreviewUrl);
    };
  }, [designFile]);

  useEffect(() => {
    if (!queuedMockups.length) {
      setMockupPreviewUrls({});
      return;
    }

    const nextPreviewEntries = queuedMockups.map(({ id, file }) => [
      id,
      URL.createObjectURL(file)
    ] as const);
    setMockupPreviewUrls(Object.fromEntries(nextPreviewEntries));

    return () => {
      nextPreviewEntries.forEach(([, previewUrl]) => {
        URL.revokeObjectURL(previewUrl);
      });
    };
  }, [queuedMockups]);

  useEffect(() => {
    setMockupOrder((current) =>
      syncOrderedMockups({
        attachedIds: attachedMockupIds,
        queuedIds: queuedMockupIds,
        currentOrder: current,
        preserveCurrentOrder: mockupOrderDirty
      })
    );
  }, [attachedMockupIds, mockupOrderDirty, queuedMockupIds]);

  useEffect(() => {
    setTagInput("");
  }, [selectedBlueprintId]);

  useEffect(() => {
    if (!createdProductId || !isPublishingActiveStatus(createdProductPublishingStatus)) {
      return;
    }

    const productId = createdProductId;
    let cancelled = false;
    let refreshInFlight = false;

    async function refreshPublishingProduct() {
      if (refreshInFlight) {
        return;
      }

      refreshInFlight = true;
      try {
        const refreshedProduct = await fetchProduct(productId);
        if (cancelled) {
          return;
        }

        setCreatedProduct(refreshedProduct);
        setJobStatusMessage(
          formatPushStatusMessage(
            storefrontActionLabel(refreshedProduct.provider_storefront_type),
            refreshedProduct.publishing_status
          )
        );
      } catch {
        // Keep the current status visible; the next interval can retry.
      } finally {
        refreshInFlight = false;
      }
    }

    void refreshPublishingProduct();
    const intervalId = window.setInterval(() => {
      void refreshPublishingProduct();
    }, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [createdProductId, createdProductPublishingStatus]);

  async function persistMockupOrdering(product: Product) {
    const queuedOrderIds = mockupOrder
      .filter((item) => item.source === "queued")
      .map((item) => item.id);
    const uploadedIdsByQueuedId = new Map<string, string>();

    if (queuedOrderIds.length > 0) {
      for (const [index, queuedId] of queuedOrderIds.entries()) {
        const queuedFile = queuedMockupFilesById.get(queuedId);
        if (!queuedFile) {
          continue;
        }

        const uploadedMockup = await uploadMockup(
          product.id,
          queuedFile,
          product.mockup_count + index
        );
        uploadedIdsByQueuedId.set(queuedId, uploadedMockup.id);
      }
    }

    const orderedMockupIds =
      uploadedIdsByQueuedId.size > 0
        ? buildOrderedMockupIds(mockupOrder, uploadedIdsByQueuedId)
        : mockupOrder
            .filter((item) => item.source === "attached")
            .map((item) => item.id);

    if (orderedMockupIds.length === 0) {
      return product;
    }

    return reorderMockups(product.id, orderedMockupIds);
  }

  function buildProductPayload(designAssetId: string) {
    if (!selectedBlueprint) {
      return null;
    }

    return {
      blueprint_id: selectedBlueprint.id,
      design_asset_id: designAssetId,
      ...buildProductEditorListingInput({
        title: draftForm.title,
        description: draftForm.productDescription,
        designDescription: draftForm.designDescription,
        tags: draftForm.tags,
        retailPrice: draftForm.retailPrice,
        currency: draftForm.currency,
        sku: draftForm.sku
      }, selectedBlueprint.name)
    };
  }

  async function handleSaveDraft() {
    if (!selectedBlueprint) {
      setDraftError("Choose a ready blueprint first.");
      return;
    }
    if (!designFile && !createdProduct?.design_asset_id) {
      setDraftError("Upload a design file before saving the draft.");
      return;
    }

    setSavingDraft(true);
    setDraftError(null);

    try {
      const designAsset = designFile ? await uploadDesignAsset(designFile) : null;
      const designAssetId = designAsset?.id ?? createdProduct?.design_asset_id;
      if (!designAssetId) {
        setDraftError("Upload a design file before saving the draft.");
        return;
      }

      const payload = buildProductPayload(designAssetId);
      if (!payload) {
        setDraftError("Choose a ready blueprint first.");
        return;
      }

      const savedProduct = createdProduct
        ? await updateProduct(createdProduct.id, {
            title: payload.title,
            description: payload.description,
            tags: payload.tags,
            retail_price: payload.retail_price,
            currency: payload.currency,
            sku: payload.sku,
            design_description: payload.design_description,
            expected_revision: createdProduct.revision,
            status: createdProduct.status === "published" ? createdProduct.status : "draft"
          })
        : await createProductDraft(payload);

      if (queuedMockups.length > 0 || mockupOrderDirty) {
        setUploadingMockups(true);

        try {
          const refreshedProduct = await persistMockupOrdering(savedProduct);
          setQueuedMockups([]);
          setMockupOrderDirty(false);
          setCreatedProduct(refreshedProduct);
          setDesignFile(null);
          setJobStatusMessage("Draft saved and images attached.");
          router.replace(`/products/${refreshedProduct.id}`);
        } catch (uploadError) {
          setCreatedProduct(savedProduct);
          setDesignFile(null);
          setDraftError(
            uploadError instanceof Error
              ? uploadError.message
              : "Draft saved, but some images could not attach yet."
          );
          setJobStatusMessage("Draft saved. Some images still need to upload.");
        } finally {
          setUploadingMockups(false);
        }
      } else {
        setCreatedProduct(savedProduct);
        setDesignFile(null);
        setJobStatusMessage(
          savedProduct.status === "published"
            ? "Changes saved."
            : `Draft saved. Send to ${storefrontAction} when it is ready.`
        );
        router.replace(`/products/${savedProduct.id}`);
      }
    } catch (createError) {
      setDraftError(
        createError instanceof Error
          ? createError.message
          : "Unable to save draft."
      );
    } finally {
      setSavingDraft(false);
    }
  }

  function commitTagInput() {
    if (!tagInput.trim()) {
      return;
    }

    setDraftForm((current) => ({
      ...current,
      tags: appendMarketplaceTags(current.tags, tagInput)
    }));
    setTagInput("");
  }

  function removeTag(tagToRemove: string) {
    setDraftForm((current) => ({
      ...current,
      tags: current.tags.filter((tag) => tag !== tagToRemove)
    }));
  }

  function handleTagInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" && event.key !== ",") {
      return;
    }

    event.preventDefault();
    commitTagInput();
  }

  async function regenerateListingTitle() {
    const title = await aiListingAssistantRef.current?.regenerateTitle();
    if (title === null || title === undefined) {
      return;
    }
    setDraftForm((current) => ({ ...current, title }));
  }

  async function regenerateListingDescription() {
    const productDescription =
      await aiListingAssistantRef.current?.regenerateDescription();
    if (productDescription === null || productDescription === undefined) {
      return;
    }
    setDraftForm((current) => ({ ...current, productDescription }));
  }

  async function regenerateListingTags() {
    const tags = await aiListingAssistantRef.current?.regenerateTags();
    if (!tags) {
      return;
    }
    setDraftForm((current) => ({ ...current, tags }));
    setTagInput("");
  }

  function handleDesignSelection(nextFiles: readonly File[]) {
    const nextFile = nextFiles[0] ?? null;
    if (!nextFile) {
      return;
    }

    setDesignFile(nextFile);
    setDraftError(null);
    setJobStatusMessage(
      createdProduct
        ? "Design source updated. Save draft to replace the attached artwork."
        : "Design source ready. Save draft when the listing is ready."
    );
  }

  function handleDesignInputChange(event: ChangeEvent<HTMLInputElement>) {
    handleDesignSelection(extractImageFiles(event.target.files));
    event.target.value = "";
  }

  function queueMockupFiles(nextFiles: readonly File[]) {
    if (!nextFiles.length) {
      return;
    }

    const { acceptedFiles, availableSlots } = queueMarketplaceFiles(
      totalMockupCount,
      nextFiles
    );
    setQueuedMockups((current) => [
      ...current,
      ...acceptedFiles.map((file) => createQueuedMockup(file))
    ]);

    if (nextFiles.length > acceptedFiles.length) {
      setDraftError(
        `Product Studio allows up to ${ETSY_MOCKUP_LIMIT} listing images. You can add ${availableSlots} more right now.`
      );
    } else {
      setDraftError(null);
      setJobStatusMessage(
        createdProduct
          ? "Images added. Upload them when you are ready."
          : "Images added. The first image becomes the hero when the product is created."
      );
    }
  }

  function handleMockupSelection(event: ChangeEvent<HTMLInputElement>) {
    queueMockupFiles(extractImageFiles(event.target.files));

    event.target.value = "";
  }

  function handleDesignDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDesignDropActive(false);
    handleDesignSelection(extractImageFiles(event.dataTransfer.files));
  }

  function handleMockupDropSelection(event: DragEvent<HTMLElement>) {
    if (!hasFileTransferData(event.dataTransfer.types)) {
      return;
    }

    event.preventDefault();
    setMockupDropActive(false);
    queueMockupFiles(extractImageFiles(event.dataTransfer.files));
  }

  function handleMockupContainerDragOver(event: DragEvent<HTMLDivElement>) {
    if (!hasFileTransferData(event.dataTransfer.types)) {
      return;
    }

    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setMockupDropActive(true);
  }

  function handleMockupContainerDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!hasFileTransferData(event.dataTransfer.types)) {
      return;
    }

    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return;
    }

    setMockupDropActive(false);
  }

  function handleMockupDragStart(event: DragEvent<HTMLDivElement>, orderKey: string) {
    setDraggedMockupKey(orderKey);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", orderKey);
  }

  async function handleMockupDrop(
    event: DragEvent<HTMLDivElement>,
    targetOrderKey: string
  ) {
    event.preventDefault();
    event.stopPropagation();

    const fromOrderKey = draggedMockupKey ?? event.dataTransfer.getData("text/plain");

    if (!fromOrderKey) {
      setDraggedMockupKey(null);
      return;
    }

    const fromIndex = mockupOrder.findIndex(
      (orderedItem) => serializeOrderedMockupItem(orderedItem) === fromOrderKey
    );
    const targetIndex = mockupOrder.findIndex(
      (orderedItem) => serializeOrderedMockupItem(orderedItem) === targetOrderKey
    );

    if (fromIndex < 0 || targetIndex < 0 || fromIndex === targetIndex) {
      setDraggedMockupKey(null);
      return;
    }

    const nextOrder = reorderItems(mockupOrder, fromIndex, targetIndex);
    setMockupOrder(nextOrder);
    setDraggedMockupKey(null);
    setDraftError(null);

    setMockupOrderDirty(true);
    setJobStatusMessage(
      createdProduct
        ? "Image order updated. Save changes to apply it."
        : "Image order updated. The first image becomes the hero when the product is created."
    );
  }

  function removeQueuedMockup(queueId: string) {
    setQueuedMockups((current) => current.filter((item) => item.id !== queueId));
    setJobStatusMessage("Image removed.");
  }

  async function handleUploadMockups() {
    if (!createdProduct || (queuedMockups.length === 0 && !mockupOrderDirty)) {
      return;
    }

    setUploadingMockups(true);
    setDraftError(null);

    try {
      const refreshedProduct = await persistMockupOrdering(createdProduct);
      setQueuedMockups([]);
      setMockupOrderDirty(false);
      setCreatedProduct(refreshedProduct);
      setJobStatusMessage("Images uploaded to the product.");
    } catch (uploadError) {
      setDraftError(
        uploadError instanceof Error
          ? uploadError.message
          : "Unable to upload images."
      );
    } finally {
      setUploadingMockups(false);
    }
  }

  async function handlePublish() {
    if (!createdProduct) {
      return;
    }
    const firstIncomplete = readiness.find((item) => !item.complete);
    if (firstIncomplete) {
      setDraftError("Save the current product and finish each send requirement first.");
      focusPublishReadinessField(firstIncomplete.field);
      return;
    }

    setPublishing(true);
    setDraftError(null);

    try {
      const response = await publishProduct(createdProduct.id, createdProduct.revision);
      setLatestPublishingJob(response.job);
      setCreatedProduct((current) =>
        current ? withProductPublishingStatus(current, response.job.status) : current
      );
      setJobStatusMessage(formatQueuedPushMessage(storefrontAction));

      const publishResult = await pollPublishingJobUntilSettled({
        jobId: response.job.id,
        fetchJob: fetchPublishingJob,
        onStatus: (status) => {
          setJobStatusMessage(formatPushStatusMessage(storefrontAction, status));
        }
      });
      const settledJob = await fetchPublishingJob(response.job.id);
      setLatestPublishingJob(settledJob);

      const refreshedProduct = await fetchProduct(createdProduct.id);
      setCreatedProduct(refreshedProduct);
      setJobStatusMessage(
        publishResult.timedOut && isPublishingActiveStatus(refreshedProduct.publishing_status)
          ? `Still sending to ${storefrontAction}. This page will keep refreshing until it is done.`
          : formatPushStatusMessage(storefrontAction, refreshedProduct.publishing_status)
      );
    } catch (publishError) {
      if (publishError instanceof BackendApiError) {
        const firstField = publishError.fields[0]?.field;
        if (firstField) {
          focusPublishReadinessField(firstField);
        } else if (publishError.code === "stale_product_revision") {
          focusPublishReadinessField("saved_changes");
        }
      }
      setDraftError(
        publishError instanceof Error
          ? publishError.message
          : `Unable to push the product to ${storefrontAction}.`
      );
    } finally {
      setPublishing(false);
    }
  }

  if (
    shouldBlockProductStudioForStoreSelection({
      selectedStoreId,
      selectionReady,
      storesLoading
    })
  ) {
    return (
      <div className="flex min-h-[calc(100dvh-2rem)] flex-col">
        <PageHeader
          title="Product Studio"
          description="Build a product from one saved blueprint."
          preserveActionSpace
        />
        <section className="flex-1 rounded-lg border border-border bg-card px-5 py-5 sm:px-6">
          <div className="mx-auto w-full max-w-xl text-center">
            <h2 className="text-base font-semibold text-foreground">
              Choose a store to continue
            </h2>
            <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
              Product Studio creates products for one fulfillment store at a time.
            </p>

            {storeConnections.length > 0 ? (
              <div className="mx-auto mt-5 max-w-sm text-left">
                <Select onValueChange={setSelectedStoreId}>
                  <SelectTrigger
                    id="product-studio-store"
                    aria-label="Store"
                    className="h-9 w-full bg-card text-sm font-medium"
                  >
                    <SelectValue placeholder="Select a store" />
                  </SelectTrigger>
                  <SelectContent className="max-h-[min(400px,var(--radix-select-content-available-height))] border-border/80 bg-card">
                    {Object.entries(groupedStoreConnections).map(([provider, stores], index) => (
                      <SelectGroup key={provider}>
                        {index > 0 ? <SelectSeparator /> : null}
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
            ) : (
              <div className="mt-6 border-t border-border pt-5">
                <p className="text-sm text-muted-foreground">
                  Connect a fulfillment store before creating a product.
                </p>
                <Button asChild className="mt-4">
                  <a href="/settings">Open Settings</a>
                </Button>
              </div>
            )}
          </div>
        </section>
      </div>
    );
  }

  if (loading || storesLoading || !selectionReady) {
    return (
      <>
        <PageHeader
          title="Product Studio"
          description="Build a product from one saved blueprint."
          preserveActionSpace
        />
        <ProductStudioSkeleton />
      </>
    );
  }

  if (error) {
    return (
      <>
        <PageHeader
          title="Product Studio"
          description="Build a product from one saved blueprint."
          preserveActionSpace
        />
        <ResourceError message={error} onRetry={() => void loadStudio()} />
      </>
    );
  }

  if (!filteredBlueprints.length) {
    return (
      <>
        <PageHeader
          title="Product Studio"
          description="Build a product from one saved blueprint."
          preserveActionSpace
        />
        <EmptyState
          title="No blueprints available for this store"
          description="Create a blueprint first, then come back here to build a product."
          action={
            <Button asChild className="w-fit">
              <a href="/blueprints">Open Blueprints</a>
            </Button>
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Product Studio"
        description="Build a store-ready product from a saved blueprint."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => void loadStudio()}>
              <RefreshCw data-icon="inline-start" />
              Refresh data
            </Button>
          </div>
        }
      />

      <div className="grid min-w-0 max-w-full items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 max-w-full overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex flex-col gap-3 border-b border-border bg-background/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-foreground">
                {draftForm.title || selectedBlueprint?.name || "Untitled listing"}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>{selectedBlueprint?.name ?? "No blueprint selected"}</span>
                <span>{totalMockupCount}/{ETSY_MOCKUP_LIMIT} images</span>
                <span>{draftForm.tags.length}/{ETSY_TAG_LIMIT} tags</span>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <StatusBadge value={createdProduct?.status ?? "Not started"} />
              <StatusBadge value={createdProduct?.publishing_status ?? "Not started"} />
            </div>
          </div>
            <SurfaceSection
              title="Images"
              bodyClassName="space-y-6"
            >
              <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
                <div className="flex flex-col gap-2">
                  <Label className="text-muted-foreground">Design source</Label>
                  <Input
                    id="product-studio-design-input"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="sr-only"
                    onChange={handleDesignInputChange}
                  />
                  <label
                    id="publish-design"
                    tabIndex={-1}
                    htmlFor="product-studio-design-input"
                    className={[
                      "flex min-h-80 cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-input bg-background p-6 text-center transition-colors",
                      designDropActive ? "border-primary/55 bg-accent/15" : "hover:border-primary/45 hover:bg-accent/10"
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    onDragOver={(event) => {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = "copy";
                      setDesignDropActive(true);
                    }}
                    onDragLeave={() => setDesignDropActive(false)}
                    onDrop={handleDesignDrop}
                  >
                    {designSurfacePreviewUrl ? (
                      <>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={designSurfacePreviewUrl}
                          alt="Uploaded design preview"
                          className="h-52 w-full rounded-md object-contain"
                        />
                        <div className="mt-4 text-sm text-muted-foreground">
                          {designFile?.name
                            ? truncateFileName(designFile.name)
                            : createdProduct?.design_asset?.file_name
                              ? truncateFileName(createdProduct.design_asset.file_name)
                              : "Attached design source"}
                        </div>
                        <div className="mt-2 text-xs text-muted-foreground">
                          Drop a new image here or click to browse.
                        </div>
                      </>
                    ) : (
                      <>
                        <ImagePlus className="mx-auto h-9 w-9 text-muted-foreground" />
                        <div className="mt-3 text-sm font-medium">Upload source artwork</div>
                        <div className="mt-2 text-xs text-muted-foreground">
                          Drop an image here or click to browse.
                        </div>
                      </>
                    )}
                  </label>
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="text-muted-foreground">Design description</Label>
                  <Textarea
                    className="min-h-80 leading-6"
                    placeholder="Describe the artwork itself: subject, palette, mood, room context, visual style, and anything the image alone does not explain."
                    value={draftForm.designDescription}
                    onChange={(event) =>
                      setDraftForm((current) => ({
                        ...current,
                        designDescription: event.target.value
                      }))
                    }
                  />
                </div>
              </div>

              <Input
                id="product-studio-mockup-input"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                className="sr-only"
                onChange={handleMockupSelection}
              />

              <div id="publish-mockups" tabIndex={-1} className="border-t border-border pt-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-medium text-foreground">
                      Add images
                    </h3>
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-2 text-xs text-muted-foreground">
                    <span>{totalMockupCount}/{ETSY_MOCKUP_LIMIT} prepared</span>
                    {createdProduct ? (
                      <Button
                        variant="outline"
                        className="h-8 px-3 text-xs"
                        onClick={() => void handleUploadMockups()}
                        disabled={queuedMockups.length === 0 || uploadingMockups}
                      >
                        {uploadingMockups ? <LoaderCircle className="animate-spin" /> : <Upload />}
                        Upload images
                      </Button>
                    ) : null}
                  </div>
                </div>

                <div
                  className={[
                    "mt-4 rounded-md border border-border bg-background/40 transition-colors",
                    mockupDropActive ? "border-primary/55 bg-accent/10" : ""
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onDragOver={handleMockupContainerDragOver}
                  onDragLeave={handleMockupContainerDragLeave}
                  onDrop={handleMockupDropSelection}
                >
                  <div className="p-4">

                    <div className="grid auto-rows-fr grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-5">
                      {mockupPreviewItems.map((mockup, index) => (
                        <div
                          key={mockup.id}
                          className={[
                            "group relative aspect-square overflow-hidden rounded-md border border-border bg-background transition duration-150 ease-out",
                            index === 0 ? "sm:col-span-2 sm:row-span-2" : "",
                            "cursor-grab hover:scale-[1.01] hover:border-primary/45 active:cursor-grabbing",
                            draggedMockupKey === mockup.orderKey
                              ? "opacity-60"
                              : ""
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          draggable
                          onDragStart={(event) => handleMockupDragStart(event, mockup.orderKey)}
                          onDragEnd={() => setDraggedMockupKey(null)}
                          onDragOver={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                          }}
                          onDrop={(event) => void handleMockupDrop(event, mockup.orderKey)}
                        >
                          {mockup.url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={mockup.url}
                            alt={index === 0 ? "Hero listing image" : `Listing image ${mockup.badge}`}
                            className="pointer-events-none h-full w-full select-none object-cover [-webkit-user-drag:none]"
                            loading={index === 0 ? "eager" : "lazy"}
                            decoding="async"
                            draggable={false}
                            />
                          ) : null}
                          <div className="pointer-events-none absolute left-2 top-2 rounded-md border border-border bg-card/95 px-2 py-1 text-[10px] font-medium text-muted-foreground">
                            {index === 0 ? "Hero" : mockup.badge}
                          </div>
                          {mockup.detail ? (
                            <div className="pointer-events-none absolute bottom-2 left-2 rounded-md border border-border bg-card/95 px-2 py-1 text-[10px] font-medium text-muted-foreground">
                              {mockup.detail}
                            </div>
                          ) : null}
                          {mockup.source === "queued" ? (
                            <>
                              <button
                                type="button"
                                aria-label="Remove image"
                                className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-card/95 text-muted-foreground opacity-90 transition hover:bg-destructive/15 hover:text-destructive sm:opacity-0 sm:group-hover:opacity-100"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  if (mockup.queueId) {
                                    removeQueuedMockup(mockup.queueId);
                                  }
                                }}
                              >
                                <X className="h-3.5 w-3.5" />
                              </button>
                              <div className="pointer-events-none absolute bottom-2 right-2 rounded-md border border-border bg-card/95 p-1 text-muted-foreground opacity-90 transition sm:opacity-0 sm:group-hover:opacity-100">
                                <GripVertical className="h-3.5 w-3.5" />
                              </div>
                            </>
                          ) : null}
                        </div>
                      ))}

                      {canQueueMoreMockups ? (
                      <label
                        htmlFor="product-studio-mockup-input"
                        className={[
                          "flex aspect-square cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-input bg-card/40 px-4 text-center transition-colors hover:border-primary/45 hover:bg-accent/15",
                          mockupPreviewItems.length === 0 ? "sm:col-span-2 sm:row-span-2" : ""
                        ]
                          .filter(Boolean)
                          .join(" ")}
                      >
                        <ImagePlus className={mockupPreviewItems.length === 0 ? "h-8 w-8 text-muted-foreground" : "h-6 w-6 text-muted-foreground"} />
                        <div className={mockupPreviewItems.length === 0 ? "mt-3 text-base font-semibold text-foreground" : "mt-3 text-sm font-medium text-foreground"}>
                          Add images
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {remainingMockupSlots} remaining
                        </div>
                        <div className="mt-2 text-[11px] text-muted-foreground">
                          Drop images here or click to browse.
                        </div>
                      </label>
                    ) : null}
                  </div>
                  </div>
                </div>
              </div>
            </SurfaceSection>

            <AIListingAssistant
              ref={aiListingAssistantRef}
              product={createdProduct}
              onRegenerationStateChange={setRegeneratingField}
              onApplied={(product) => {
                setCreatedProduct(product);
                setDraftForm((current) => ({
                  ...current,
                  title: product.title,
                  productDescription: product.description ?? "",
                  designDescription:
                    product.design_description ?? current.designDescription,
                  tags: product.tags
                }));
              }}
            />

            <SurfaceSection
              title="Listing content"
              bodyClassName="space-y-6"
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-3">
                  <Label className="text-muted-foreground">Product title</Label>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {draftForm.title.length}/140
                  </span>
                </div>
                <div className="relative">
                  <AutoResizeTextarea
                    id="publish-title"
                    className="pr-16 leading-5 disabled:bg-muted/35"
                    maxLength={140}
                    value={draftForm.title}
                    disabled={regeneratingField === "title"}
                    onChange={(event) =>
                      setDraftForm((current) => ({
                        ...current,
                        title: event.target.value
                      }))
                    }
                  />
                  <AIFieldRegenerateButton
                    label="product title"
                    loading={regeneratingField === "title"}
                    disabled={regeneratingField !== null}
                    fillHeight
                    onClick={() => void regenerateListingTitle()}
                  />
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-3">
                  <Label className="text-muted-foreground">Product description</Label>
                  <AIFieldRegenerateButton
                    label="product description"
                    loading={regeneratingField === "description"}
                    disabled={regeneratingField !== null}
                    inline
                    onClick={() => void regenerateListingDescription()}
                  />
                </div>
                <Textarea
                  className="h-[580px] leading-6 disabled:bg-muted/35"
                  placeholder="Write the marketplace listing description."
                  value={draftForm.productDescription}
                  disabled={regeneratingField === "description"}
                  onChange={(event) =>
                    setDraftForm((current) => ({
                      ...current,
                      productDescription: event.target.value
                    }))
                  }
                />
              </div>

              <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_220px]">
                <div className="flex flex-col gap-2">
                  <Label className="text-muted-foreground">Tags</Label>
                  <div
                    className={[
                      "rounded-md border border-border bg-background/40 transition-colors",
                      regeneratingField === "tags" ? "bg-muted/35 text-muted-foreground" : ""
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    <div className="relative flex items-start justify-between gap-3 border-b border-border px-4 py-3 pr-[4.5rem]">
                      <div>
                        <div className="text-sm font-medium text-foreground">
                          Search tags
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {draftForm.tags.length}/{ETSY_TAG_LIMIT}
                      </div>
                      <AIFieldRegenerateButton
                        label="tags"
                        loading={regeneratingField === "tags"}
                        disabled={regeneratingField !== null}
                        fillHeight
                        onClick={() => void regenerateListingTags()}
                        className="rounded-br-none border-y-0 border-r-0"
                      />
                    </div>
                    {draftForm.tags.length < ETSY_TAG_LIMIT ? (
                      <div className="flex items-center gap-2 px-4 py-3">
                        <Input
                          className="h-10 bg-background"
                          placeholder="Shape, color, style, function, etc."
                          value={tagInput}
                          disabled={regeneratingField === "tags"}
                          onChange={(event) => setTagInput(event.target.value)}
                          onKeyDown={handleTagInputKeyDown}
                          onBlur={commitTagInput}
                        />
                        <Button
                          variant="outline"
                          className="h-10 shrink-0"
                          onClick={commitTagInput}
                          disabled={!tagInput.trim() || regeneratingField === "tags"}
                        >
                          Add tag
                        </Button>
                      </div>
                    ) : null}
                    <div className="flex flex-wrap gap-2 px-4 py-4">
                      {draftForm.tags.map((tag) => (
                        <button
                          key={tag}
                          type="button"
                          onClick={() => removeTag(tag)}
                          disabled={regeneratingField === "tags"}
                          className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent/20"
                        >
                          <span>{tag}</span>
                          <X className="h-4 w-4" />
                        </button>
                      ))}
                    </div>
                    <div className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
                      {draftForm.tags.length >= ETSY_TAG_LIMIT
                        ? `All ${ETSY_TAG_LIMIT} used`
                        : `${draftForm.tags.length} of ${ETSY_TAG_LIMIT} used`}
                      {" • "}
                      Paste comma-separated tags and press Enter to add them all at once.
                    </div>
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <Label className="text-muted-foreground">SKU</Label>
                  <Input
                    value={draftForm.sku}
                    onChange={(event) =>
                      setDraftForm((current) => ({
                        ...current,
                        sku: event.target.value
                      }))
                    }
                    placeholder="Optional SKU prefix or listing code"
                  />
                </div>
              </div>
            </SurfaceSection>
        </div>

        <aside className="min-w-0 max-w-full overflow-hidden rounded-lg border border-border bg-card">
          <ProductControlsPanel
            productStatus={createdProduct?.status ?? "Not started"}
            publishingStatus={createdProduct?.publishing_status ?? "Not started"}
            metaText={productControlsMetaText}
            submittedMetaText={submittedMetaText}
            statusMessage={jobStatusMessage ?? formatPushHelperCopy(storefrontAction)}
            readiness={readiness}
            onReadinessSelect={focusPublishReadinessField}
            saveLabel={createdProduct?.status === "published" ? "Save changes" : "Save draft"}
            onSave={() => void handleSaveDraft()}
            saving={savingDraft}
            saveDisabled={saveDisabled}
            publishLabel={`Send to ${storefrontAction}`}
            onPublish={() => void handlePublish()}
            publishing={publishing}
            publishDisabled={publishDisabled}
            errorMessage={draftError}
            errorDetail={
              latestPublishingJob?.status === "failed"
                ? latestPublishingJob.error_message
                : null
            }
          />
          <SurfaceSection
            title="Blueprint"
            bodyClassName="space-y-4"
          >
            <div className="flex flex-col gap-2">
              <Label className="text-muted-foreground">Select blueprint</Label>
              <Select
                value={selectedBlueprintId}
                onValueChange={(value) => {
                  const nextBlueprint =
                    filteredBlueprints.find((blueprint) => blueprint.id === value) ??
                    null;
                  setSelectedBlueprintId(value);
                  setDraftForm(buildDraftForm(nextBlueprint));
                  setCreatedProduct(null);
                  setLatestPublishingJob(null);
                  setQueuedMockups([]);
                  setMockupOrder([]);
                  setMockupOrderDirty(false);
                  setDraggedMockupKey(null);
                  setJobStatusMessage(null);
                  setDraftError(null);
                }}
              >
                <SelectTrigger id="publish-blueprint">
                  <SelectValue placeholder="Select Blueprint" />
                </SelectTrigger>
                <SelectContent>
                  {filteredBlueprints.map((blueprint) => (
                    <SelectItem key={blueprint.id} value={blueprint.id}>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-foreground">
                          {blueprint.name}
                        </div>
                        <StoreLabel
                          source={blueprint}
                          secondaryVariant="badge"
                          nameClassName="sr-only"
                          className="mt-1"
                        />
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {selectedBlueprint ? (
              <>
                <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-foreground">
                      {getBlueprintCardTitle(selectedBlueprint)}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {getBlueprintCardSubtitle(selectedBlueprint)}
                    </div>
                  </div>
                  <StatusBadge value={selectedBlueprint.status} />
                </div>

                <div className="rounded-md border border-border bg-background px-3">
                  <RailRow label="Partner" value={providerLabel(selectedBlueprint.provider)} />
                  <RailRow
                    label="Connected store"
                    value={<StoreLabel source={selectedBlueprint} secondaryVariant="badge" />}
                  />
                  <RailRow
                    label="Product type"
                    value={formatBlueprintProductType(selectedBlueprint)}
                  />
                  <RailRow
                    label="Variants"
                    value={formatBlueprintVariantSummary(selectedBlueprint)}
                  />
                  <RailRow
                    label="Artwork"
                    value={formatBlueprintArtworkSummary(selectedBlueprint)}
                  />
                  <RailRow
                    label="Base cost"
                    value={
                      selectedBlueprint.base_cost_amount !== null
                        ? formatCurrency(
                            selectedBlueprint.base_cost_amount,
                            selectedBlueprint.currency ?? "USD"
                          )
                        : "—"
                    }
                  />
                </div>
              </>
            ) : null}
          </SurfaceSection>

          <SurfaceSection
            title="Pricing"
            bodyClassName="space-y-4"
          >
            <div className="flex flex-col gap-2">
              <Label className="text-muted-foreground">Retail price</Label>
              <Input
                id="publish-retail-price"
                value={draftForm.retailPrice}
                onChange={(event) =>
                  setDraftForm((current) => ({
                    ...current,
                    retailPrice: event.target.value
                  }))
                }
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label className="text-muted-foreground">Currency</Label>
              <Input
                id="publish-currency"
                value={draftForm.currency}
                onChange={(event) =>
                  setDraftForm((current) => ({
                    ...current,
                    currency: event.target.value
                  }))
                }
              />
            </div>
            <div className="rounded-md border border-border bg-background px-3">
              <RailRow
                label="Retail preview"
                value={
                  hasRetailPrice
                    ? formatCurrency(parsedRetailPrice, draftForm.currency || "USD")
                    : "—"
                }
              />
              <RailRow
                label="Projected margin"
                value={
                  projectedMargin !== null
                    ? formatCurrency(projectedMargin, draftForm.currency || "USD")
                    : "—"
                }
              />
            </div>
          </SurfaceSection>

        </aside>
      </div>
    </>
  );
}
