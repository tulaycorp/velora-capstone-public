import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";

export function PageHeader(props: {
  title: React.ReactNode;
  description?: string;
  action?: React.ReactNode;
  preserveActionSpace?: boolean;
}) {
  const { title, action, preserveActionSpace = false } = props;
  const showActionSlot = Boolean(action) || preserveActionSpace;

  return (
    <div className="mb-5 flex flex-col gap-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex min-h-9 min-w-0 max-w-3xl flex-1 items-end">
          <h1 className="min-w-0 w-full overflow-hidden text-2xl font-semibold tracking-normal text-foreground">
            {title}
          </h1>
        </div>
        {showActionSlot ? (
          <div
            aria-hidden={action ? undefined : true}
            className={cn(
              "shrink-0",
              !action && "h-9 w-32 pointer-events-none opacity-0"
            )}
          >
            {action ?? <div className="h-9 w-32" />}
          </div>
        ) : null}
      </div>
      <Separator />
    </div>
  );
}
