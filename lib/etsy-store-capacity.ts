import type { ProviderCredentialEntry, ProviderStoreConnection } from "./backend-api";

export const ETSY_STORE_LIMIT = 5;

type EtsyStoreCapacityInput = {
  storeConnections: ProviderStoreConnection[];
  gelatoCredentials: ProviderCredentialEntry[];
};

function buildStoreIdentity(provider: string, credentialKey: string, providerStoreId: string) {
  return `${provider}:${credentialKey}:${providerStoreId}`;
}

export function buildEtsyStoreCapacitySummary({
  storeConnections,
  gelatoCredentials
}: EtsyStoreCapacityInput) {
  const actualEtsyStoreKeys = new Set(
    storeConnections.flatMap((connection) => {
      if (connection.storefront_type !== "etsy") {
        return [];
      }

      return [
        buildStoreIdentity(
          connection.provider,
          connection.credential_key,
          connection.provider_store_id
        )
      ];
    })
  );
  const projectedEtsyStoreKeys = new Set(actualEtsyStoreKeys);

  for (const credential of gelatoCredentials) {
    for (const seed of credential.manual_store_seeds) {
      if (seed.storefront_type !== "etsy") {
        continue;
      }

      const providerStoreId = seed.provider_store_id.trim();
      if (!providerStoreId) {
        continue;
      }

      projectedEtsyStoreKeys.add(
        buildStoreIdentity("gelato", credential.credential_key, providerStoreId)
      );
    }
  }

  const current = actualEtsyStoreKeys.size;
  const projected = projectedEtsyStoreKeys.size;

  return {
    limit: ETSY_STORE_LIMIT,
    current,
    projected,
    remaining: Math.max(0, ETSY_STORE_LIMIT - projected),
    isAtLimit: projected >= ETSY_STORE_LIMIT
  };
}
