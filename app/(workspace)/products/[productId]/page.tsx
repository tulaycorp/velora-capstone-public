"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  GripVertical,
  ImagePlus,
  LoaderCircle,
  X
} from "lucide-react";
import type { ChangeEvent, DragEvent, KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PageHeader } from "@/components/workspace/page-header";
import { DeleteProductDialog } from "@/components/workspace/delete-product-dialog";
import { ProductControlsPanel } from "@/components/workspace/product-controls-panel";
import {
  ProductEditorRailRow as RailRow,
  ProductEditorSection as SurfaceSection
} from "@/components/workspace/product-editor-primitives";
import { AIListingAssistant, type AIListingAssistantHandle } from "@/components/workspace/ai-listing-assistant";
import { AIFieldRegenerateButton } from "@/components/workspace/ai-field-regenerate-button";
import {
  ProductDetailSkeleton,
  ResourceError
} from "@/components/workspace/resource-state";
import { StoreLabel } from "@/components/workspace/store-label";
import { StatusBadge } from "@/components/workspace/status-badge";
import { Button } from "@/components/ui/button";
import { AutoResizeTextarea } from "@/components/ui/auto-resize-textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { AIGenerationField } from "@/lib/ai-generation-review";
import {
  buildOrderedMockupIds,
  serializeOrderedMockupItem,
  syncOrderedMockups,
  type OrderedMockupItem
} from "../../product-detail-mockup-state";
import {
  appendMarketplaceTags,
  ETSY_MOCKUP_LIMIT,
  ETSY_TAG_LIMIT,
  getMarketplaceImageStatusLabel,
  hasFileTransferData,
  queueMarketplaceFiles,
  reorderItems
} from "../../product-studio-state";
import {
  BackendApiError,
  deleteMockup,
  fetchBlueprints,
  fetchProduct,
  fetchPublishingJob,
  fetchPublishingJobs,
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

type ProductDetailForm = {
  title: string;
  description: string;
  designDescription: string;
  tags: string[];
  sku: string;
  retailPrice: string;
  currency: string;
};

type ProductDetailPageData = {
  blueprints: Blueprint[];
  latestPublishingJob: PublishingJob | null;
  product: Product;
};

function buildForm(product: Product): ProductDetailForm {
  return {
    title: product.title,
    description: product.description ?? "",
    designDescription: product.design_description ?? "",
    tags: product.tags,
    sku: product.sku ?? "",
    retailPrice: product.retail_price !== null ? String(product.retail_price) : "",
    currency: product.currency ?? "USD"
  };
}

export default function ProductDetailPage() {
  const params = useParams<{ productId: string }>();
  const router = useRouter();
  const aiListingAssistantRef = useRef<AIListingAssistantHandle>(null);
  const [regeneratingField, setRegeneratingField] =
    useState<AIGenerationField | null>(null);
  const productId = params?.productId ?? "";
  const loadProductDetail = useCallback(async () => {
    if (!productId) {
      throw new Error("Product not found.");
    }

    const [nextProduct, nextBlueprints, publishingJobs] = await Promise.all([
      fetchProduct(productId),
      fetchBlueprints().catch(() => []),
      fetchPublishingJobs(productId).catch(() => [])
    ]);

    return {
      blueprints: nextBlueprints,
      latestPublishingJob: publishingJobs[0] ?? null,
      product: nextProduct
    };
  }, [productId]);
  const {
    data: pageData,
    error,
    load,
    loading,
    setData: setPageData
  } = useCachedWorkspaceResource<ProductDetailPageData>({
    cacheKey: workspacePageCacheKeys.product(productId || "missing"),
    loadResource: loadProductDetail
  });
  const [form, setForm] = useState<ProductDetailForm | null>(() =>
    pageData?.product ? buildForm(pageData.product) : null
  );
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
  const [deletingMockupId, setDeletingMockupId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const hydratedProductIdRef = useRef<string | null>(pageData?.product.id ?? null);
  const product = pageData?.product ?? null;
  const latestPublishingJob = pageData?.latestPublishingJob ?? null;
  const blueprints = useMemo(() => pageData?.blueprints ?? [], [pageData?.blueprints]);
  const setProduct = useCallback(
    (nextValue: React.SetStateAction<Product | null>) => {
      setPageData((current) => {
        if (!current) {
          return current;
        }

        const nextProduct =
          typeof nextValue === "function"
            ? nextValue(current.product)
            : nextValue;

        if (!nextProduct) {
          return current;
        }

        return {
          ...current,
          product: nextProduct
        };
      });
    },
    [setPageData]
  );
  const setLatestPublishingJob = useCallback(
    (job: PublishingJob) => {
      setPageData((current) => current ? { ...current, latestPublishingJob: job } : current);
    },
    [setPageData]
  );
  const blueprint = useMemo(
    () =>
      blueprints.find((candidate) => candidate.id === product?.blueprint_id) ?? null,
    [blueprints, product?.blueprint_id]
  );

  const sortedMockups = useMemo(
    () => [...(product?.mockups ?? [])].sort((left, right) => left.position - right.position),
    [product?.mockups]
  );

  const storefrontAction = product
    ? storefrontActionLabel(product.provider_storefront_type)
    : "store";
  const activeProductId = product?.id ?? null;
  const activeProductPublishingStatus = product?.publishing_status ?? null;
  const publishingActive = isPublishingActiveStatus(product?.publishing_status);
  const productControlsMetaText = product
    ? `Last saved ${formatDateTime(product.updated_at)}`
    : "Loading product details.";
  const submittedMetaText = latestPublishingJob
    ? `Submitted revision ${latestPublishingJob.product_revision} ${formatDateTime(latestPublishingJob.created_at)}${
        product && product.revision > latestPublishingJob.product_revision
          ? ` · Current saved revision ${product.revision} is newer; this send uses revision ${latestPublishingJob.product_revision}`
          : ""
      }`
    : null;
  const existingMockupCount = product?.mockup_count ?? 0;
  const totalMockupCount = existingMockupCount + queuedMockups.length;
  const remainingMockupSlots = Math.max(ETSY_MOCKUP_LIMIT - totalMockupCount, 0);
  const canQueueMoreMockups = totalMockupCount < ETSY_MOCKUP_LIMIT;
  const parsedRetailPrice = form?.retailPrice ? Number(form.retailPrice) : null;
  const hasRetailPrice =
    form?.retailPrice.trim() !== ""
    && parsedRetailPrice !== null
    && Number.isFinite(parsedRetailPrice);
  const projectedMargin =
    hasRetailPrice
    && product?.cost_amount !== null
    && product?.cost_amount !== undefined
      ? parsedRetailPrice - product.cost_amount
      : null;
  const designSurfacePreviewUrl =
    designPreviewUrl ?? product?.design_asset?.public_url ?? null;
  const attachedMockupsById = useMemo(
    () => new Map(sortedMockups.map((mockup) => [mockup.id, mockup])),
    [sortedMockups]
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
    () => sortedMockups.map((mockup) => mockup.id),
    [sortedMockups]
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

  const editorDirty = product && form
    ? isProductEditorDirty({
        product,
        values: form,
        pendingDesign: Boolean(designFile),
        pendingMockups: queuedMockups.length > 0,
        mockupOrderDirty
      })
    : true;
  const readiness = buildPublishReadiness({
    blueprintReady: Boolean(blueprint?.validated_at && blueprint.variant_count > 0),
    designSaved: Boolean(product?.design_asset?.public_url),
    mockupCount: sortedMockups.filter((mockup) => Boolean(mockup.public_url)).length,
    title: form?.title ?? "",
    retailPrice: form?.retailPrice ?? "",
    currency: form?.currency ?? "",
    editorDirty
  });
  const publishDisabled =
    publishing
    || publishingActive
    || saving
    || Boolean(deletingMockupId)
    || !hasPendingStorefrontChanges(product?.revision ?? 0, latestPublishingJob)
    || readiness.some((item) => !item.complete);
  const saveDisabled =
    !editorDirty
    || publishingActive;

  useEffect(() => {
    if (!product) {
      hydratedProductIdRef.current = null;
      setForm(null);
      return;
    }

    if (hydratedProductIdRef.current === product.id) {
      return;
    }

    hydratedProductIdRef.current = product.id;
    setForm(buildForm(product));
  }, [product]);

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
    if (!activeProductId || !isPublishingActiveStatus(activeProductPublishingStatus)) {
      return;
    }

    const productId = activeProductId;
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

        setProduct(refreshedProduct);
        setStatusMessage(
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
  }, [activeProductId, activeProductPublishingStatus, setProduct]);

  async function persistMockupOrdering(currentProduct: Product) {
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
          currentProduct.id,
          queuedFile,
          currentProduct.mockup_count + index
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
      return currentProduct;
    }

    return reorderMockups(currentProduct.id, orderedMockupIds);
  }

  async function handleSaveDraft() {
    if (!product || !form) {
      return;
    }

    setSaving(true);
    setFormError(null);

    try {
      const designAsset = designFile ? await uploadDesignAsset(designFile) : null;
      const savedProduct = await updateProduct(product.id, {
        ...buildProductEditorListingInput(form, product.title),
        design_asset_id: designAsset?.id,
        expected_revision: product.revision,
        status: product.status === "published" ? product.status : "draft"
      });

      if (queuedMockups.length > 0 || mockupOrderDirty) {
        try {
          const refreshedProduct = await persistMockupOrdering(savedProduct);
          setQueuedMockups([]);
          setMockupOrderDirty(false);
          setProduct(refreshedProduct);
          setForm(buildForm(refreshedProduct));
          setDesignFile(null);
          setStatusMessage("Changes saved and images attached.");
        } catch (uploadError) {
          setProduct(savedProduct);
          setForm(buildForm(savedProduct));
          setDesignFile(null);
          setFormError(
            uploadError instanceof Error
              ? uploadError.message
              : "Changes saved, but some images could not attach yet."
          );
          setStatusMessage("Changes saved. Some images still need to upload.");
        }
      } else {
        setProduct(savedProduct);
        setForm(buildForm(savedProduct));
        setDesignFile(null);
        setStatusMessage(savedProduct.status === "published" ? "Changes saved." : "Draft saved.");
      }
    } catch (saveError) {
      setFormError(
        saveError instanceof Error ? saveError.message : "Unable to save product."
      );
    } finally {
      setSaving(false);
    }
  }

  function commitTagInput() {
    if (!tagInput.trim() || !form) {
      return;
    }

    setForm({
      ...form,
      tags: appendMarketplaceTags(form.tags, tagInput)
    });
    setTagInput("");
  }

  function removeTag(tagToRemove: string) {
    if (!form) {
      return;
    }

    setForm({
      ...form,
      tags: form.tags.filter((tag) => tag !== tagToRemove)
    });
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
    setForm((current) => (current ? { ...current, title } : current));
  }

  async function regenerateListingDescription() {
    const description =
      await aiListingAssistantRef.current?.regenerateDescription();
    if (description === null || description === undefined) {
      return;
    }
    setForm((current) => (current ? { ...current, description } : current));
  }

  async function regenerateListingTags() {
    const tags = await aiListingAssistantRef.current?.regenerateTags();
    if (!tags) {
      return;
    }
    setForm((current) => (current ? { ...current, tags } : current));
    setTagInput("");
  }

  function handleDesignSelection(nextFiles: readonly File[]) {
    const nextFile = nextFiles[0] ?? null;
    if (!nextFile) {
      return;
    }

    setDesignFile(nextFile);
    setFormError(null);
    setStatusMessage("Design source updated. Save changes to replace the attached artwork.");
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
      setFormError(
        `This product allows up to ${ETSY_MOCKUP_LIMIT} listing images. You can add ${availableSlots} more right now.`
      );
    } else {
      setFormError(null);
      setStatusMessage("Images added. Save changes to upload them.");
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
    setFormError(null);
    setDraggedMockupKey(null);

    if (!product) {
      return;
    }

    setMockupOrderDirty(true);
    setStatusMessage("Image order updated. Save changes to apply it.");
  }

  function removeQueuedMockup(queueId: string) {
    setQueuedMockups((current) => current.filter((item) => item.id !== queueId));
    setStatusMessage("Image removed.");
  }

  async function handleDeleteAttachedMockup(mockupId: string) {
    if (!product) {
      return;
    }

    setDeletingMockupId(mockupId);
    setFormError(null);
    try {
      const refreshedProduct = await deleteMockup(product.id, mockupId);
      setProduct(refreshedProduct);
      setStatusMessage("Image removed.");
    } catch (deleteError) {
      setFormError(
        deleteError instanceof Error ? deleteError.message : "Unable to remove image."
      );
    } finally {
      setDeletingMockupId(null);
    }
  }

  async function handlePublish() {
    if (!product || !form) {
      return;
    }
    const firstIncomplete = readiness.find((item) => !item.complete);
    if (firstIncomplete) {
      setFormError("Save the current product and finish each send requirement first.");
      focusPublishReadinessField(firstIncomplete.field);
      return;
    }

    setPublishing(true);
    setFormError(null);
    try {
      const response = await publishProduct(product.id, product.revision);
      setLatestPublishingJob(response.job);
      setProduct((current) =>
        current ? withProductPublishingStatus(current, response.job.status) : current
      );
      setStatusMessage(formatQueuedPushMessage(storefrontAction));

      const publishResult = await pollPublishingJobUntilSettled({
        jobId: response.job.id,
        fetchJob: fetchPublishingJob,
        onStatus: (status) => {
          setStatusMessage(formatPushStatusMessage(storefrontAction, status));
        }
      });
      const settledJob = await fetchPublishingJob(response.job.id);
      setLatestPublishingJob(settledJob);

      const refreshedProduct = await fetchProduct(product.id);
      setProduct(refreshedProduct);
      setForm(buildForm(refreshedProduct));
      setStatusMessage(
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
      setFormError(
        publishError instanceof Error
          ? publishError.message
          : `Unable to push the product to ${storefrontAction}.`
      );
    } finally {
      setPublishing(false);
    }
  }

  if (loading) {
    return (
      <>
        <PageHeader
          title="Product"
          description="Loading product workspace."
          preserveActionSpace
        />
        <ProductDetailSkeleton />
      </>
    );
  }

  if (error || !product || !form) {
    return (
      <>
        <PageHeader
          title="Product"
          description="Edit details, images, pricing, and send status."
          preserveActionSpace
        />
        <ResourceError message={error ?? "Product not found."} onRetry={() => void load()} />
      </>
    );
  }

  return (
    <div className="min-w-0 max-w-full overflow-x-clip">
      <PageHeader
        title={
          <span className="flex min-w-0 w-full items-center gap-1.5">
            <Link
              href="/products"
              className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
            >
              Products
            </Link>
            <span className="shrink-0 font-normal text-muted-foreground/30">/</span>
            <span className="min-w-0 flex-1 truncate">{product.title}</span>
          </span>
        }
        description="Quick-edit the saved product in the same workspace used for product creation."
        action={
          <Button asChild variant="outline">
            <Link href="/products">
              <ArrowLeft data-icon="inline-start" />
              Products
            </Link>
          </Button>
        }
      />

      <div className="grid min-w-0 max-w-full items-start gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 max-w-full overflow-hidden rounded-lg border border-border bg-card">
          <div className="flex flex-col gap-3 border-b border-border bg-background/35 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-foreground">
                {form.title || product.title || "Untitled listing"}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>{blueprint?.name ?? product.product_type}</span>
                <span>{totalMockupCount}/{ETSY_MOCKUP_LIMIT} images</span>
                <span>{form.tags.length}/{ETSY_TAG_LIMIT} tags</span>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <StatusBadge value={product.status} />
              <StatusBadge value={product.publishing_status} />
            </div>
          </div>

          <SurfaceSection title="Images" bodyClassName="space-y-6">
            <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
              <div className="flex flex-col gap-2">
                <Label className="text-muted-foreground">Design source</Label>
                <Input
                  id="product-detail-design-input"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="sr-only"
                  onChange={handleDesignInputChange}
                />
                <label
                  id="publish-design"
                  tabIndex={-1}
                  htmlFor="product-detail-design-input"
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
                        alt="Product design preview"
                        className="h-52 w-full rounded-md object-contain"
                      />
                      <div className="mt-4 text-sm text-muted-foreground">
                        {designFile?.name
                          ? truncateFileName(designFile.name)
                          : product.design_asset?.file_name
                            ? truncateFileName(product.design_asset.file_name)
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
                  value={form.designDescription}
                  placeholder="Describe the artwork, style, subject, and details to guide listing generation."
                  onChange={(event) => setForm({ ...form, designDescription: event.target.value })}
                />
              </div>
            </div>

            <Input
              id="product-detail-mockup-input"
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
                        <button
                          type="button"
                          aria-label="Remove image"
                          className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-card/95 text-muted-foreground opacity-90 transition hover:bg-destructive/15 hover:text-destructive disabled:cursor-wait disabled:opacity-60 sm:opacity-0 sm:group-hover:opacity-100"
                          disabled={mockup.source === "attached" && deletingMockupId === mockup.mockupId}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (mockup.source === "queued" && mockup.queueId) {
                              removeQueuedMockup(mockup.queueId);
                              return;
                            }
                            if (mockup.mockupId) {
                              void handleDeleteAttachedMockup(mockup.mockupId);
                            }
                          }}
                        >
                          {mockup.source === "attached" && deletingMockupId === mockup.mockupId ? (
                            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <X className="h-3.5 w-3.5" />
                          )}
                        </button>
                        <div className="pointer-events-none absolute bottom-2 right-2 rounded-md border border-border bg-card/95 p-1 text-muted-foreground opacity-90 transition sm:opacity-0 sm:group-hover:opacity-100">
                          <GripVertical className="h-3.5 w-3.5" />
                        </div>
                      </div>
                    ))}

                    {canQueueMoreMockups ? (
                      <label
                        htmlFor="product-detail-mockup-input"
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
            product={product}
            onRegenerationStateChange={setRegeneratingField}
            onApplied={(updatedProduct) => {
              setProduct(updatedProduct);
              setForm(buildForm(updatedProduct));
              setStatusMessage("Vel suggestions applied.");
            }}
          />

          <SurfaceSection title="Listing content" bodyClassName="space-y-6">
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-3">
                <Label className="text-muted-foreground">Product title</Label>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {form.title.length}/140
                </span>
              </div>
              <div className="relative">
                <AutoResizeTextarea
                  id="publish-title"
                  className="pr-16 leading-5 disabled:bg-muted/35"
                  maxLength={140}
                  value={form.title}
                  disabled={regeneratingField === "title"}
                  onChange={(event) => setForm({ ...form, title: event.target.value })}
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
                value={form.description}
                disabled={regeneratingField === "description"}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
            </div>

            <div className="grid min-w-0 max-w-full gap-6 xl:grid-cols-[minmax(0,1fr)_220px]">
              <div className="flex min-w-0 flex-col gap-2">
                <Label className="text-muted-foreground">Tags</Label>
                <div
                  className={[
                    "min-w-0 max-w-full overflow-hidden rounded-md border border-border bg-background/40 transition-colors",
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
                      {form.tags.length}/{ETSY_TAG_LIMIT}
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
                  {form.tags.length < ETSY_TAG_LIMIT ? (
                    <div className="flex min-w-0 items-center gap-2 px-4 py-3">
                      <Input
                        className="h-10 min-w-0 bg-background"
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
                    {form.tags.map((tag) => (
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
                    {form.tags.length >= ETSY_TAG_LIMIT
                      ? `All ${ETSY_TAG_LIMIT} used`
                      : `${form.tags.length} of ${ETSY_TAG_LIMIT} used`}
                    {" • "}
                    Paste comma-separated tags and press Enter to add them all at once.
                  </div>
                </div>
              </div>

              <div className="flex min-w-0 flex-col gap-2">
                <Label className="text-muted-foreground">SKU</Label>
                <Input
                  value={form.sku}
                  onChange={(event) => setForm({ ...form, sku: event.target.value })}
                  placeholder="Optional SKU prefix or listing code"
                />
              </div>
            </div>
          </SurfaceSection>
        </div>

        <aside className="min-w-0 max-w-full overflow-hidden rounded-lg border border-border bg-card">
          <ProductControlsPanel
            productStatus={product.status}
            publishingStatus={product.publishing_status}
            metaText={productControlsMetaText}
            submittedMetaText={submittedMetaText}
            statusMessage={statusMessage ?? formatPushHelperCopy(storefrontAction)}
            readiness={readiness}
            onReadinessSelect={focusPublishReadinessField}
            saveLabel={product.status === "published" ? "Save changes" : "Save draft"}
            onSave={() => void handleSaveDraft()}
            saving={saving}
            saveDisabled={saveDisabled}
            publishLabel={`Send to ${storefrontAction}`}
            onPublish={() => void handlePublish()}
            publishing={publishing}
            publishDisabled={publishDisabled}
            errorMessage={formError}
            errorDetail={
              latestPublishingJob?.status === "failed"
                ? latestPublishingJob.error_message
                : null
            }
          />

          <div id="publish-blueprint" tabIndex={-1}>
            <SurfaceSection title="Blueprint" bodyClassName="space-y-4">
            <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2.5">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-foreground">
                  {blueprint ? getBlueprintCardTitle(blueprint) : product.name}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {blueprint ? getBlueprintCardSubtitle(blueprint) : product.product_type}
                </div>
              </div>
              <StatusBadge value={blueprint?.status ?? product.validation_status} />
            </div>

            <div className="rounded-md border border-border bg-background px-3">
              <RailRow label="Partner" value={providerLabel(product.provider)} />
              <RailRow
                label="Connected store"
                value={<StoreLabel source={product} secondaryVariant="badge" />}
              />
              <RailRow
                label="Product type"
                value={blueprint ? formatBlueprintProductType(blueprint) : product.product_type}
              />
              <RailRow
                label="Variants"
                value={blueprint ? formatBlueprintVariantSummary(blueprint) : "—"}
              />
              <RailRow
                label="Artwork"
                value={
                  blueprint
                    ? formatBlueprintArtworkSummary(blueprint)
                    : "—"
                }
              />
              <RailRow
                label="Base cost"
                value={
                  blueprint?.base_cost_amount !== null && blueprint?.base_cost_amount !== undefined
                    ? formatCurrency(blueprint.base_cost_amount, blueprint.currency ?? "USD")
                    : formatCurrency(product.cost_amount, product.currency ?? "USD")
                }
              />
            </div>
            </SurfaceSection>
          </div>

          <SurfaceSection title="Pricing" bodyClassName="space-y-4">
            <div className="flex flex-col gap-2">
              <Label className="text-muted-foreground">Retail price</Label>
              <Input
                id="publish-retail-price"
                value={form.retailPrice}
                onChange={(event) => setForm({ ...form, retailPrice: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label className="text-muted-foreground">Currency</Label>
              <Input
                id="publish-currency"
                value={form.currency}
                onChange={(event) => setForm({ ...form, currency: event.target.value })}
              />
            </div>
            <div className="rounded-md border border-border bg-background px-3">
              <RailRow
                label="Retail preview"
                value={
                  hasRetailPrice
                    ? formatCurrency(parsedRetailPrice, form.currency || "USD")
                    : "—"
                }
              />
              <RailRow
                label="Projected margin"
                value={
                  projectedMargin !== null
                    ? formatCurrency(projectedMargin, form.currency || "USD")
                    : "—"
                }
              />
            </div>
          </SurfaceSection>

          <SurfaceSection title="Delete product" bodyClassName="space-y-4">
            <div className="rounded-md border border-red-500/20 bg-red-500/5 p-4">
              <div className="text-sm font-medium text-foreground">Remove this product from Velora</div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                This will remove this product from the Velora database and it can no longer be edited on Velora.
              </p>
              {(product.provider_product_id || product.external_listing_id) ? (
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Any provider or storefront listing already created outside Velora is not deleted by this action.
                </p>
              ) : null}
            </div>

            <DeleteProductDialog
              productId={product.id}
              productTitle={product.title}
              buttonLabel="Delete product"
              disabled={publishingActive}
              hasProviderRecord={Boolean(product.provider_product_id || product.external_listing_id)}
              onDeleted={() => {
                router.push("/products");
                router.refresh();
              }}
            />
          </SurfaceSection>

        </aside>
      </div>
    </div>
  );
}
