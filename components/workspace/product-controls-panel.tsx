import { AlertCircle, CheckCircle2, LoaderCircle, Rocket } from "lucide-react";

import { StatusBadge } from "@/components/workspace/status-badge";
import { Button } from "@/components/ui/button";
import type { PublishReadinessField, PublishReadinessItem } from "@/lib/product-publish-readiness";
import { cn } from "@/lib/utils";

type ProductControlsPanelProps = {
  productStatus: string | null | undefined;
  publishingStatus: string | null | undefined;
  metaText: string;
  statusMessage: string;
  submittedMetaText?: string | null;
  readiness: PublishReadinessItem[];
  onReadinessSelect?: (field: PublishReadinessField) => void;
  saveLabel: string;
  onSave: () => void;
  saving: boolean;
  saveDisabled?: boolean;
  publishLabel: string;
  onPublish: () => void;
  publishing: boolean;
  publishDisabled: boolean;
  errorMessage?: string | null;
  errorDetail?: string | null;
};

export function ProductControlsPanel({
  productStatus,
  publishingStatus,
  metaText,
  statusMessage,
  submittedMetaText = null,
  readiness,
  onReadinessSelect,
  saveLabel,
  onSave,
  saving,
  saveDisabled = false,
  publishLabel,
  onPublish,
  publishing,
  publishDisabled,
  errorMessage,
  errorDetail
}: ProductControlsPanelProps) {
  return (
    <div className="border-b border-border bg-background/35 px-5 py-4">
      <div className="space-y-4">
        <div>
          <div className="text-sm font-semibold text-foreground">Product controls</div>
          <div className="mt-1 text-xs text-muted-foreground">{metaText}</div>
          {submittedMetaText ? (
            <div className="mt-1 text-xs text-muted-foreground">{submittedMetaText}</div>
          ) : null}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-border bg-background px-3 py-2.5">
            <div className="text-xs text-muted-foreground">Product</div>
            <div className="mt-2">
              <StatusBadge value={productStatus} />
            </div>
          </div>
          <div className="rounded-md border border-border bg-background px-3 py-2.5">
            <div className="text-xs text-muted-foreground">Send to store</div>
            <div className="mt-2">
              <StatusBadge value={publishingStatus} />
            </div>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          <Button id="publish-save" onClick={onSave} disabled={saveDisabled || saving}>
            {saving ? <LoaderCircle className="animate-spin" /> : null}
            {saving ? "Saving..." : saveLabel}
          </Button>
          <Button
            variant="outline"
            onClick={onPublish}
            disabled={publishDisabled}
          >
            {publishing ? <LoaderCircle className="animate-spin" /> : <Rocket />}
            {publishing ? `Sending...` : publishLabel}
          </Button>
        </div>

        <div aria-live="polite" className="text-sm leading-6 text-muted-foreground">
          {statusMessage}
        </div>

        {errorMessage || errorDetail ? (
          <div
            role="alert"
            className="flex gap-2.5 rounded-md border border-destructive/35 bg-destructive/10 px-3 py-2.5 text-destructive"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div className="min-w-0 text-sm leading-5">
              <div className="font-medium">{errorMessage || "Send failed"}</div>
              {errorDetail ? (
                <div className="mt-1 break-words text-xs text-destructive/85">{errorDetail}</div>
              ) : null}
            </div>
          </div>
        ) : null}

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          {readiness.map((item) => {
            const interactive = !item.complete && Boolean(onReadinessSelect);
            const content = (
              <>
                {item.complete ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
                ) : (
                  <AlertCircle className="h-4 w-4 shrink-0 text-muted-foreground" />
                )}
                <span>{item.label}</span>
              </>
            );
            const className = cn(
              "flex w-full items-center gap-2 rounded-md border px-3 py-2 text-left text-sm",
              item.complete
                ? "border-border bg-background text-foreground"
                : "border-border/70 bg-background text-muted-foreground",
              interactive && "transition-colors hover:border-primary/40 hover:text-foreground"
            );

            return interactive ? (
              <button
                key={item.field}
                type="button"
                className={className}
                onClick={() => onReadinessSelect?.(item.field)}
              >
                {content}
              </button>
            ) : (
              <div
                key={item.field}
                className={className}
              >
                {content}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
