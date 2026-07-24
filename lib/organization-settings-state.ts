import type {
  EtsyConnectionStatus,
  ManualStoreSeed,
  OrganizationJoinRequestSummary,
  PodProviderKey,
  ProviderCredentialStatus,
  ProviderStoreConnection
} from "./backend-api";

function storefrontLabel(type: ManualStoreSeed["storefront_type"]) {
  if (type === "etsy") return "Etsy";
  if (type === "shopify") return "Shopify";
  return "Unknown";
}

export type PrintifyCredentialDraft = {
  display_name: string;
  api_token: string;
};

export type GelatoCredentialDraft = {
  display_name: string;
  api_key: string;
};

export type CredentialDrafts = {
  printify: PrintifyCredentialDraft;
  gelato: GelatoCredentialDraft;
};

export const providerKeys: PodProviderKey[] = ["printify", "gelato"];

export function createPrintifyDraft(): PrintifyCredentialDraft {
  return { display_name: "", api_token: "" };
}

export function createManualStoreSeed(
  overrides: Partial<ManualStoreSeed> = {}
): ManualStoreSeed {
  const storefrontType = overrides.storefront_type ?? "etsy";
  return {
    provider_store_id: overrides.provider_store_id ?? "",
    storefront_type: storefrontType,
    storefront_display_name:
      overrides.storefront_display_name ?? storefrontLabel(storefrontType),
    label: overrides.label ?? null,
    etsy_shop_id: overrides.etsy_shop_id ?? null
  };
}

export function createGelatoDraft(): GelatoCredentialDraft {
  return { display_name: "", api_key: "" };
}

export function normalizeManualStoreSeedsForSave(seeds: ManualStoreSeed[]) {
  return seeds.flatMap((seed) => {
    const providerStoreId = seed.provider_store_id.trim();
    if (!providerStoreId) return [];

    const storefrontType = seed.storefront_type;
    const label = seed.label?.trim() ?? "";
    return [{
      provider_store_id: providerStoreId,
      storefront_type: storefrontType,
      storefront_display_name: storefrontLabel(storefrontType),
      label: label || null,
      etsy_shop_id: seed.etsy_shop_id?.trim() || null
    }];
  });
}

function createEmptyCredentialStatus(provider: PodProviderKey): ProviderCredentialStatus {
  return {
    provider,
    is_configured: false,
    required_keys: [provider === "printify" ? "api_token" : "api_key"],
    credential_count: 0,
    credentials: []
  };
}

export const emptyCredentialStatuses = {
  printify: createEmptyCredentialStatus("printify"),
  gelato: createEmptyCredentialStatus("gelato")
} satisfies Record<PodProviderKey, ProviderCredentialStatus>;

export function createEmptyEtsyConnectionStatus(): EtsyConnectionStatus {
  return {
    is_connected: false,
    seller_user_id: null,
    last_synced_at: null,
    scopes: [],
    connected_account_count: 0,
    connected_accounts: [],
    connected_shops: [],
    matched_connection_count: 0,
    unmapped_connection_count: 0
  };
}

export function formatStorefrontCount(count: number) {
  return `${count} store${count === 1 ? "" : "s"}`;
}

export function formatCredentialCount(count: number) {
  return `${count} key${count === 1 ? "" : "s"}`;
}

export function formatRequesterPrimaryLine(joinRequest: OrganizationJoinRequestSummary) {
  return joinRequest.requested_by_email ?? joinRequest.requested_by_name;
}

export function formatRequesterSecondaryLine(joinRequest: OrganizationJoinRequestSummary) {
  if (!joinRequest.requested_by_email || joinRequest.requested_by_email === joinRequest.requested_by_name) {
    return null;
  }
  return joinRequest.requested_by_name;
}

export function buildCredentialActionKey(provider: PodProviderKey, credentialKey: string) {
  return `${provider}:${credentialKey}`;
}

export function latestSyncedAt(connections: ProviderStoreConnection[]) {
  let latestValue: string | null = null;
  let latestTimestamp = Number.NEGATIVE_INFINITY;

  for (const connection of connections) {
    if (!connection.last_sync_at) continue;
    const timestamp = new Date(connection.last_sync_at).getTime();
    if (Number.isNaN(timestamp) || timestamp <= latestTimestamp) continue;
    latestTimestamp = timestamp;
    latestValue = connection.last_sync_at;
  }
  return latestValue;
}

export function groupStoreConnectionsByType(connections: ProviderStoreConnection[]) {
  const groups = new Map<ManualStoreSeed["storefront_type"], ProviderStoreConnection[]>();
  for (const connection of connections) {
    const existing = groups.get(connection.storefront_type);
    if (existing) existing.push(connection);
    else groups.set(connection.storefront_type, [connection]);
  }

  const orderedTypes: ManualStoreSeed["storefront_type"][] = ["etsy", "shopify", "unknown"];
  const orderedGroups = orderedTypes
    .filter((type) => groups.has(type))
    .map((type) => ({
      key: type,
      title: storefrontLabel(type),
      connections: groups.get(type) ?? []
    }));

  for (const [type, groupedConnections] of groups.entries()) {
    if (orderedTypes.includes(type)) continue;
    orderedGroups.push({
      key: type,
      title: storefrontLabel(type),
      connections: groupedConnections
    });
  }
  return orderedGroups;
}
