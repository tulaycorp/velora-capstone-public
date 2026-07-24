"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { fetchSessionContext, type SessionContext } from "@/lib/backend-api";
import {
  buildWorkspacePageCacheScopeKey,
  clearWorkspacePageCache
} from "@/lib/workspace-page-cache";

type AppSessionContextValue = {
  sessionContext: SessionContext;
  refreshSessionContext: () => Promise<SessionContext>;
  setSessionContext: (value: SessionContext) => void;
};

const AppSessionContext = createContext<AppSessionContextValue | null>(null);

export function AppSessionContextProvider({
  children,
  initialSessionContext
}: {
  children: React.ReactNode;
  initialSessionContext: SessionContext;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [sessionContext, setSessionContext] = useState(initialSessionContext);
  const currentCacheScopeKey = buildWorkspacePageCacheScopeKey({
    organizationId: sessionContext.organization?.id ?? null,
    userId: sessionContext.user.id
  });
  const previousCacheScopeKeyRef = useRef(currentCacheScopeKey);

  const refreshSessionContext = useCallback(async () => {
    const nextValue = await fetchSessionContext();
    setSessionContext(nextValue);
    return nextValue;
  }, []);

  useEffect(() => {
    if (sessionContext.onboarding_status === "approved") {
      return;
    }

    if (pathname === "/onboarding") {
      return;
    }

    router.replace("/onboarding");
    router.refresh();
  }, [pathname, router, sessionContext.onboarding_status]);

  useEffect(() => {
    if (previousCacheScopeKeyRef.current === currentCacheScopeKey) {
      return;
    }

    clearWorkspacePageCache();
    previousCacheScopeKeyRef.current = currentCacheScopeKey;
  }, [currentCacheScopeKey]);

  return (
    <AppSessionContext.Provider
      value={{
        sessionContext,
        refreshSessionContext,
        setSessionContext
      }}
    >
      {children}
    </AppSessionContext.Provider>
  );
}

export function useAppSessionContext() {
  const context = useContext(AppSessionContext);
  if (!context) {
    throw new Error("useAppSessionContext must be used inside AppSessionContextProvider.");
  }
  return context;
}
