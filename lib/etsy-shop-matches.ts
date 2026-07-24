type PodProviderKey = "printify" | "gelato";

type EtsyShopSummaryLike = {
  matched_connection_id: string | null;
  matched_connection_label: string | null;
  matched_connection_ids: string[];
  matched_connection_labels: string[];
};

type ProviderStoreConnectionLike = {
  id: string;
  provider: PodProviderKey;
  label: string;
};

export type EtsyShopMatchedConnectionDisplay = {
  id: string;
  provider: string;
  storeLabel: string;
};

function formatProviderLabel(provider: PodProviderKey) {
  return provider === "printify" ? "Printify" : "Gelato";
}

function normalizeStoreLabel(label: string) {
  const normalized = label.trim();
  const [name = ""] = normalized.split(/\s*(?:->|→)\s*/, 1);
  return name.trim() || normalized || "Unknown store";
}

export function resolveEtsyShopMatchedConnections(
  shop: EtsyShopSummaryLike,
  storeConnections: ProviderStoreConnectionLike[]
): EtsyShopMatchedConnectionDisplay[] {
  const matchedIds =
    shop.matched_connection_ids.length > 0
      ? shop.matched_connection_ids
      : shop.matched_connection_id
        ? [shop.matched_connection_id]
        : [];

  const resolvedMatches = matchedIds
    .map((connectionId) => storeConnections.find((connection) => connection.id === connectionId))
    .filter((connection): connection is ProviderStoreConnectionLike => Boolean(connection))
    .map((connection) => ({
      id: connection.id,
      provider: formatProviderLabel(connection.provider),
      storeLabel: normalizeStoreLabel(connection.label)
    }));

  if (resolvedMatches.length > 0) {
    return resolvedMatches;
  }

  const fallbackLabels =
    shop.matched_connection_labels.length > 0
      ? shop.matched_connection_labels
      : shop.matched_connection_label
        ? [shop.matched_connection_label]
        : [];

  return fallbackLabels.map((label) => ({
    id: label,
    provider: "Connected store",
    storeLabel: normalizeStoreLabel(label)
  }));
}
