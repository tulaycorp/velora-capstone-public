import type { AIGenerationOutput, Product } from "@/lib/backend-api";

export const AI_GENERATION_FIELDS = [
  "title",
  "description",
  "tags",
  "seo_title",
  "seo_description",
  "seo_keywords"
] as const;

export type AIGenerationField = (typeof AI_GENERATION_FIELDS)[number];
export type AIGenerationRequestScope = AIGenerationField | "all";

type ProductGenerationBaseline = Pick<
  Product,
  | "title"
  | "description"
  | "tags"
  | "seo_title"
  | "seo_description"
  | "seo_keywords"
>;

export function buildGenerationReviewBaseline(
  product: ProductGenerationBaseline
): AIGenerationOutput {
  return {
    title: product.title,
    description: product.description ?? "",
    tags: product.tags,
    seo_title: product.seo_title ?? "",
    seo_description: product.seo_description ?? "",
    seo_keywords: product.seo_keywords,
    attributes: {},
    warnings: []
  };
}

export function mergeTargetedGeneration({
  current,
  product,
  output,
  field
}: {
  current: AIGenerationOutput | null;
  product: ProductGenerationBaseline;
  output: AIGenerationOutput;
  field: AIGenerationField;
}): AIGenerationOutput {
  return {
    ...(current ?? buildGenerationReviewBaseline(product)),
    [field]: output[field],
    warnings: output.warnings
  };
}

export function buildSelectedGenerationFields(field?: AIGenerationField) {
  return Object.fromEntries(
    AI_GENERATION_FIELDS.map((candidate) => [candidate, field ? candidate === field : true])
  ) as Record<AIGenerationField, boolean>;
}

export function resolveGenerationRequestId(
  currentRequestId: string | undefined,
  createRequestId: () => string
) {
  return currentRequestId ?? createRequestId();
}

export function shouldRetainGenerationRequestIdAfterError(
  status: number | null
) {
  return status === null || status === 429 || status >= 500;
}
