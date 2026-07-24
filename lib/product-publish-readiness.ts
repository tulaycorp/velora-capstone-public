export type PublishReadinessField =
  | "blueprint_id"
  | "provider_store_connection_id"
  | "design_asset_id"
  | "mockups"
  | "title"
  | "retail_price"
  | "currency"
  | "saved_changes";

export type PublishReadinessItem = {
  label: string;
  complete: boolean;
  field: PublishReadinessField;
};

type SavedEditorProduct = {
  title: string;
  description: string | null;
  design_description: string | null;
  tags: string[];
  retail_price: number | null;
  currency: string | null;
  sku: string | null;
};

type ProductEditorValues = {
  title: string;
  description: string;
  designDescription: string;
  tags: string[];
  retailPrice: string;
  currency: string;
  sku: string;
};

function nullableText(value: string) {
  return value.trim() || null;
}

function nullablePrice(value: string) {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function equalTags(left: string[], right: string[]) {
  return left.length === right.length && left.every((tag, index) => tag === right[index]);
}

export function isProductEditorDirty({
  product,
  values,
  pendingDesign,
  pendingMockups,
  mockupOrderDirty
}: {
  product: SavedEditorProduct | null;
  values: ProductEditorValues;
  pendingDesign: boolean;
  pendingMockups: boolean;
  mockupOrderDirty: boolean;
}) {
  if (!product) {
    return true;
  }

  return (
    product.title !== values.title.trim()
    || product.description !== nullableText(values.description)
    || product.design_description !== nullableText(values.designDescription)
    || !equalTags(product.tags, values.tags)
    || !Object.is(product.retail_price, nullablePrice(values.retailPrice))
    || product.currency !== nullableText(values.currency)
    || product.sku !== nullableText(values.sku)
    || pendingDesign
    || pendingMockups
    || mockupOrderDirty
  );
}

export function buildPublishReadiness({
  blueprintReady,
  designSaved,
  mockupCount,
  title,
  retailPrice,
  currency,
  editorDirty
}: {
  blueprintReady: boolean;
  designSaved: boolean;
  mockupCount: number;
  title: string;
  retailPrice: string;
  currency: string;
  editorDirty: boolean;
}): PublishReadinessItem[] {
  const parsedPrice = Number(retailPrice);
  return [
    { label: "Blueprint validated", complete: blueprintReady, field: "blueprint_id" },
    { label: "Design saved", complete: designSaved, field: "design_asset_id" },
    { label: "Product title added", complete: title.trim().length > 0, field: "title" },
    {
      label: "Price and currency added",
      complete: retailPrice.trim().length > 0 && Number.isFinite(parsedPrice) && parsedPrice > 0 && currency.trim().length > 0,
      field: retailPrice.trim().length > 0 && Number.isFinite(parsedPrice) && parsedPrice > 0 ? "currency" : "retail_price"
    },
    { label: "Product image uploaded", complete: mockupCount > 0, field: "mockups" },
    { label: "Latest changes saved", complete: !editorDirty, field: "saved_changes" }
  ];
}

const PUBLISH_FIELD_TARGETS: Record<PublishReadinessField, string> = {
  blueprint_id: "publish-blueprint",
  provider_store_connection_id: "publish-blueprint",
  design_asset_id: "publish-design",
  mockups: "publish-mockups",
  title: "publish-title",
  retail_price: "publish-retail-price",
  currency: "publish-currency",
  saved_changes: "publish-save"
};

export function focusPublishReadinessField(field: string) {
  if (typeof document === "undefined") {
    return false;
  }
  const targetId = PUBLISH_FIELD_TARGETS[field as PublishReadinessField];
  if (!targetId) {
    return false;
  }
  const target = document.getElementById(targetId);
  if (!target) {
    return false;
  }
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.focus({ preventScroll: true });
  return true;
}
