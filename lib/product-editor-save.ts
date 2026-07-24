export type ProductEditorListingFields = {
  title: string;
  description: string;
  designDescription: string;
  tags: string[];
  retailPrice: string;
  currency: string;
  sku: string;
};

export type ProductEditorListingInput = {
  title: string;
  description: string | null;
  design_description: string | null;
  tags: string[];
  retail_price: number | null;
  currency: string;
  sku: string | null;
};

export function buildProductEditorListingInput(
  fields: ProductEditorListingFields,
  fallbackTitle: string
): ProductEditorListingInput {
  return {
    title: fields.title.trim() || fallbackTitle,
    description: fields.description.trim() || null,
    design_description: fields.designDescription.trim() || null,
    tags: fields.tags,
    retail_price: fields.retailPrice ? Number(fields.retailPrice) : null,
    currency: fields.currency.trim() || "USD",
    sku: fields.sku.trim() || null
  };
}

export function withProductPublishingStatus<
  T extends { publishing_status: string }
>(product: T, publishingStatus: string): T {
  return { ...product, publishing_status: publishingStatus };
}
