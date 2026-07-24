"use client";

import { OrganizationSwitcher } from "@clerk/nextjs";

export function OrganizationPanel({ clerkEnabled }: { clerkEnabled: boolean }) {
  if (!clerkEnabled) {
    return (
      <div>
        <div className="text-xs text-muted-foreground">Workspace</div>
        <div className="text-sm font-semibold text-foreground">Velora</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">Workspace</div>
      <OrganizationSwitcher
        afterCreateOrganizationUrl="/dashboard"
        afterSelectOrganizationUrl="/dashboard"
        appearance={{
          elements: {
            organizationSwitcherTrigger:
              "flex h-10 w-full items-center justify-between rounded-md border border-border bg-card px-3 text-left text-sm text-foreground hover:bg-muted/60",
            organizationPreviewMainIdentifier: "text-sm font-semibold text-foreground",
            organizationPreviewSecondaryIdentifier: "text-xs text-muted-foreground",
            organizationSwitcherPopoverCard: "border border-border bg-popover text-popover-foreground shadow-2xl"
          }
        }}
      />
    </div>
  );
}
