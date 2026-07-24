import { LoaderCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export function AIFieldRegenerateButton({
  label,
  loading,
  disabled,
  onClick,
  fillHeight = false,
  inline = false,
  className
}: {
  label: string;
  loading: boolean;
  disabled: boolean;
  onClick: () => void;
  fillHeight?: boolean;
  inline?: boolean;
  className?: string;
}) {
  const largeIcon = fillHeight && !inline;

  return (
    <button
      type="button"
      aria-label={loading ? `Regenerating ${label} with Vel` : `Regenerate ${label} with Vel`}
      title={loading ? `Regenerating ${label} with Vel` : `Regenerate ${label} with Vel`}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "absolute z-10 inline-flex items-center justify-center text-primary transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50",
        inline
          ? "static h-8 w-8 rounded-md border border-primary/30 bg-background/95 hover:border-primary/50 hover:bg-primary/10"
          : fillHeight
            ? "inset-y-0 right-0 w-14 rounded-l-none rounded-r-md border border-border bg-muted/70 hover:border-border hover:bg-muted"
            : "right-2 top-2 h-8 w-8 rounded-md border border-primary/30 bg-background/95 hover:border-primary/50 hover:bg-primary/10",
        className
      )}
    >
      {loading ? (
        <LoaderCircle
          className={cn(largeIcon ? "h-5 w-5" : "h-3.5 w-3.5", "animate-spin")}
          aria-hidden="true"
        />
      ) : (
        <Sparkles
          className={largeIcon ? "h-5 w-5" : "h-3.5 w-3.5"}
          aria-hidden="true"
        />
      )}
    </button>
  );
}
