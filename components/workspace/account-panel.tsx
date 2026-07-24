"use client";

import { UserButton, useUser } from "@clerk/nextjs";

function ClerkAccountPanelInner() {
  const { user } = useUser();
  const label =
    user?.primaryEmailAddress?.emailAddress ||
    user?.fullName ||
    "Authenticated user";

  return (
    <div className="rounded-md border border-border bg-background p-3">
      <div className="flex items-center gap-3">
        <UserButton
          appearance={{
            elements: {
              userButtonAvatarBox: "h-9 w-9"
            }
          }}
        />
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">{label}</div>
          <div className="text-xs text-muted-foreground">Signed in</div>
        </div>
      </div>
    </div>
  );
}

export function AccountPanel({ clerkEnabled }: { clerkEnabled: boolean }) {
  if (!clerkEnabled) {
    return (
      <div className="rounded-md border border-border bg-background p-3">
        <div className="text-sm font-medium text-foreground">Preview mode</div>
        <div className="mt-1 text-xs leading-5 text-muted-foreground">
          Full sign-in settings are not enabled in this environment yet.
        </div>
      </div>
    );
  }

  return <ClerkAccountPanelInner />;
}
