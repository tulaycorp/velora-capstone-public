export type OrderedMockupItem =
  | { source: "attached"; id: string }
  | { source: "queued"; id: string };

export function serializeOrderedMockupItem(item: OrderedMockupItem) {
  return `${item.source}:${item.id}`;
}

function buildCanonicalOrder(attachedIds: string[], queuedIds: string[]) {
  return [
    ...attachedIds.map((id) => ({ source: "attached", id }) as const),
    ...queuedIds.map((id) => ({ source: "queued", id }) as const)
  ];
}

export function syncOrderedMockups({
  attachedIds,
  queuedIds,
  currentOrder,
  preserveCurrentOrder
}: {
  attachedIds: string[];
  queuedIds: string[];
  currentOrder: OrderedMockupItem[];
  preserveCurrentOrder: boolean;
}) {
  const canonicalOrder = buildCanonicalOrder(attachedIds, queuedIds);

  if (!preserveCurrentOrder) {
    return canonicalOrder;
  }

  const attachedIdSet = new Set(attachedIds);
  const queuedIdSet = new Set(queuedIds);
  const nextOrder = currentOrder.filter((item) =>
    item.source === "attached" ? attachedIdSet.has(item.id) : queuedIdSet.has(item.id)
  );
  const seenKeys = new Set(nextOrder.map(serializeOrderedMockupItem));

  for (const item of canonicalOrder) {
    const key = serializeOrderedMockupItem(item);
    if (seenKeys.has(key)) {
      continue;
    }

    nextOrder.push(item);
    seenKeys.add(key);
  }

  return nextOrder;
}

export function buildOrderedMockupIds(
  orderedItems: OrderedMockupItem[],
  uploadedIdsByQueuedId: Map<string, string>
) {
  const nextIds: string[] = [];

  for (const item of orderedItems) {
    if (item.source === "attached") {
      nextIds.push(item.id);
      continue;
    }

    const uploadedId = uploadedIdsByQueuedId.get(item.id);
    if (uploadedId) {
      nextIds.push(uploadedId);
    }
  }

  return nextIds;
}
