import assert from "node:assert/strict";
import test from "node:test";

import {
  buildOrderedMockupIds,
  serializeOrderedMockupItem,
  syncOrderedMockups,
  type OrderedMockupItem
} from "./product-detail-mockup-state.ts";

test("serializeOrderedMockupItem keeps attached and queued ids distinct", () => {
  assert.equal(
    serializeOrderedMockupItem({ source: "attached", id: "image-1" }),
    "attached:image-1"
  );
  assert.equal(
    serializeOrderedMockupItem({ source: "queued", id: "image-1" }),
    "queued:image-1"
  );
});

test("syncOrderedMockups uses canonical attached-then-queued order when there is no draft ordering to preserve", () => {
  const nextOrder = syncOrderedMockups({
    attachedIds: ["attached-a", "attached-b"],
    queuedIds: ["queued-a"],
    currentOrder: [],
    preserveCurrentOrder: false
  });

  assert.deepEqual(nextOrder, [
    { source: "attached", id: "attached-a" },
    { source: "attached", id: "attached-b" },
    { source: "queued", id: "queued-a" }
  ]);
});

test("syncOrderedMockups preserves mixed ordering while dropping missing items and appending new ones", () => {
  const currentOrder: OrderedMockupItem[] = [
    { source: "queued", id: "queued-a" },
    { source: "attached", id: "attached-b" },
    { source: "attached", id: "attached-a" },
    { source: "queued", id: "queued-missing" }
  ];

  const nextOrder = syncOrderedMockups({
    attachedIds: ["attached-a", "attached-b", "attached-c"],
    queuedIds: ["queued-a", "queued-b"],
    currentOrder,
    preserveCurrentOrder: true
  });

  assert.deepEqual(nextOrder, [
    { source: "queued", id: "queued-a" },
    { source: "attached", id: "attached-b" },
    { source: "attached", id: "attached-a" },
    { source: "attached", id: "attached-c" },
    { source: "queued", id: "queued-b" }
  ]);
});

test("buildOrderedMockupIds replaces queued ids with uploaded ids while preserving the visible order", () => {
  const orderedIds = buildOrderedMockupIds(
    [
      { source: "attached", id: "attached-a" },
      { source: "queued", id: "queued-a" },
      { source: "attached", id: "attached-b" },
      { source: "queued", id: "queued-b" }
    ],
    new Map([
      ["queued-a", "uploaded-a"],
      ["queued-b", "uploaded-b"]
    ])
  );

  assert.deepEqual(orderedIds, [
    "attached-a",
    "uploaded-a",
    "attached-b",
    "uploaded-b"
  ]);
});
