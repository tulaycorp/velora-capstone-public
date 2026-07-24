import type { ReactNode } from "react";

export function ProductEditorSection({
  title,
  description,
  children,
  className,
  bodyClassName
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={[
        "min-w-0 max-w-full overflow-hidden border-b border-border bg-card last:border-b-0",
        className
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="flex min-w-0 max-w-full flex-col gap-1 border-b border-border/70 px-5 py-4 sm:px-6">
        <h2 className="text-[15px] font-semibold tracking-normal text-foreground">
          {title}
        </h2>
        {description ? (
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      <div
        className={["min-w-0 max-w-full p-5 sm:p-6", bodyClassName].filter(Boolean).join(" ")}
      >
        {children}
      </div>
    </section>
  );
}

export function ProductEditorRailRow({
  label,
  value
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-start justify-between gap-4 border-b border-border/70 py-3 last:border-b-0">
      <div className="shrink-0 text-xs font-medium text-muted-foreground">
        {label}
      </div>
      <div className="min-w-0 max-w-[210px] break-words text-right text-sm font-medium text-foreground">
        {value}
      </div>
    </div>
  );
}
