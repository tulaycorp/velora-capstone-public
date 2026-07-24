import type {
  AnalyticsOverview,
  EtsySnapshot,
  RecentActivity,
} from "@/lib/backend-api";

export function formatAnalyticsCount(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatPublishSuccessRate(overview: AnalyticsOverview) {
  if (overview.publish_success_rate_last_30_days === null) {
    return "—";
  }
  return `${overview.publish_success_rate_last_30_days.toFixed(1)}%`;
}

export function formatRevenueValue(activity: RecentActivity) {
  const value = activity.revenue_last_30_days.toFixed(2);
  if (activity.revenue_is_mixed_currency) {
    return `${value} (mixed currencies)`;
  }
  if (activity.revenue_currency === "USD") {
    return `$${value}`;
  }
  if (activity.revenue_currency) {
    return `${activity.revenue_currency} ${value}`;
  }
  return value;
}

export function formatDurationSeconds(value: number | null) {
  if (value === null) {
    return "—";
  }
  if (value < 60) {
    return `${Math.round(value)}s`;
  }
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

export function buildMarketPanelState(snapshot: EtsySnapshot) {
  if (snapshot.available) {
    return {
      title: "Market snapshot",
      description: "Live Etsy shop totals for the current scope.",
    };
  }
  return {
    title: "Market snapshot unavailable",
    description:
      snapshot.unavailable_reason ?? "Connect Etsy in Settings to unlock market analytics.",
  };
}
