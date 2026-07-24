import assert from "node:assert/strict";
import test from "node:test";

import {
  AI_GENERATION_FIELDS,
  buildGenerationReviewBaseline,
  buildSelectedGenerationFields,
  mergeTargetedGeneration,
  resolveGenerationRequestId,
  shouldRetainGenerationRequestIdAfterError
} from "./ai-generation-review.ts";

const product = {
  title: "Saved title",
  description: "Saved description",
  tags: ["saved-tag"],
  seo_title: "Saved SEO title",
  seo_description: "Saved SEO description",
  seo_keywords: ["saved-keyword"]
};

const output = {
  title: "Generated title",
  description: "Generated description",
  tags: ["generated-tag"],
  seo_title: "Generated SEO title",
  seo_description: "Generated SEO description",
  seo_keywords: ["generated-keyword"],
  attributes: { source: "generated" },
  warnings: ["Review generated facts."]
};

test("a first targeted generation preserves every other saved product field", () => {
  for (const field of AI_GENERATION_FIELDS) {
    const result = mergeTargetedGeneration({ current: null, product, output, field });
    const baseline = buildGenerationReviewBaseline(product);

    assert.deepEqual(result[field], output[field]);
    for (const otherField of AI_GENERATION_FIELDS) {
      if (otherField !== field) {
        assert.deepEqual(result[otherField], baseline[otherField]);
      }
    }
  }
});

test("a targeted regeneration changes only its requested review field", () => {
  const current = {
    ...buildGenerationReviewBaseline(product),
    title: "Edited review title",
    description: "Edited review description"
  };
  const result = mergeTargetedGeneration({
    current,
    product,
    output,
    field: "seo_title"
  });

  assert.equal(result.seo_title, output.seo_title);
  assert.equal(result.title, current.title);
  assert.equal(result.description, current.description);
  assert.deepEqual(result.tags, current.tags);
});

test("a first targeted generation selects only the requested field", () => {
  assert.deepEqual(buildSelectedGenerationFields("description"), {
    title: false,
    description: true,
    tags: false,
    seo_title: false,
    seo_description: false,
    seo_keywords: false
  });
  assert.ok(Object.values(buildSelectedGenerationFields()).every(Boolean));
});

test("request ids are reused for retryable failures and replaced after invalid context", () => {
  let created = 0;
  const createRequestId = () => `request-${++created}`;

  assert.equal(resolveGenerationRequestId(undefined, createRequestId), "request-1");
  assert.equal(
    resolveGenerationRequestId("request-1", createRequestId),
    "request-1"
  );
  assert.equal(created, 1);
  assert.equal(shouldRetainGenerationRequestIdAfterError(null), true);
  assert.equal(shouldRetainGenerationRequestIdAfterError(429), true);
  assert.equal(shouldRetainGenerationRequestIdAfterError(503), true);
  assert.equal(shouldRetainGenerationRequestIdAfterError(409), false);
  assert.equal(shouldRetainGenerationRequestIdAfterError(422), false);
});
