"use client";

import {
  CircleAlert,
  Info,
  LoaderCircle,
  ShieldCheck,
  Sparkles
} from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState
} from "react";
import { Button } from "@/components/ui/button";
import { AutoResizeTextarea } from "@/components/ui/auto-resize-textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { AIFieldRegenerateButton } from "@/components/workspace/ai-field-regenerate-button";
import {
  buildSelectedGenerationFields,
  mergeTargetedGeneration,
  resolveGenerationRequestId,
  shouldRetainGenerationRequestIdAfterError,
  type AIGenerationField,
  type AIGenerationRequestScope
} from "@/lib/ai-generation-review";
import {
  BackendApiError,
  applyProductListingGeneration,
  fetchAICapabilities,
  generateProductListing,
  type AIGenerationOutput,
  type Product
} from "@/lib/backend-api";

type Props = {
  product: Product | null;
  onApplied: (product: Product) => void;
  onRegenerationStateChange?: (field: AIGenerationField | null) => void;
};

export type AIListingAssistantHandle = {
  regenerateTitle: () => Promise<string | null>;
  regenerateDescription: () => Promise<string | null>;
  regenerateTags: () => Promise<string[] | null>;
};

type GenerationOperation = AIGenerationField | "all" | "applying" | null;

function requestId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `ai-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export const AIListingAssistant = forwardRef<AIListingAssistantHandle, Props>(
  function AIListingAssistant(
    { product, onApplied, onRegenerationStateChange },
    ref
  ) {
    const [enabled, setEnabled] = useState(false);
    const [capabilitiesLoaded, setCapabilitiesLoaded] = useState(false);
    const [generation, setGeneration] = useState<AIGenerationOutput | null>(null);
    const [generationId, setGenerationId] = useState<string | null>(null);
    const [operation, setOperation] = useState<GenerationOperation>(null);
    const [error, setError] = useState<string | null>(null);
    const [selected, setSelected] = useState(buildSelectedGenerationFields);
    const requestIds = useRef<
      Partial<Record<AIGenerationRequestScope, string>>
    >({});
    const localWaitToken = useRef(0);

    useEffect(() => {
      let cancelled = false;

      void fetchAICapabilities()
        .then((value) => {
          if (!cancelled) {
            setEnabled(value.enabled);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setEnabled(false);
          }
        })
        .finally(() => {
          if (!cancelled) {
            setCapabilitiesLoaded(true);
          }
        });

      return () => {
        cancelled = true;
      };
    }, []);

    useEffect(() => {
      const regeneratingField =
        operation && operation !== "all" && operation !== "applying"
          ? operation
          : null;
      onRegenerationStateChange?.(regeneratingField);

      return () => {
        onRegenerationStateChange?.(null);
      };
    }, [onRegenerationStateChange, operation]);

    const reason = !product
      ? "Save the draft first."
      : !product.design_description?.trim()
        ? "Add a design description before generating."
        : !capabilitiesLoaded
          ? "Checking generation availability."
          : !enabled
            ? "Listing generation is not configured in this environment."
            : null;

    const tagsText = useMemo(
      () => generation?.tags.join(", ") ?? "",
      [generation]
    );
    const busy = operation !== null;

    const generate = useCallback(
      async (field?: AIGenerationField) => {
        if (!product || reason) {
          setError(reason ?? "Listing generation is unavailable.");
          return;
        }

        const hadGeneration = generation !== null;
        const requestScope: AIGenerationRequestScope = field ?? "all";
        const generationRequestId = resolveGenerationRequestId(
          requestIds.current[requestScope],
          requestId
        );
        requestIds.current[requestScope] = generationRequestId;
        const waitToken = ++localWaitToken.current;
        setOperation(field ?? "all");
        setError(null);

        try {
          const response = await generateProductListing(product.id, {
            client_request_id: generationRequestId,
            expected_product_revision: product.revision,
            regenerate_fields: field ? [field] : []
          });

          if (waitToken !== localWaitToken.current) {
            return;
          }

          if (!response.output) {
            if (response.status !== "pending") {
              delete requestIds.current[requestScope];
            }
            throw new Error(response.error_message || "Vel did not return a listing.");
          }

          setGeneration((current) =>
            field
              ? mergeTargetedGeneration({
                  current,
                  product,
                  output: response.output!,
                  field
                })
              : response.output
          );
          setGenerationId(response.id);
          delete requestIds.current[requestScope];
          if (!field) {
            setSelected(buildSelectedGenerationFields());
          } else if (!hadGeneration) {
            setSelected(buildSelectedGenerationFields(field));
          }
        } catch (cause) {
          if (waitToken !== localWaitToken.current) {
            return;
          }
          const status = cause instanceof BackendApiError ? cause.status : null;
          if (!shouldRetainGenerationRequestIdAfterError(status)) {
            delete requestIds.current[requestScope];
          }
          setError(
            cause instanceof Error ? cause.message : "Unable to generate a listing."
          );
        } finally {
          if (waitToken === localWaitToken.current) {
            setOperation(null);
          }
        }
      },
      [generation, product, reason]
    );

    const generateDirect = useCallback(
      async (
        field: "title" | "description" | "tags"
      ): Promise<string | string[] | null> => {
        if (!product || reason) {
          setError(reason ?? "Listing generation is unavailable.");
          return null;
        }

        const requestScope: AIGenerationRequestScope = field;
        const generationRequestId = resolveGenerationRequestId(
          requestIds.current[requestScope],
          requestId
        );
        requestIds.current[requestScope] = generationRequestId;
        const waitToken = ++localWaitToken.current;
        setOperation(field);
        setError(null);

        try {
          const response = await generateProductListing(product.id, {
            client_request_id: generationRequestId,
            expected_product_revision: product.revision,
            regenerate_fields: [field]
          });

          if (waitToken !== localWaitToken.current) {
            return null;
          }

          if (!response.output) {
            if (response.status !== "pending") {
              delete requestIds.current[requestScope];
            }
            throw new Error(response.error_message || `Vel did not return ${field}.`);
          }

          delete requestIds.current[requestScope];
          return response.output[field];
        } catch (cause) {
          if (waitToken !== localWaitToken.current) {
            return null;
          }
          const status = cause instanceof BackendApiError ? cause.status : null;
          if (!shouldRetainGenerationRequestIdAfterError(status)) {
            delete requestIds.current[requestScope];
          }
          setError(
            cause instanceof Error
              ? cause.message
              : `Unable to regenerate ${field}.`
          );
          return null;
        } finally {
          if (waitToken === localWaitToken.current) {
            setOperation(null);
          }
        }
      },
      [product, reason]
    );

    async function apply() {
      if (!product || !generation || !generationId) {
        return;
      }

      setOperation("applying");
      setError(null);

      try {
        const payload = {
          expected_product_revision: product.revision,
          ...(selected.title ? { title: generation.title } : {}),
          ...(selected.description ? { description: generation.description } : {}),
          ...(selected.tags
            ? {
                tags: tagsText
                  .split(",")
                  .map((tag) => tag.trim())
                  .filter(Boolean)
              }
            : {}),
          ...(selected.seo_title ? { seo_title: generation.seo_title } : {}),
          ...(selected.seo_description
            ? { seo_description: generation.seo_description }
            : {}),
          ...(selected.seo_keywords
            ? { seo_keywords: generation.seo_keywords }
            : {})
        };

        if (Object.keys(payload).length === 1) {
          setError("Select at least one field to apply.");
          return;
        }

        const response = await applyProductListingGeneration(
          product.id,
          generationId,
          payload
        );
        onApplied(response.product);
        setGeneration(null);
        setGenerationId(null);
      } catch (cause) {
        setError(
          cause instanceof Error ? cause.message : "Unable to apply this listing."
        );
      } finally {
        setOperation(null);
      }
    }

    useImperativeHandle(
      ref,
      () => ({
        regenerateTitle: async () => {
          const value = await generateDirect("title");
          return typeof value === "string" ? value : null;
        },
        regenerateDescription: async () => {
          const value = await generateDirect("description");
          return typeof value === "string" ? value : null;
        },
        regenerateTags: async () => {
          const value = await generateDirect("tags");
          return Array.isArray(value) ? value : null;
        }
      }),
      [generateDirect]
    );

    function updateSelected(field: AIGenerationField, checked: boolean) {
      setSelected((current) => ({ ...current, [field]: checked }));
    }

    function isFieldLoading(field: AIGenerationField) {
      return operation === field || operation === "all";
    }

    function stopWaitingLocally() {
      if (!operation || operation === "applying") {
        return;
      }
      localWaitToken.current += 1;
      setOperation(null);
      setError(
        "Stopped waiting locally. The server request may still finish; retrying will reuse the same request."
      );
    }

    return (
      <section
        aria-labelledby="generate-with-vel-title"
        className="min-w-0 max-w-full overflow-x-clip border-b border-primary/20 bg-primary/[0.035] [overflow-wrap:anywhere]"
      >
        <div className="flex flex-col gap-5 px-5 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6">
          <div className="flex min-w-0 items-start gap-3.5">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary/25 bg-primary/10 text-primary">
              <Sparkles className="h-4.5 w-4.5" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2
                id="generate-with-vel-title"
                className="text-[15px] font-semibold text-foreground"
              >
                Generate with Vel
              </h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                Ask Vel to turn your product and artwork into search-optimized
                titles, descriptions, tags, and SEO details.
              </p>
              <div className="mt-2 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                <ShieldCheck className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                <span className="min-w-0">
                  Review required. Vel never saves or publishes automatically.
                </span>
              </div>
            </div>
          </div>

          <div className="flex w-full shrink-0 flex-col gap-2 sm:w-auto sm:flex-row">
            {operation && operation !== "applying" ? (
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                onClick={stopWaitingLocally}
              >
                Stop waiting
              </Button>
            ) : null}
            <Button
              type="button"
              className="w-full shrink-0 sm:w-auto"
              onClick={() => void generate()}
              disabled={Boolean(reason) || busy}
            >
              {operation === "all" ? (
                <LoaderCircle className="animate-spin" data-icon="inline-start" />
              ) : (
                <Sparkles data-icon="inline-start" />
              )}
              {operation === "all"
                ? "Generating..."
                : generation
                  ? "Generate again"
                  : "Generate listing"}
            </Button>
          </div>
        </div>

        {reason ? (
          <div className="flex min-w-0 items-start gap-2 border-t border-primary/15 bg-background/25 px-5 py-3 text-xs leading-5 text-muted-foreground sm:px-6">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0">{reason}</span>
          </div>
        ) : null}

        {error ? (
          <div
            role="alert"
            className="flex min-w-0 items-start gap-2 border-t border-destructive/25 bg-destructive/10 px-5 py-3 text-sm leading-5 text-destructive sm:px-6"
          >
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="min-w-0">{error}</span>
          </div>
        ) : null}

        {generation ? (
          <div className="min-w-0 border-t border-primary/20 bg-card/70">
            <div className="flex flex-col gap-1 border-b border-border/70 px-5 py-4 sm:px-6">
              <h3 className="text-sm font-semibold text-foreground">
                Review suggestions
              </h3>
              <p className="text-xs leading-5 text-muted-foreground">
                Edit the draft and select only the fields you want to copy into the
                listing.
              </p>
            </div>

            <div className="min-w-0 space-y-6 px-5 py-5 sm:px-6">
              <div className="min-w-0">
                <Label className="flex items-center gap-2.5">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={selected.title}
                    onChange={(event) =>
                      updateSelected("title", event.target.checked)
                    }
                  />
                  Suggested title
                </Label>
                <div className="relative mt-2">
                  <AutoResizeTextarea
                    className="pr-16 leading-5 disabled:bg-muted/35"
                    maxLength={140}
                    value={generation.title}
                    disabled={isFieldLoading("title")}
                    onChange={(event) =>
                      setGeneration({ ...generation, title: event.target.value })
                    }
                  />
                  <AIFieldRegenerateButton
                    label="title"
                    loading={operation === "title"}
                    disabled={busy}
                    fillHeight
                    onClick={() => void generate("title")}
                  />
                </div>
              </div>

              <div className="min-w-0">
                <Label className="flex items-center gap-2.5">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={selected.description}
                    onChange={(event) =>
                      updateSelected("description", event.target.checked)
                    }
                  />
                  Suggested description
                </Label>
                <div className="relative mt-2">
                  <Textarea
                    className="min-h-44 pr-12 leading-6 disabled:bg-muted/35"
                    value={generation.description}
                    disabled={isFieldLoading("description")}
                    onChange={(event) =>
                      setGeneration({
                        ...generation,
                        description: event.target.value
                      })
                    }
                  />
                  <AIFieldRegenerateButton
                    label="description"
                    loading={operation === "description"}
                    disabled={busy}
                    onClick={() => void generate("description")}
                  />
                </div>
              </div>

              <div className="min-w-0">
                <Label className="flex items-center gap-2.5">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={selected.tags}
                    onChange={(event) =>
                      updateSelected("tags", event.target.checked)
                    }
                  />
                  Suggested tags
                </Label>
                <div className="relative mt-2">
                  <Input
                    className="pr-16 disabled:bg-muted/35"
                    value={tagsText}
                    disabled={isFieldLoading("tags")}
                    onChange={(event) =>
                      setGeneration({
                        ...generation,
                        tags: event.target.value
                          .split(",")
                          .map((tag) => tag.trim())
                          .filter(Boolean)
                      })
                    }
                  />
                  <AIFieldRegenerateButton
                    label="tags"
                    loading={operation === "tags"}
                    disabled={busy}
                    fillHeight
                    onClick={() => void generate("tags")}
                  />
                </div>
              </div>

              <div className="grid min-w-0 gap-5 lg:grid-cols-2">
                <div className="min-w-0">
                  <Label className="flex items-center gap-2.5">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={selected.seo_title}
                      onChange={(event) =>
                        updateSelected("seo_title", event.target.checked)
                      }
                    />
                    SEO title
                  </Label>
                  <div className="relative mt-2">
                    <Input
                      className="pr-12 disabled:bg-muted/35"
                      value={generation.seo_title}
                      disabled={isFieldLoading("seo_title")}
                      onChange={(event) =>
                        setGeneration({
                          ...generation,
                          seo_title: event.target.value
                        })
                      }
                    />
                    <AIFieldRegenerateButton
                      label="SEO title"
                      loading={operation === "seo_title"}
                      disabled={busy}
                      onClick={() => void generate("seo_title")}
                      className="top-1"
                    />
                  </div>
                </div>

                <div className="min-w-0">
                  <Label className="flex items-center gap-2.5">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={selected.seo_keywords}
                      onChange={(event) =>
                        updateSelected("seo_keywords", event.target.checked)
                      }
                    />
                    SEO keywords
                  </Label>
                  <div className="relative mt-2">
                    <Input
                      className="pr-12 disabled:bg-muted/35"
                      value={generation.seo_keywords.join(", ")}
                      disabled={isFieldLoading("seo_keywords")}
                      onChange={(event) =>
                        setGeneration({
                          ...generation,
                          seo_keywords: event.target.value
                            .split(",")
                            .map((keyword) => keyword.trim())
                            .filter(Boolean)
                        })
                      }
                    />
                    <AIFieldRegenerateButton
                      label="SEO keywords"
                      loading={operation === "seo_keywords"}
                      disabled={busy}
                      onClick={() => void generate("seo_keywords")}
                      className="top-1"
                    />
                  </div>
                </div>
              </div>

              <div className="min-w-0">
                <Label className="flex items-center gap-2.5">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={selected.seo_description}
                    onChange={(event) =>
                      updateSelected("seo_description", event.target.checked)
                    }
                  />
                  SEO description
                </Label>
                <div className="relative mt-2">
                  <Textarea
                    className="min-h-24 pr-12 leading-6 disabled:bg-muted/35"
                    value={generation.seo_description}
                    disabled={isFieldLoading("seo_description")}
                    onChange={(event) =>
                      setGeneration({
                        ...generation,
                        seo_description: event.target.value
                      })
                    }
                  />
                  <AIFieldRegenerateButton
                    label="SEO description"
                    loading={operation === "seo_description"}
                    disabled={busy}
                    onClick={() => void generate("seo_description")}
                  />
                </div>
              </div>

              {generation.warnings.length ? (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-3 text-xs leading-5 text-amber-200">
                  <CircleAlert
                    className="mt-0.5 h-3.5 w-3.5 shrink-0"
                    aria-hidden="true"
                  />
                  <span className="min-w-0">
                    {generation.warnings.join(" ")}
                  </span>
                </div>
              ) : null}
            </div>

            <div className="flex flex-col gap-3 border-t border-border/70 bg-background/25 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
              <p className="text-xs leading-5 text-muted-foreground">
                Your listing changes only after you apply the selected fields.
              </p>
              <Button
                type="button"
                className="w-full shrink-0 sm:w-auto"
                onClick={() => void apply()}
                disabled={busy}
              >
                {operation === "applying" ? (
                  <LoaderCircle className="animate-spin" data-icon="inline-start" />
                ) : null}
                {operation === "applying"
                  ? "Applying suggestions..."
                  : "Apply selected fields"}
              </Button>
            </div>
          </div>
        ) : null}
      </section>
    );
  }
);
