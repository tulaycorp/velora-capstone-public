import { Badge } from "@/components/ui/badge";
import { humanizeStatusLabel } from "@/lib/ux-copy";

function statusVariant(value: string) {
  const normalized = value.trim().toLowerCase();
  if (
    normalized.includes("active") ||
    normalized.includes("connected") ||
    normalized.includes("published") ||
    normalized.includes("succeeded") ||
    normalized.includes("ready") ||
    normalized.includes("validated")
  ) {
    return "default";
  }

  if (
    normalized.includes("queued") ||
    normalized.includes("pending") ||
    normalized.includes("review") ||
    normalized.includes("draft") ||
    normalized.includes("created")
  ) {
    return "secondary";
  }

  return "outline";
}

export function StatusBadge({
  value,
  className
}: {
  value: string | null | undefined;
  className?: string;
}) {
  const rawLabel = value && value.trim() ? value : "Unknown";
  const label = humanizeStatusLabel(rawLabel);

  return (
    <Badge
      variant={statusVariant(rawLabel)}
      className={["rounded-md px-2 py-1", className].filter(Boolean).join(" ")}
    >
      {label}
    </Badge>
  );
}
