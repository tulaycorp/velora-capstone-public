"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type SetStateAction } from "react";
import { useAppSessionContext } from "@/components/auth/app-session-context";
import {
  DEFAULT_WORKSPACE_PAGE_CACHE_MAX_AGE_MS,
  clearWorkspacePageCache,
  hasWorkspacePageCache,
  loadWorkspacePageResource,
  readWorkspacePageCache,
  writeWorkspacePageCache
} from "@/lib/workspace-page-cache";

export type CachedWorkspaceLoadMode = "blocking" | "background";
export type CachedWorkspaceLoadPolicy = "force" | "if-stale";

export function useCachedWorkspaceResource<T>({
  cacheKey,
  loadResource,
  staleAfterMs = DEFAULT_WORKSPACE_PAGE_CACHE_MAX_AGE_MS,
  keepPreviousData = false
}: {
  cacheKey: string;
  loadResource: () => Promise<T>;
  staleAfterMs?: number;
  keepPreviousData?: boolean;
}) {
  const { sessionContext } = useAppSessionContext();
  const cacheScope = useMemo(
    () => ({
      organizationId: sessionContext.organization?.id ?? null,
      userId: sessionContext.user.id
    }),
    [sessionContext.organization?.id, sessionContext.user.id]
  );
  const [data, setDataState] = useState<T | undefined>(() =>
    readWorkspacePageCache<T>(cacheKey, {
      maxAgeMs: staleAfterMs,
      scope: cacheScope
    })
  );
  const [loading, setLoading] = useState(() => data === undefined);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeRequestIdRef = useRef(0);
  const cacheKeyRef = useRef(cacheKey);
  const cacheScopeRef = useRef(cacheScope);
  const dataRef = useRef<T | undefined>(data);

  const setData = useCallback((nextValue: SetStateAction<T | undefined>) => {
    setDataState((current) => {
      const nextData =
        typeof nextValue === "function"
          ? (nextValue as (current: T | undefined) => T | undefined)(current)
          : nextValue;

      dataRef.current = nextData;
      if (nextData === undefined) {
        clearWorkspacePageCache({
          key: cacheKeyRef.current,
          scope: cacheScopeRef.current
        });
      } else {
        writeWorkspacePageCache(cacheKeyRef.current, nextData, {
          scope: cacheScopeRef.current
        });
      }

      return nextData;
    });
  }, []);

  const load = useCallback(
    async (
      mode: CachedWorkspaceLoadMode = "blocking",
      policy: CachedWorkspaceLoadPolicy = "force"
    ) => {
      if (
        policy === "if-stale" &&
        hasWorkspacePageCache(cacheKey, {
          maxAgeMs: staleAfterMs,
          scope: cacheScope
        })
      ) {
        return dataRef.current;
      }

      const requestId = activeRequestIdRef.current + 1;
      activeRequestIdRef.current = requestId;

      if (mode === "blocking") {
        setLoading(true);
        setError(null);
      } else {
        setRefreshing(true);
      }

      try {
        const nextData = await loadWorkspacePageResource(
          cacheKey,
          cacheScope,
          loadResource
        );
        if (activeRequestIdRef.current !== requestId) {
          return undefined;
        }

        dataRef.current = nextData;
        writeWorkspacePageCache(cacheKey, nextData, {
          scope: cacheScope
        });
        setDataState(nextData);
        setError(null);
        return nextData;
      } catch (loadError) {
        if (activeRequestIdRef.current !== requestId) {
          return undefined;
        }

        if (mode === "blocking" || dataRef.current === undefined) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "Unable to load workspace data."
          );
        }
        return undefined;
      } finally {
        if (activeRequestIdRef.current !== requestId) {
          return;
        }

        if (mode === "blocking") {
          setLoading(false);
        } else {
          setRefreshing(false);
        }
      }
    },
    [cacheKey, cacheScope, loadResource, staleAfterMs]
  );

  const isCacheFresh = useCallback(
    () =>
      hasWorkspacePageCache(cacheKey, {
        maxAgeMs: staleAfterMs,
        scope: cacheScope
      }),
    [cacheKey, cacheScope, staleAfterMs]
  );

  useEffect(() => {
    cacheKeyRef.current = cacheKey;
    cacheScopeRef.current = cacheScope;
    const cachedValue = readWorkspacePageCache<T>(cacheKey, {
      maxAgeMs: staleAfterMs,
      scope: cacheScope
    });
    const retainsPreviousData =
      keepPreviousData &&
      cachedValue === undefined &&
      dataRef.current !== undefined;
    if (!retainsPreviousData) {
      dataRef.current = cachedValue;
      setDataState(cachedValue);
    }
    setError(null);
    setLoading(cachedValue === undefined && !retainsPreviousData);
    setRefreshing(retainsPreviousData);

    if (cachedValue === undefined) {
      void load(retainsPreviousData ? "background" : "blocking");
    }
  }, [cacheKey, cacheScope, keepPreviousData, load, staleAfterMs]);

  return {
    data,
    error,
    isCacheFresh,
    load,
    loading,
    refreshing,
    setData
  };
}
