import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPublishReadiness,
  isProductEditorDirty
} from "./product-publish-readiness.ts";

const product = {
  title: "Saved title",
  description: "Saved description",
  design_description: "Private design context",
  tags: ["wall art"],
  retail_price: 39.99,
  currency: "USD",
  sku: "WALL-1"
};

const values = {
  title: "Saved title",
  description: "Saved description",
  designDescription: "Private design context",
  tags: ["wall art"],
  retailPrice: "39.99",
  currency: "USD",
  sku: "WALL-1"
};

test("editor dirtiness includes listing, pricing, design, and pending media state", () => {
  assert.equal(isProductEditorDirty({ product, values, pendingDesign: false, pendingMockups: false, mockupOrderDirty: false }), false);
  assert.equal(isProductEditorDirty({ product, values: { ...values, retailPrice: "40" }, pendingDesign: false, pendingMockups: false, mockupOrderDirty: false }), true);
  assert.equal(isProductEditorDirty({ product, values, pendingDesign: false, pendingMockups: true, mockupOrderDirty: false }), true);
  assert.equal(isProductEditorDirty({ product, values, pendingDesign: false, pendingMockups: false, mockupOrderDirty: true }), true);
});

test("publish readiness blocks unsaved, invalid, or incomplete product state", () => {
  const readiness = buildPublishReadiness({
    blueprintReady: true,
    designSaved: true,
    mockupCount: 0,
    title: "Saved title",
    retailPrice: "0",
    currency: "USD",
    editorDirty: true
  });
  const incompleteFields = readiness.filter((item) => !item.complete).map((item) => item.field);
  assert.deepEqual(incompleteFields, ["retail_price", "mockups", "saved_changes"]);
});

test("publish readiness passes only the persisted complete editor state", () => {
  const readiness = buildPublishReadiness({
    blueprintReady: true,
    designSaved: true,
    mockupCount: 1,
    title: "Saved title",
    retailPrice: "39.99",
    currency: "USD",
    editorDirty: false
  });
  assert.equal(readiness.every((item) => item.complete), true);
});
