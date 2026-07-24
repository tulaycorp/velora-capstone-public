"use client";

import { useState } from "react";
import { useClerk } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { ChevronDown, LoaderCircle, LogOut, Settings } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { type SessionContext } from "@/lib/backend-api";
import { cn } from "@/lib/utils";

const ACCOUNT_SETTINGS_PATH = "/account";

export function OrganizationSidebarCard({
  clerkEnabled,
  sessionContext
}: {
  clerkEnabled: boolean;
  sessionContext: SessionContext;
}) {
  if (!sessionContext.organization || !sessionContext.membership) {
    return null;
  }

  const emailLabel = sessionContext.user.email ?? sessionContext.user.display_name;

  if (!clerkEnabled) {
    return (
      <div className="min-w-0 rounded-md border border-border bg-background/55 px-3 py-2.5">
        <div className="truncate text-sm font-medium text-foreground">Local workspace mode</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">{emailLabel}</div>
      </div>
    );
  }

  return <ClerkOrganizationSidebarCard emailLabel={emailLabel} />;
}

function ClerkOrganizationSidebarCard({ emailLabel }: { emailLabel: string }) {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const { signOut } = useClerk();

  async function handleSignOut() {
    try {
      setIsSigningOut(true);
      setMenuOpen(true);
      await signOut({ redirectUrl: "/sign-in" });
    } catch {
      setIsSigningOut(false);
    }
  }

  return (
    <DropdownMenu open={menuOpen || isSigningOut} onOpenChange={setMenuOpen}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Open account menu"
          aria-busy={isSigningOut}
          disabled={isSigningOut}
          className="flex w-full min-w-0 items-center justify-between rounded-md border border-border bg-background/55 px-3 py-2.5 text-left text-sm font-medium text-foreground transition-colors hover:bg-muted/20 disabled:cursor-wait"
        >
          <span className="min-w-0 flex-1 truncate">{emailLabel}</span>
          <div className="ml-3 flex shrink-0 items-center gap-2">
            {isSigningOut ? <LoaderCircle className="size-4 animate-spin text-primary" /> : null}
            <ChevronDown
              className={cn(
                "size-4 text-muted-foreground transition-transform duration-150",
                (menuOpen || isSigningOut) && "rotate-180"
              )}
            />
          </div>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={8}
        className="w-64 rounded-md border-border/80 bg-card p-1.5"
      >
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-2">
            <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Signed in as
            </div>
            <div className="mt-1 break-all text-sm font-medium text-foreground">{emailLabel}</div>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              setMenuOpen(false);
              router.push(ACCOUNT_SETTINGS_PATH);
            }}
          >
            <Settings className="text-muted-foreground" />
            User settings
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={isSigningOut}
            onSelect={(event) => {
              event.preventDefault();
              void handleSignOut();
            }}
          >
            {isSigningOut ? (
              <LoaderCircle className="animate-spin text-primary" />
            ) : (
              <LogOut className="text-muted-foreground" />
            )}
            {isSigningOut ? "Logging out..." : "Log out"}
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
