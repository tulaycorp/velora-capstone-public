import { AlertCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export function ResourceLoading({
  title = "Loading workspace data"
}: {
  title?: string;
}) {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-24 w-full rounded-lg" />
      <Skeleton className="h-[320px] w-full rounded-lg" />
      <div className="sr-only">{title}</div>
    </div>
  );
}

export function ResourceError({
  message,
  onRetry
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-6">
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 h-5 w-5 text-destructive" />
          <div>
            <div className="font-medium text-foreground">Unable to load data</div>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{message}</p>
          </div>
        </div>
        {onRetry ? (
          <Button variant="outline" className="w-fit" onClick={onRetry}>
            Try again
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function EmptyState({
  title,
  description,
  action
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-6">
        <div>
          <div className="font-medium text-foreground">{title}</div>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
        </div>
        {action}
      </CardContent>
    </Card>
  );
}

export * from "./page-skeletons";

