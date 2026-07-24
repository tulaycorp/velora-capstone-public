type EtsyDiscoverySummaryInput = {
  etsyStoreConnectionCount: number;
  lastSyncedAt: string | null;
  formatDateTime: (value: string | null) => string;
};

export function buildEtsyDiscoverySummaryChips({
  etsyStoreConnectionCount,
  lastSyncedAt,
  formatDateTime
}: EtsyDiscoverySummaryInput) {
  return [
    {
      label: "Connected stores",
      value: `${etsyStoreConnectionCount}`
    },
    {
      label: "Last updated",
      value: formatDateTime(lastSyncedAt)
    }
  ];
}
