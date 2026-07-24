"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  CircleHelp,
  Download,
  Link2,
  Plus,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts";
import { useAppSessionContext } from "@/components/auth/app-session-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Calendar } from "@/components/ui/calendar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/workspace/page-header";
import {
  GenericPageSkeleton,
  ResourceError,
} from "@/components/workspace/resource-state";
import { SimpleTable } from "@/components/workspace/simple-table";
import { useStoreContext } from "@/components/workspace/store-context";
import { useCachedWorkspaceResource } from "@/hooks/use-cached-workspace-resource";
import { useRefetchOnWindowFocus } from "@/hooks/use-refetch-on-window-focus";
import {
  createAnalyticsExpense,
  deleteAnalyticsExpense,
  fetchBusinessAnalytics,
  fetchBusinessAnalyticsDetails,
  fetchWorkspaceAnalytics,
  formatDateTime,
  mapAnalyticsOrderLine,
  providerLabel,
  updateAnalyticsPreferences,
  type AnalyticsPreset,
  type AnalyticsDetailPage,
  type AnalyticsDetailResource,
  type BusinessAnalyticsResponse,
  type ExpenseInput,
  type ExpenseRecord,
  type ProductPerformanceRow,
  type ReportingCurrency,
  type SeoPerformanceRow,
  type StorePerformanceRow,
  type UnmatchedOrderLine,
  type WorkspaceAnalyticsResponse,
} from "@/lib/backend-api";
import { workspacePageCacheKeys } from "@/lib/workspace-page-cache-keys";
import { cleanStoreDisplayName } from "@/lib/store-display";
import { format } from "date-fns";

type AnalyticsPageData = {
  business: BusinessAnalyticsResponse;
  operations: WorkspaceAnalyticsResponse;
};

type ChartMode = "pnl" | "orders" | "margin";
type ProductMeasure = "revenue" | "units" | "gross_profit" | "net_profit";
type AnalyticsDetailQuery = {
  storeConnectionId?: string;
  preset: AnalyticsPreset;
  currency: ReportingCurrency;
  timezone: string;
  start?: string;
  end?: string;
  revision: number;
};

const ANALYTICS_PAGE_SIZE = 25;

const PRESETS: Array<{ value: AnalyticsPreset; label: string }> = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "this_year", label: "This year" },
  { value: "all_time", label: "All time" },
  { value: "custom", label: "Custom range" },
];
const CURRENCIES: ReportingCurrency[] = ["PHP", "USD", "EUR", "JPY"];
const VELORA_CHART_GREEN = "hsl(var(--primary))";

const chartConfig = {
  revenue: { label: "Revenue", color: VELORA_CHART_GREEN },
  expenses: { label: "Expenses", color: "hsl(40 4% 61%)" },
  gross_profit: { label: "Gross profit", color: "hsl(173 58% 48%)" },
  net_profit: { label: "Net profit", color: "hsl(188 46% 38%)" },
  orders: { label: "Orders", color: VELORA_CHART_GREEN },
  comparison_revenue: { label: "Previous period", color: "hsl(40 4% 61%)" },
  comparison_orders: { label: "Previous period", color: "hsl(40 4% 61%)" },
  margin: { label: "Net margin", color: VELORA_CHART_GREEN },
} satisfies ChartConfig;

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Manila";
  } catch {
    return "Asia/Manila";
  }
}

function formatMoney(value: number | null, currency: ReportingCurrency) {
  if (value === null) return "Unavailable";
  return new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency,
    maximumFractionDigits: currency === "JPY" ? 0 : 2,
  }).format(value);
}

function formatCompactMoney(value: number | null, currency: ReportingCurrency) {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-PH", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatPercent(value: number | null) {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function comparisonPercent(current: number | null, previous: number | null) {
  if (current === null || previous === null || previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

function channelLabel(channel: string) {
  if (channel === "etsy") return "Etsy";
  if (channel === "shopify") return "Shopify";
  return channel || "Other";
}

function csvCell(value: string | number | null) {
  let normalized = String(value ?? "");
  if (typeof value === "string" && /^[=+\-@]/.test(normalized)) {
    normalized = `'${normalized}`;
  }
  return `"${normalized.replaceAll('"', '""')}"`;
}

function downloadCsv(filename: string, rows: Array<Array<string | number | null>>) {
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
  const blob = new Blob(["\uFEFF", csv], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function downloadProductsCsv(
  rows: ProductPerformanceRow[],
  currency: ReportingCurrency
) {
  downloadCsv(
    `velora-product-analytics-${new Date().toISOString().slice(0, 10)}.csv`,
    [
      [
        "Product",
        "Store",
        "Units",
        `Revenue (${currency})`,
        `Gross profit (${currency})`,
        `Net profit (${currency})`,
        "Margin (%)",
        "SEO score",
      ],
      ...rows.map((row) => [
        row.title,
        cleanStoreDisplayName(row.store_label),
        row.units,
        row.revenue,
        row.gross_profit,
        row.net_profit,
        row.margin_percent,
        row.seo_score,
      ]),
    ]
  );
}

function downloadStoresCsv(
  rows: StorePerformanceRow[],
  currency: ReportingCurrency
) {
  downloadCsv(
    `velora-store-analytics-${new Date().toISOString().slice(0, 10)}.csv`,
    [
      [
        "POD provider",
        "Channel",
        "Store",
        "Orders",
        "Units",
        `Revenue (${currency})`,
        `Expenses (${currency})`,
        `Net profit (${currency})`,
        "Margin (%)",
        "Unmatched",
      ],
      ...rows
        .sort(
          (left, right) =>
            providerLabel(left.provider).localeCompare(
              providerLabel(right.provider),
              undefined,
              { sensitivity: "base" }
            ) ||
            channelLabel(left.storefront_type).localeCompare(
              channelLabel(right.storefront_type),
              undefined,
              { sensitivity: "base" }
            ) ||
            cleanStoreDisplayName(left.store_label).localeCompare(
              cleanStoreDisplayName(right.store_label),
              undefined,
              { sensitivity: "base" }
            )
        )
        .map((row) => [
          providerLabel(row.provider),
          channelLabel(row.storefront_type),
          cleanStoreDisplayName(row.store_label),
          row.order_count,
          row.units,
          row.revenue,
          row.expenses,
          row.net_profit,
          row.margin_percent,
          row.unmatched_line_count,
        ]),
    ]
  );
}

function Metric({
  label,
  value,
  detail,
  change,
  coverage,
}: {
  label: string;
  value: string;
  detail: string;
  change?: number | null;
  coverage?: number;
}) {
  return (
    <div className="min-w-0 px-4 py-4 lg:px-5">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {label}
        {coverage !== undefined && coverage < 100 ? (
          <span title={`${coverage.toFixed(0)}% data coverage`}>
            <CircleHelp className="h-3.5 w-3.5" />
          </span>
        ) : null}
      </div>
      <div className="truncate text-xl font-semibold tracking-tight text-foreground xl:text-2xl">
        {value}
      </div>
      <div className="mt-1 flex min-h-5 items-center gap-1.5 text-xs text-muted-foreground">
        {change !== undefined && change !== null ? (
          <span
            className={
              change >= 0
                ? "inline-flex items-center text-emerald-600 dark:text-emerald-400"
                : "inline-flex items-center text-rose-600 dark:text-rose-400"
            }
          >
            {change >= 0 ? (
              <ArrowUpRight className="mr-0.5 h-3.5 w-3.5" />
            ) : (
              <ArrowDownRight className="mr-0.5 h-3.5 w-3.5" />
            )}
            {Math.abs(change).toFixed(1)}%
          </span>
        ) : null}
        <span>{detail}</span>
      </div>
    </div>
  );
}

function SectionHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-border pb-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

function AnalyticsChart({
  analytics,
  mode,
}: {
  analytics: BusinessAnalyticsResponse;
  mode: ChartMode;
}) {
  const data = analytics.trend.map((point) => ({
    ...point,
    margin:
      point.net_profit !== null && point.revenue
        ? (point.net_profit / point.revenue) * 100
        : null,
  }));

  return (
    <div className="space-y-4">
      <ChartContainer config={chartConfig} className="h-[320px] w-full aspect-auto">
        {mode === "orders" ? (
          <LineChart data={data} accessibilityLayer margin={{ left: 4, right: 12 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="period" tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis tickLine={false} axisLine={false} width={38} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line
              type="monotone"
              dataKey="orders"
              stroke={VELORA_CHART_GREEN}
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="comparison_orders"
              stroke="var(--color-comparison_orders)"
              strokeWidth={1.5}
              strokeDasharray="5 5"
              dot={false}
            />
          </LineChart>
        ) : mode === "margin" ? (
          <LineChart data={data} accessibilityLayer margin={{ left: 4, right: 12 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="period" tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis tickLine={false} axisLine={false} width={42} unit="%" />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line
              type="monotone"
              dataKey="margin"
              stroke={VELORA_CHART_GREEN}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
            />
          </LineChart>
        ) : (
          <AreaChart data={data} accessibilityLayer margin={{ left: 4, right: 12 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="period" tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={58}
              tickFormatter={(value) => formatCompactMoney(Number(value), analytics.currency)}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  formatter={(value) =>
                    formatMoney(Number(value), analytics.currency)
                  }
                />
              }
            />
            <Area
              type="monotone"
              dataKey="revenue"
              stroke={VELORA_CHART_GREEN}
              fill={VELORA_CHART_GREEN}
              fillOpacity={0.2}
              strokeWidth={2.5}
            />
            <Area
              type="monotone"
              dataKey="expenses"
              stroke="var(--color-expenses)"
              fill="var(--color-expenses)"
              fillOpacity={0.05}
              strokeWidth={1.5}
            />
            <Line
              type="monotone"
              dataKey="comparison_revenue"
              stroke="var(--color-comparison_revenue)"
              strokeDasharray="5 5"
              strokeWidth={1.5}
              dot={false}
            />
          </AreaChart>
        )}
      </ChartContainer>

      <details className="group border-t border-border pt-3">
        <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
          View chart data
        </summary>
        <div className="mt-3 max-h-64 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-background text-muted-foreground">
              <tr>
                <th className="py-2 font-medium">Period</th>
                <th className="py-2 text-right font-medium">Revenue</th>
                <th className="py-2 text-right font-medium">Expenses</th>
                <th className="py-2 text-right font-medium">Orders</th>
              </tr>
            </thead>
            <tbody>
              {analytics.trend.map((point) => (
                <tr key={point.period} className="border-t border-border/70">
                  <td className="py-2">{point.period}</td>
                  <td className="py-2 text-right">
                    {formatMoney(point.revenue, analytics.currency)}
                  </td>
                  <td className="py-2 text-right">
                    {formatMoney(point.expenses, analytics.currency)}
                  </td>
                  <td className="py-2 text-right">{point.orders}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function useAnalyticsDetailPage<T>({
  resource,
  query,
  productMeasure,
}: {
  resource: AnalyticsDetailResource;
  query: AnalyticsDetailQuery;
  productMeasure?: ProductMeasure;
}) {
  const [page, setPage] = useState(1);
  const filterKey = [
    query.storeConnectionId ?? "all",
    query.preset,
    query.currency,
    query.timezone,
    query.start ?? "",
    query.end ?? "",
    query.revision,
    productMeasure ?? "",
  ].join(":");

  useEffect(() => {
    setPage(1);
  }, [filterKey]);

  const loadResource = useCallback(
    () =>
      fetchBusinessAnalyticsDetails<T>({
        resource,
        storeConnectionId: query.storeConnectionId,
        preset: query.preset,
        currency: query.currency,
        timezone: query.timezone,
        start: query.start,
        end: query.end,
        page,
        pageSize: ANALYTICS_PAGE_SIZE,
        productMeasure,
      }),
    [
      page,
      productMeasure,
      query.currency,
      query.end,
      query.preset,
      query.start,
      query.storeConnectionId,
      query.timezone,
      resource,
    ]
  );
  const detail = useCachedWorkspaceResource<AnalyticsDetailPage<T>>({
    cacheKey: `analytics-details:${resource}:${filterKey}:${page}:${ANALYTICS_PAGE_SIZE}`,
    loadResource,
    keepPreviousData: true,
  });

  useEffect(() => {
    if (
      detail.data &&
      detail.data.total_pages > 0 &&
      page > detail.data.total_pages
    ) {
      setPage(detail.data.total_pages);
    }
  }, [detail.data, page]);

  return { ...detail, page, setPage };
}

function AnalyticsPagination({
  page,
  totalPages,
  total,
  pageSize,
  onPageChange,
  disabled,
}: {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
}) {
  if (totalPages <= 1) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs tabular-nums text-muted-foreground">
        {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}
      </p>
      <div className="flex items-center gap-3">
        <span className="text-xs tabular-nums text-muted-foreground">
          Page {page.toLocaleString()} of {totalPages.toLocaleString()}
        </span>
        <Pagination className="mx-0 w-auto justify-end">
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                aria-disabled={disabled || page <= 1}
                className={
                  disabled || page <= 1
                    ? "pointer-events-none opacity-50"
                    : undefined
                }
                onClick={(event) => {
                  event.preventDefault();
                  if (!disabled && page > 1) onPageChange(page - 1);
                }}
              />
            </PaginationItem>
            <PaginationItem>
              <PaginationNext
                href="#"
                aria-disabled={disabled || page >= totalPages}
                className={
                  disabled || page >= totalPages
                    ? "pointer-events-none opacity-50"
                    : undefined
                }
                onClick={(event) => {
                  event.preventDefault();
                  if (!disabled && page < totalPages) onPageChange(page + 1);
                }}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </div>
    </div>
  );
}

function DetailLoading() {
  return (
    <div className="flex min-h-36 items-center justify-center border border-border text-sm text-muted-foreground">
      <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
      Loading table…
    </div>
  );
}

function ExpenseDialog({
  open,
  onOpenChange,
  currency,
  storeConnectionId,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currency: ReportingCurrency;
  storeConnectionId: string | null;
  onSaved: () => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [form, setForm] = useState<ExpenseInput>({
    incurred_on: new Date().toISOString(),
    category: "operating",
    amount: 0,
    currency,
    note: "",
    provider_store_connection_id: storeConnectionId,
  });

  useEffect(() => {
    setForm((current) => ({
      ...current,
      currency,
      provider_store_connection_id: storeConnectionId,
    }));
  }, [currency, storeConnectionId]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await createAnalyticsExpense(form);
      await onSaved();
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Unable to save expense.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setDatePickerOpen(false);
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add expense</DialogTitle>
          <DialogDescription>
            Record an expense without spreading it across products automatically.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="expense-date">Date</Label>
              <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
                <PopoverTrigger asChild>
                  <Button
                    id="expense-date"
                    type="button"
                    variant="outline"
                    className="h-10 w-full justify-start px-3 text-left font-normal"
                  >
                    <CalendarDays className="mr-2 h-4 w-4 text-muted-foreground" />
                    {format(new Date(form.incurred_on), "MMM d, yyyy")}
                  </Button>
                </PopoverTrigger>
                <PopoverContent
                  align="start"
                  portalled={false}
                  className="z-[60] w-auto border-border bg-popover p-0"
                >
                  <Calendar
                    mode="single"
                    selected={new Date(form.incurred_on)}
                    captionLayout="dropdown"
                    startMonth={new Date(1970, 0)}
                    endMonth={new Date(new Date().getFullYear() + 1, 11)}
                    onSelect={(selectedDate) => {
                      if (!selectedDate) return;
                      const localNoon = new Date(
                        selectedDate.getFullYear(),
                        selectedDate.getMonth(),
                        selectedDate.getDate(),
                        12
                      );
                      setForm((current) => ({
                        ...current,
                        incurred_on: localNoon.toISOString(),
                      }));
                      setDatePickerOpen(false);
                    }}
                    autoFocus
                  />
                </PopoverContent>
              </Popover>
            </div>
            <div className="space-y-2">
              <Label htmlFor="expense-category">Category</Label>
              <Input
                id="expense-category"
                value={form.category}
                onChange={(event) =>
                  setForm((current) => ({ ...current, category: event.target.value }))
                }
                placeholder="Advertising"
              />
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-[1fr_120px]">
            <div className="space-y-2">
              <Label htmlFor="expense-amount">Amount</Label>
              <Input
                id="expense-amount"
                type="number"
                min="0"
                step="0.01"
                value={form.amount}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    amount: Number(event.target.value),
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Currency</Label>
              <Select
                value={form.currency}
                onValueChange={(value) =>
                  setForm((current) => ({
                    ...current,
                    currency: value as ReportingCurrency,
                  }))
                }
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CURRENCIES.map((value) => (
                    <SelectItem key={value} value={value}>{value}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="expense-note">Note</Label>
            <Textarea
              id="expense-note"
              value={form.note ?? ""}
              onChange={(event) =>
                setForm((current) => ({ ...current, note: event.target.value }))
              }
              placeholder="Optional context for this expense"
            />
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={saving || !form.category || form.amount < 0}>
            {saving ? "Saving..." : "Add expense"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MappingDialog({
  line,
  products,
  open,
  onOpenChange,
  onMapped,
}: {
  line: UnmatchedOrderLine | null;
  products: ProductPerformanceRow[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onMapped: () => Promise<void>;
}) {
  const [productId, setProductId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setProductId("");
    setError(null);
  }, [line]);

  async function submit() {
    if (!line || !productId) return;
    setSaving(true);
    setError(null);
    try {
      await mapAnalyticsOrderLine(line.id, productId);
      await onMapped();
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Unable to map item.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Map unmatched item</DialogTitle>
          <DialogDescription>
            This mapping repairs historical product attribution for the selected line.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="border-l-2 border-primary pl-3">
            <div className="text-sm font-medium text-foreground">{line?.title}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              Order {line?.order_display_id} · {cleanStoreDisplayName(line?.store_label)}
            </div>
          </div>
          <div className="space-y-2">
            <Label>Velora product</Label>
            <Select value={productId} onValueChange={setProductId}>
              <SelectTrigger><SelectValue placeholder="Select product" /></SelectTrigger>
              <SelectContent>
                {products.map((product) => (
                  <SelectItem key={product.product_id} value={product.product_id}>
                    {product.title} · {cleanStoreDisplayName(product.store_label)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={saving || !productId}>
            {saving ? "Mapping..." : "Save mapping"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AnalyticsPage() {
  const { selectedStoreId } = useStoreContext();
  const { sessionContext } = useAppSessionContext();
  const isAdmin = sessionContext.membership?.role === "admin";
  const [preset, setPreset] = useState<AnalyticsPreset>("30d");
  const [currency, setCurrency] = useState<ReportingCurrency>("PHP");
  const [timezone, setTimezone] = useState(browserTimezone);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [chartMode, setChartMode] = useState<ChartMode>("pnl");
  const [productMeasure, setProductMeasure] = useState<ProductMeasure>("revenue");
  const [expenseOpen, setExpenseOpen] = useState(false);
  const [mappingLine, setMappingLine] = useState<UnmatchedOrderLine | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const [detailRevision, setDetailRevision] = useState(0);

  const queryKey = [
    selectedStoreId,
    preset,
    currency,
    timezone,
    customStart,
    customEnd,
  ].join(":");
  const loadAnalytics = useCallback(
    async (): Promise<AnalyticsPageData> => {
      const [business, operations] = await Promise.all([
        fetchBusinessAnalytics({
          storeConnectionId: selectedStoreId,
          preset,
          currency,
          timezone,
          start: preset === "custom" ? customStart : undefined,
          end: preset === "custom" ? customEnd : undefined,
        }),
        fetchWorkspaceAnalytics(selectedStoreId),
      ]);
      return { business, operations };
    },
    [currency, customEnd, customStart, preset, selectedStoreId, timezone]
  );
  const {
    data,
    error,
    load,
    loading,
    refreshing,
    isCacheFresh,
  } = useCachedWorkspaceResource<AnalyticsPageData>({
    cacheKey: workspacePageCacheKeys.analyticsBusiness(queryKey),
    loadResource: loadAnalytics,
    keepPreviousData: true,
  });

  useRefetchOnWindowFocus(
    useCallback(async () => {
      await load("background", "if-stale");
    }, [load]),
    { shouldRefetch: () => !isCacheFresh() }
  );

  useEffect(() => {
    if (!isAdmin || typeof window === "undefined") return;
    const storageKey = "velora:analytics-timezone-captured";
    if (window.localStorage.getItem(storageKey)) return;
    window.localStorage.setItem(storageKey, "true");
    void updateAnalyticsPreferences({
      reporting_currency: currency,
      reporting_timezone: timezone,
    });
  }, [currency, isAdmin, timezone]);

  useEffect(() => {
    if (!exportNotice) return;
    const timeoutId = window.setTimeout(() => setExportNotice(null), 3_500);
    return () => window.clearTimeout(timeoutId);
  }, [exportNotice]);

  const revenueChange = useMemo(
    () =>
      data
        ? comparisonPercent(
            data.business.summary.revenue.amount,
            data.business.summary.previous_revenue
          )
        : null,
    [data]
  );
  if (loading) {
    return (
      <>
        <PageHeader title="Analytics" preserveActionSpace />
        <GenericPageSkeleton />
      </>
    );
  }

  if (error || !data) {
    return (
      <>
        <PageHeader title="Analytics" preserveActionSpace />
        <ResourceError
          message={error ?? "Unable to load analytics right now."}
          onRetry={() => void load()}
        />
      </>
    );
  }

  const { business, operations } = data;
  const displayCurrency = business.currency;
  const mappedStoreId = business.scope.is_all_stores
    ? null
    : business.scope.store_connection_id;
  const detailQuery: AnalyticsDetailQuery = {
    storeConnectionId: selectedStoreId,
    preset,
    currency: displayCurrency,
    timezone,
    start: preset === "custom" ? customStart : undefined,
    end: preset === "custom" ? customEnd : undefined,
    revision: detailRevision,
  };

  async function refreshAfterMutation() {
    setDetailRevision((current) => current + 1);
    await load("background");
  }

  function selectCurrency(value: ReportingCurrency) {
    setCurrency(value);
    if (isAdmin) {
      void updateAnalyticsPreferences({ reporting_currency: value });
    }
  }

  return (
    <>
      <PageHeader
        title="Analytics"
        action={
          <Button
            variant="outline"
            onClick={() => void load("background")}
            disabled={refreshing}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Refreshing" : "Refresh"}
          </Button>
        }
      />

      <div className="space-y-5">
        <div className="flex flex-col gap-3 border-b border-border pb-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={preset} onValueChange={(value) => setPreset(value as AnalyticsPreset)}>
              <SelectTrigger className="w-[170px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {PRESETS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {preset === "custom" ? (
              <>
                <Input
                  type="date"
                  aria-label="Analytics start date"
                  className="w-[150px]"
                  value={customStart}
                  onChange={(event) => setCustomStart(event.target.value)}
                />
                <span className="text-xs text-muted-foreground">to</span>
                <Input
                  type="date"
                  aria-label="Analytics end date"
                  className="w-[150px]"
                  value={customEnd}
                  onChange={(event) => setCustomEnd(event.target.value)}
                />
              </>
            ) : null}
            <Select
              value={currency}
              onValueChange={(value) => selectCurrency(value as ReportingCurrency)}
            >
              <SelectTrigger className="w-[92px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((value) => (
                  <SelectItem key={value} value={value}>{value}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{cleanStoreDisplayName(business.scope.label, "All Stores")}</span>
            <span aria-hidden>·</span>
            <span>{business.timezone}</span>
            <span aria-hidden>·</span>
            <span>Updated {formatDateTime(business.generated_at)}</span>
          </div>
        </div>

        {business.capabilities.authorization_upgrade_required ? (
          <div className="flex flex-col gap-3 border-l-2 border-amber-500 bg-amber-500/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex gap-3">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
              <div>
                <div className="text-sm font-medium text-foreground">Etsy finance access required</div>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  Grant analytics access to import receipts, transactions, fees, and refunds.
                </p>
              </div>
            </div>
            <Button variant="outline" size="sm" asChild>
              <a href="/settings">Grant analytics access</a>
            </Button>
          </div>
        ) : null}

        {business.warnings.length ? (
          <div className="flex gap-3 border-l-2 border-amber-500 px-4 py-2.5">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
            <div className="space-y-1 text-sm text-muted-foreground">
              {business.warnings.map((warning) => <p key={warning}>{warning}</p>)}
            </div>
          </div>
        ) : null}

        <div className="grid divide-y divide-border border-y border-border [&>*]:border-border sm:grid-cols-2 sm:[&>*:nth-child(odd)]:border-r lg:grid-cols-6 lg:divide-y-0 lg:[&>*]:border-r lg:[&>*:last-child]:border-r-0">
          <Metric
            label="Revenue"
            value={formatMoney(business.summary.revenue.amount, displayCurrency)}
            detail="vs previous period"
            change={revenueChange}
            coverage={business.summary.revenue.coverage_percent}
          />
          <Metric
            label="Expenses"
            value={formatMoney(business.summary.expenses.amount, displayCurrency)}
            detail="direct and unallocated"
            coverage={business.summary.expenses.coverage_percent}
          />
          <Metric
            label="Gross profit"
            value={formatMoney(business.summary.gross_profit.amount, displayCurrency)}
            detail={`${formatPercent(business.summary.gross_margin_percent)} margin`}
            coverage={business.summary.gross_profit.coverage_percent}
          />
          <Metric
            label="Net profit"
            value={formatMoney(business.summary.net_profit.amount, displayCurrency)}
            detail={`${formatPercent(business.summary.net_margin_percent)} margin`}
            coverage={business.summary.net_profit.coverage_percent}
          />
          <Metric
            label="Orders"
            value={business.summary.order_count.toLocaleString()}
            detail={`${business.summary.unit_count.toLocaleString()} mapped units`}
          />
          <Metric
            label="Unmatched"
            value={business.summary.unmatched_line_count.toLocaleString()}
            detail="requires product mapping"
          />
        </div>

        <Tabs defaultValue="overview" className="space-y-5">
          <TabsList className="h-auto w-full justify-start overflow-x-auto rounded-none border-b border-border bg-transparent p-0">
            {["Overview", "Products", "Stores", "Expenses", "SEO", "Operations"].map((label) => (
              <TabsTrigger
                key={label}
                value={label.toLowerCase()}
                className="rounded-none border-b-2 border-transparent px-4 py-3 text-sm data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              >
                {label}
                {label === "Operations" && business.summary.unmatched_line_count > 0 ? (
                  <span className="ml-2 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-600 dark:text-amber-400">
                    {business.summary.unmatched_line_count}
                  </span>
                ) : null}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview" className="space-y-6">
            <section className="space-y-4">
              <SectionHeading
                title="Performance trend"
                description={`Current period is solid; the previous equal-length period is dashed. Grouped by ${business.trend_granularity}.`}
                action={
                  <div className="inline-flex rounded-md border border-border p-0.5">
                    {([
                      ["pnl", "P&L"],
                      ["orders", "Orders"],
                      ["margin", "Margin"],
                    ] as Array<[ChartMode, string]>).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setChartMode(value)}
                        className={`rounded px-2.5 py-1 text-xs transition-colors ${
                          chartMode === value
                            ? "bg-muted text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                }
              />
              <AnalyticsChart analytics={business} mode={chartMode} />
            </section>

            <section className="space-y-4">
              <SectionHeading
                title="Store comparison"
                description="Marketplace revenue and attributed expenses across connected stores."
              />
              <StoreTable rows={business.stores} currency={displayCurrency} />
            </section>
          </TabsContent>

          <TabsContent value="products" className="space-y-4">
            <PaginatedProductSection
              query={detailQuery}
              currency={displayCurrency}
              measure={productMeasure}
              onMeasureChange={setProductMeasure}
              onExportStarted={() =>
                setExportNotice("Product analytics CSV download started.")
              }
            />
          </TabsContent>

          <TabsContent value="stores" className="space-y-4">
            <SectionHeading
              title="Store performance"
              description="One row per connected marketplace destination, ready for future Shopify stores."
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    downloadStoresCsv([...business.stores], displayCurrency);
                    setExportNotice("Store analytics CSV download started.");
                  }}
                  disabled={!business.stores.length}
                >
                  <Download className="mr-2 h-3.5 w-3.5" /> Export CSV
                </Button>
              }
            />
            <StoreTable rows={business.stores} currency={displayCurrency} />
          </TabsContent>

          <TabsContent value="expenses" className="space-y-4">
            <SectionHeading
              title="Expense ledger"
              description="Imported and manual costs. Unallocated overhead remains organization-level."
              action={
                isAdmin ? (
                  <Button size="sm" onClick={() => setExpenseOpen(true)}>
                    <Plus className="mr-2 h-3.5 w-3.5" /> Add expense
                  </Button>
                ) : undefined
              }
            />
            <PaginatedExpenseTable
              query={detailQuery}
              isAdmin={isAdmin}
              onMutated={refreshAfterMutation}
            />
          </TabsContent>

          <TabsContent value="seo" className="space-y-5">
            <div className="flex gap-3 border-l-2 border-border px-4 py-2.5">
              <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="text-sm text-muted-foreground">
                Scores are deterministic listing-quality checks. Etsy does not expose impressions,
                CTR, search terms, or authoritative keyword rank through the current API.
              </div>
            </div>
            <SectionHeading
              title="Listing optimization"
              description="Lowest scores first so the next useful edit is easy to identify."
            />
            <PaginatedSeoTable query={detailQuery} />
          </TabsContent>

          <TabsContent value="operations" className="space-y-6">
            <section className="space-y-4">
              <SectionHeading
                title="Unmatched sales"
                description="These sales remain in store totals but are excluded from named product rankings."
              />
              <PaginatedUnmatchedTable
                query={detailQuery}
                currency={displayCurrency}
                isAdmin={isAdmin}
                onMap={setMappingLine}
              />
            </section>
            <section className="space-y-4">
              <SectionHeading
                title="Publishing operations"
                description="Secondary workflow diagnostics from the existing operational analytics service."
              />
              <div className="grid divide-y divide-border border-y border-border [&>*]:border-border sm:grid-cols-2 sm:divide-y-0 sm:[&>*]:border-r sm:[&>*:last-child]:border-r-0 lg:grid-cols-4">
                <Metric
                  label="Queued"
                  value={operations.workflow_health.queued_job_count.toLocaleString()}
                  detail="publishing jobs"
                />
                <Metric
                  label="In progress"
                  value={operations.workflow_health.in_progress_job_count.toLocaleString()}
                  detail="currently running"
                />
                <Metric
                  label="Failed"
                  value={operations.workflow_health.failed_job_count_last_30_days.toLocaleString()}
                  detail="last 30 days"
                />
                <Metric
                  label="Needs listing work"
                  value={operations.overview.listings_needing_attention_count.toLocaleString()}
                  detail="catalog issues"
                />
              </div>
            </section>
          </TabsContent>
        </Tabs>
      </div>

      {exportNotice ? (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-5 right-5 z-50 flex max-w-sm items-center gap-2.5 rounded-md border border-primary/30 bg-popover px-4 py-3 text-sm text-popover-foreground shadow-lg"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
          {exportNotice}
        </div>
      ) : null}

      <ExpenseDialog
        open={expenseOpen}
        onOpenChange={setExpenseOpen}
        currency={currency}
        storeConnectionId={mappedStoreId}
        onSaved={refreshAfterMutation}
      />
      <MappingDialog
        line={mappingLine}
        products={business.products}
        open={mappingLine !== null}
        onOpenChange={(open) => {
          if (!open) setMappingLine(null);
        }}
        onMapped={refreshAfterMutation}
      />
    </>
  );
}

function PaginatedProductSection({
  query,
  currency,
  measure,
  onMeasureChange,
  onExportStarted,
}: {
  query: AnalyticsDetailQuery;
  currency: ReportingCurrency;
  measure: ProductMeasure;
  onMeasureChange: (measure: ProductMeasure) => void;
  onExportStarted: () => void;
}) {
  const detail = useAnalyticsDetailPage<ProductPerformanceRow>({
    resource: "products",
    query,
    productMeasure: measure,
  });
  const [exporting, setExporting] = useState(false);

  async function exportAll() {
    if (!detail.data?.total || exporting) return;
    setExporting(true);
    try {
      const exportPageSize = 100;
      const totalPages = Math.ceil(detail.data.total / exportPageSize);
      const rows: ProductPerformanceRow[] = [];
      for (let page = 1; page <= totalPages; page += 1) {
        const response = await fetchBusinessAnalyticsDetails<ProductPerformanceRow>({
          resource: "products",
          storeConnectionId: query.storeConnectionId,
          preset: query.preset,
          currency: query.currency,
          timezone: query.timezone,
          start: query.start,
          end: query.end,
          page,
          pageSize: exportPageSize,
          productMeasure: measure,
        });
        rows.push(...response.items);
      }
      downloadProductsCsv(rows, currency);
      onExportStarted();
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <SectionHeading
        title="Product performance"
        description={`Ranked by ${measure.replace("_", " ")} while keeping profitability coverage explicit.`}
        action={
          <div className="flex items-center gap-2">
            <Select
              value={measure}
              onValueChange={(value) => onMeasureChange(value as ProductMeasure)}
            >
              <SelectTrigger className="h-8 w-[150px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="revenue">Revenue</SelectItem>
                <SelectItem value="units">Units sold</SelectItem>
                <SelectItem value="gross_profit">Gross profit</SelectItem>
                <SelectItem value="net_profit">Net profit</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void exportAll()}
              disabled={!detail.data?.total || exporting}
            >
              <Download className="mr-2 h-3.5 w-3.5" />
              {exporting ? "Preparing…" : "Export CSV"}
            </Button>
          </div>
        }
      />
      {detail.loading && !detail.data ? (
        <DetailLoading />
      ) : detail.error || !detail.data ? (
        <ResourceError
          message={detail.error ?? "Unable to load product analytics."}
          onRetry={() => void detail.load("blocking", "force")}
        />
      ) : (
        <>
          <ProductTable
            rows={detail.data.items}
            currency={currency}
            measure={measure}
            rankOffset={(detail.data.page - 1) * detail.data.page_size}
          />
          <AnalyticsPagination
            page={detail.data.page}
            totalPages={detail.data.total_pages}
            total={detail.data.total}
            pageSize={detail.data.page_size}
            onPageChange={detail.setPage}
            disabled={detail.refreshing}
          />
        </>
      )}
    </>
  );
}

function PaginatedExpenseTable({
  query,
  isAdmin,
  onMutated,
}: {
  query: AnalyticsDetailQuery;
  isAdmin: boolean;
  onMutated: () => Promise<void>;
}) {
  const detail = useAnalyticsDetailPage<ExpenseRecord>({
    resource: "expenses",
    query,
  });
  if (detail.loading && !detail.data) return <DetailLoading />;
  if (detail.error || !detail.data) {
    return (
      <ResourceError
        message={detail.error ?? "Unable to load expenses."}
        onRetry={() => void detail.load("blocking", "force")}
      />
    );
  }
  return (
    <>
      <ExpenseTable
        rows={detail.data.items}
        isAdmin={isAdmin}
        onDelete={async (expense) => {
          await deleteAnalyticsExpense(expense.id);
          await onMutated();
        }}
      />
      <AnalyticsPagination
        page={detail.data.page}
        totalPages={detail.data.total_pages}
        total={detail.data.total}
        pageSize={detail.data.page_size}
        onPageChange={detail.setPage}
        disabled={detail.refreshing}
      />
    </>
  );
}

function PaginatedSeoTable({ query }: { query: AnalyticsDetailQuery }) {
  const detail = useAnalyticsDetailPage<SeoPerformanceRow>({
    resource: "seo",
    query,
  });
  if (detail.loading && !detail.data) return <DetailLoading />;
  if (detail.error || !detail.data) {
    return (
      <ResourceError
        message={detail.error ?? "Unable to load listing optimization data."}
        onRetry={() => void detail.load("blocking", "force")}
      />
    );
  }
  return (
    <>
      <SeoTable rows={detail.data.items} />
      <AnalyticsPagination
        page={detail.data.page}
        totalPages={detail.data.total_pages}
        total={detail.data.total}
        pageSize={detail.data.page_size}
        onPageChange={detail.setPage}
        disabled={detail.refreshing}
      />
    </>
  );
}

function PaginatedUnmatchedTable({
  query,
  currency,
  isAdmin,
  onMap,
}: {
  query: AnalyticsDetailQuery;
  currency: ReportingCurrency;
  isAdmin: boolean;
  onMap: (line: UnmatchedOrderLine) => void;
}) {
  const detail = useAnalyticsDetailPage<UnmatchedOrderLine>({
    resource: "unmatched",
    query,
  });
  if (detail.loading && !detail.data) return <DetailLoading />;
  if (detail.error || !detail.data) {
    return (
      <ResourceError
        message={detail.error ?? "Unable to load unmatched sales."}
        onRetry={() => void detail.load("blocking", "force")}
      />
    );
  }
  return (
    <>
      <UnmatchedTable
        rows={detail.data.items}
        currency={currency}
        isAdmin={isAdmin}
        onMap={onMap}
      />
      <AnalyticsPagination
        page={detail.data.page}
        totalPages={detail.data.total_pages}
        total={detail.data.total}
        pageSize={detail.data.page_size}
        onPageChange={detail.setPage}
        disabled={detail.refreshing}
      />
    </>
  );
}

function ProductTable({
  rows,
  currency,
  measure,
  rankOffset = 0,
}: {
  rows: ProductPerformanceRow[];
  currency: ReportingCurrency;
  measure: ProductMeasure;
  rankOffset?: number;
}) {
  if (!rows.length) {
    return <EmptyLedger message="No products are available in this scope." />;
  }
  return (
    <SimpleTable
      className="rounded-md bg-background"
      rows={rows}
      columns={[
        {
          key: "title",
          label: "Product",
          className: "min-w-[240px]",
          render: (row) => (
            <div>
              <a href={`/products/${row.product_id}`} className="font-medium hover:text-primary">
                {row.title}
              </a>
              <div className="mt-1 text-xs text-muted-foreground">
                {cleanStoreDisplayName(row.store_label)}
              </div>
            </div>
          ),
        },
        {
          key: "performance",
          label: "Performance",
          render: (row) => {
            const value = row[measure];
            const rank = rankOffset + rows.indexOf(row);
            const inactive = !["published", "active"].includes(row.status.toLowerCase());
            const label = inactive
              ? "Inactive"
              : row.active_days < 30
                ? "New"
                : value === null
                  ? "Insufficient data"
                  : rank === 0 && value > 0
                    ? "Best seller"
                    : value <= 0
                      ? "Needs attention"
                      : "Tracking";
            return (
              <Badge
                variant="outline"
                className={
                  label === "Best seller"
                    ? "border-primary/30 text-primary"
                    : label === "Needs attention"
                      ? "border-amber-500/30 text-amber-600 dark:text-amber-400"
                      : "font-normal text-muted-foreground"
                }
              >
                {label}
              </Badge>
            );
          },
        },
        { key: "units", label: "Units", className: "text-right", render: (row) => row.units.toLocaleString() },
        { key: "revenue", label: "Revenue", className: "text-right", render: (row) => formatMoney(row.revenue, currency) },
        { key: "gross_profit", label: "Gross profit", className: "text-right", render: (row) => formatMoney(row.gross_profit, currency) },
        { key: "net_profit", label: "Net profit", className: "text-right", render: (row) => formatMoney(row.net_profit, currency) },
        { key: "margin_percent", label: "Margin", className: "text-right", render: (row) => formatPercent(row.margin_percent) },
        {
          key: "seo_score",
          label: "SEO",
          className: "text-right",
          render: (row) => <span className="font-medium">{row.seo_score}/100</span>,
        },
      ]}
    />
  );
}

function StoreTable({
  rows,
  currency,
}: {
  rows: StorePerformanceRow[];
  currency: ReportingCurrency;
}) {
  if (!rows.length) return <EmptyLedger message="No connected stores are available." />;

  const groupedRows = Array.from(
    rows.reduce((providers, row) => {
      const channels = providers.get(row.provider) ?? new Map<string, StorePerformanceRow[]>();
      const channelRows = channels.get(row.storefront_type) ?? [];
      channelRows.push(row);
      channels.set(row.storefront_type, channelRows);
      providers.set(row.provider, channels);
      return providers;
    }, new Map<string, Map<string, StorePerformanceRow[]>>())
  ).sort(([left], [right]) =>
    providerLabel(left).localeCompare(providerLabel(right), undefined, {
      sensitivity: "base",
    })
  );

  return (
    <div className="space-y-7">
      {groupedRows.map(([provider, channels]) => (
        <section key={provider} className="space-y-4">
          <div className="border-b border-border pb-2">
            <h3 className="text-sm font-semibold text-foreground">
              {providerLabel(provider)}
            </h3>
          </div>
          <div className="space-y-5">
            {Array.from(channels.entries())
              .sort(([left], [right]) =>
                channelLabel(left).localeCompare(channelLabel(right), undefined, {
                  sensitivity: "base",
                })
              )
              .map(([channel, channelRows]) => (
                <div key={channel} className="space-y-2">
                  <div className="flex items-center justify-between px-1">
                    <div className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                      {channelLabel(channel)}
                    </div>
                    <div className="text-xs tabular-nums text-muted-foreground">
                      {channelRows.length} {channelRows.length === 1 ? "store" : "stores"}
                    </div>
                  </div>
                  <StoreRowsTable
                    rows={[...channelRows].sort((left, right) =>
                      cleanStoreDisplayName(left.store_label).localeCompare(
                        cleanStoreDisplayName(right.store_label)
                      )
                    )}
                    currency={currency}
                  />
                </div>
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function StoreRowsTable({
  rows,
  currency,
}: {
  rows: StorePerformanceRow[];
  currency: ReportingCurrency;
}) {
  return (
    <SimpleTable
      className="rounded-md bg-background"
      rows={rows}
      columns={[
        {
          key: "store_label",
          label: "Store",
          className: "min-w-[220px]",
          render: (row) => (
            <div>
              <div className="font-medium">{cleanStoreDisplayName(row.store_label)}</div>
            </div>
          ),
        },
        { key: "order_count", label: "Orders", className: "text-right", render: (row) => row.order_count.toLocaleString() },
        { key: "units", label: "Units", className: "text-right", render: (row) => row.units.toLocaleString() },
        { key: "revenue", label: "Revenue", className: "text-right", render: (row) => formatMoney(row.revenue, currency) },
        { key: "expenses", label: "Expenses", className: "text-right", render: (row) => formatMoney(row.expenses, currency) },
        { key: "net_profit", label: "Net profit", className: "text-right", render: (row) => formatMoney(row.net_profit, currency) },
        {
          key: "unmatched_line_count",
          label: "Unmatched",
          className: "text-right",
          render: (row) => row.unmatched_line_count ? (
            <Badge variant="outline" className="border-amber-500/30 text-amber-600 dark:text-amber-400">
              {row.unmatched_line_count}
            </Badge>
          ) : "0",
        },
      ]}
    />
  );
}

function ExpenseTable({
  rows,
  isAdmin,
  onDelete,
}: {
  rows: ExpenseRecord[];
  isAdmin: boolean;
  onDelete: (expense: ExpenseRecord) => Promise<void>;
}) {
  if (!rows.length) return <EmptyLedger message="No expenses were recorded in this period." />;
  return (
    <SimpleTable
      className="rounded-md bg-background"
      rows={rows}
      columns={[
        { key: "incurred_on", label: "Date", render: (row) => new Date(row.incurred_on).toLocaleDateString() },
        { key: "category", label: "Category", className: "capitalize", render: (row) => row.category.replaceAll("_", " ") },
        {
          key: "scope",
          label: "Attribution",
          render: (row) =>
            row.product_title ??
            (row.store_label ? cleanStoreDisplayName(row.store_label) : "Organization"),
        },
        { key: "source", label: "Source", className: "capitalize" },
        { key: "note", label: "Note", className: "max-w-[280px] truncate text-muted-foreground" },
        { key: "amount", label: "Amount", className: "text-right", render: (row) => formatMoney(row.amount, row.currency as ReportingCurrency) },
        {
          key: "actions",
          label: "",
          className: "w-[90px] text-right",
          render: (row) =>
            isAdmin && row.source === "manual" ? (
              <Button variant="ghost" size="sm" onClick={() => void onDelete(row)}>Delete</Button>
            ) : null,
        },
      ]}
    />
  );
}

function SeoTable({ rows }: { rows: SeoPerformanceRow[] }) {
  if (!rows.length) return <EmptyLedger message="No listings are available in this scope." />;
  return (
    <SimpleTable
      className="rounded-md bg-background"
      rows={rows}
      columns={[
        {
          key: "title",
          label: "Listing",
          className: "min-w-[240px]",
          render: (row) => (
            <div>
              <a href={`/products/${row.product_id}`} className="font-medium hover:text-primary">{row.title}</a>
              <div className="mt-1 text-xs text-muted-foreground">
                {cleanStoreDisplayName(row.store_label)}
              </div>
            </div>
          ),
        },
        {
          key: "score",
          label: "Score",
          className: "w-[110px]",
          render: (row) => (
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-12 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary" style={{ width: `${row.score}%` }} />
              </div>
              <span className="font-medium">{row.score}</span>
            </div>
          ),
        },
        { key: "title_length", label: "Title", className: "text-right", render: (row) => `${row.title_length} chars` },
        { key: "tag_count", label: "Tags", className: "text-right", render: (row) => `${row.tag_count}/13` },
        {
          key: "issues",
          label: "Opportunities",
          className: "min-w-[300px]",
          render: (row) => (
            <div className="flex flex-wrap gap-1.5">
              {row.issues.length ? row.issues.map((issue) => (
                <Badge key={issue} variant="outline" className="font-normal text-muted-foreground">{issue}</Badge>
              )) : <span className="text-muted-foreground">No rule-based issues</span>}
            </div>
          ),
        },
      ]}
    />
  );
}

function UnmatchedTable({
  rows,
  currency,
  isAdmin,
  onMap,
}: {
  rows: UnmatchedOrderLine[];
  currency: ReportingCurrency;
  isAdmin: boolean;
  onMap: (line: UnmatchedOrderLine) => void;
}) {
  if (!rows.length) return <EmptyLedger message="No unmatched sales in this period." />;
  return (
    <SimpleTable
      className="rounded-md bg-background"
      rows={rows}
      columns={[
        { key: "order_display_id", label: "Order" },
        {
          key: "title",
          label: "Provider item",
          className: "min-w-[260px]",
          render: (row) => (
            <div>
              <div className="font-medium">{row.title}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {row.sku ?? "No SKU"} · {cleanStoreDisplayName(row.store_label)}
              </div>
            </div>
          ),
        },
        { key: "quantity", label: "Qty", className: "text-right" },
        { key: "revenue_amount", label: "Revenue", className: "text-right", render: (row) => formatMoney(row.revenue_amount, (row.currency as ReportingCurrency) || currency) },
        {
          key: "actions",
          label: "",
          className: "w-[140px] text-right",
          render: (row) =>
            isAdmin ? (
              <Button variant="outline" size="sm" onClick={() => onMap(row)}>
                <Link2 className="mr-2 h-3.5 w-3.5" /> Map product
              </Button>
            ) : null,
        },
      ]}
    />
  );
}

function EmptyLedger({ message }: { message: string }) {
  return (
    <div className="flex min-h-36 items-center justify-center border border-dashed border-border px-6 text-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}
