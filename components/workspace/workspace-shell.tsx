"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useAppSessionContext } from "@/components/auth/app-session-context";
import { buildWorkspacePageCacheScopeKey } from "@/lib/workspace-page-cache";
import { navItems } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import { StoreSwitcher } from "@/components/workspace/store-switcher";
import { StoreContextProvider } from "@/components/workspace/store-context";
import { OrganizationSidebarCard } from "@/components/workspace/organization-sidebar-card";

function isWorkspaceNavItemActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function WorkspaceShellInner({
  children,
  clerkEnabled
}: {
  children: React.ReactNode;
  clerkEnabled: boolean;
}) {
  const pathname = usePathname() ?? "/dashboard";
  const { sessionContext } = useAppSessionContext();
  const isAdmin = sessionContext.membership?.role === "admin";
  const visibleNavItems = navItems.filter((item) => item.href !== "/settings" || isAdmin);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-[226px] border-r border-border/80 bg-card md:flex md:flex-col">
        <div className="border-b border-border/80 p-3">
          <Link
            href="/dashboard"
            className="mb-4 flex h-9 items-center gap-2.5 text-[15px] font-semibold text-foreground"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary text-xs font-bold text-primary-foreground">
              V
            </span>
            Velora
          </Link>

          <div className="rounded-md border border-border bg-background/55 p-3">
            <div className="mb-3 text-sm font-medium text-foreground">
              {sessionContext.organization?.name ?? "Velora"}
            </div>
            <StoreSwitcher />
          </div>
        </div>
        <nav className="flex-1 px-2 py-3">
          {visibleNavItems.map((item) => {
            const Icon = item.icon;
            const active = isWorkspaceNavItemActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "mb-1 flex h-9 items-center justify-between rounded-md px-3 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground",
                  active && "bg-muted text-foreground"
                )}
              >
                <span className="flex items-center gap-3">
                  <Icon className="h-4 w-4" />
                  {item.label}
                </span>
                {active ? <ChevronRight className="h-4 w-4" /> : null}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-border/80 p-3">
          <OrganizationSidebarCard clerkEnabled={clerkEnabled} sessionContext={sessionContext} />
        </div>
      </aside>

      <div className="md:pl-[226px]">
        <main className="mx-auto max-w-[1400px] px-4 py-4">{children}</main>
      </div>
    </div>
  );
}

export function WorkspaceShell({
  children,
  clerkEnabled,
  initialSelectedStoreId = null
}: {
  children: React.ReactNode;
  clerkEnabled: boolean;
  initialSelectedStoreId?: string | null;
}) {
  const { sessionContext } = useAppSessionContext();
  const workspaceScopeKey = buildWorkspacePageCacheScopeKey({
    organizationId: sessionContext.organization?.id ?? null,
    userId: sessionContext.user.id
  });

  return (
    <StoreContextProvider
      key={workspaceScopeKey}
      initialSelectedStoreId={initialSelectedStoreId}
    >
      <WorkspaceShellInner clerkEnabled={clerkEnabled}>{children}</WorkspaceShellInner>
    </StoreContextProvider>
  );
}
