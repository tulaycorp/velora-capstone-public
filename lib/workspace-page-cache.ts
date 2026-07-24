export const DEFAULT_WORKSPACE_PAGE_CACHE_MAX_AGE_MS = 60_000;

export type WorkspacePageCacheScope = {
  organizationId: string | null;
  userId: string;
};

type WorkspacePageCacheEntry = {
  cachedAt: number;
  scopeKey: string;
  value: unknown;
};

type WorkspacePageCacheReadOptions = {
  maxAgeMs?: number;
  now?: () => number;
  scope: WorkspacePageCacheScope;
};

type WorkspacePageCacheWriteOptions = {
  now?: () => number;
  scope: WorkspacePageCacheScope;
};

type WorkspacePageCacheClearOptions = {
  key?: string;
  keyPrefix?: string;
  scope?: WorkspacePageCacheScope;
};

const workspacePageCache = new Map<string, WorkspacePageCacheEntry>();
const workspacePageRequests = new Map<string, Promise<unknown>>();

function resolveNow(now?: () => number) {
  return now ? now() : Date.now();
}

function buildWorkspacePageCacheEntryKey(key: string, scopeKey: string) {
  return `${scopeKey}::${key}`;
}

function buildWorkspacePageCacheRequestKey(
  key: string,
  scope: WorkspacePageCacheScope
) {
  return buildWorkspacePageCacheEntryKey(
    key,
    buildWorkspacePageCacheScopeKey(scope)
  );
}

function isWorkspacePageCacheEntryExpired(
  entry: WorkspacePageCacheEntry,
  options: WorkspacePageCacheReadOptions
) {
  const maxAgeMs = options.maxAgeMs ?? DEFAULT_WORKSPACE_PAGE_CACHE_MAX_AGE_MS;
  return resolveNow(options.now) - entry.cachedAt > maxAgeMs;
}

export function buildWorkspacePageCacheScopeKey(
  scope: WorkspacePageCacheScope
): string {
  return `org:${scope.organizationId ?? "none"}|user:${scope.userId}`;
}

export function readWorkspacePageCache<T>(
  key: string,
  options: WorkspacePageCacheReadOptions
): T | undefined {
  const scopeKey = buildWorkspacePageCacheScopeKey(options.scope);
  const entryKey = buildWorkspacePageCacheEntryKey(key, scopeKey);
  const entry = workspacePageCache.get(entryKey);

  if (!entry) {
    return undefined;
  }

  if (isWorkspacePageCacheEntryExpired(entry, options)) {
    workspacePageCache.delete(entryKey);
    return undefined;
  }

  return entry.value as T;
}

export function writeWorkspacePageCache<T>(
  key: string,
  value: T,
  options: WorkspacePageCacheWriteOptions
): T {
  const scopeKey = buildWorkspacePageCacheScopeKey(options.scope);
  const entryKey = buildWorkspacePageCacheEntryKey(key, scopeKey);

  workspacePageCache.set(entryKey, {
    cachedAt: resolveNow(options.now),
    scopeKey,
    value
  });

  return value;
}

export function hasWorkspacePageCache(
  key: string,
  options: WorkspacePageCacheReadOptions
): boolean {
  return readWorkspacePageCache(key, options) !== undefined;
}

export function loadWorkspacePageResource<T>(
  key: string,
  scope: WorkspacePageCacheScope,
  loadResource: () => Promise<T>
): Promise<T> {
  const requestKey = buildWorkspacePageCacheRequestKey(key, scope);
  const activeRequest = workspacePageRequests.get(requestKey) as
    | Promise<T>
    | undefined;
  if (activeRequest) {
    return activeRequest;
  }

  const request = loadResource().finally(() => {
    if (workspacePageRequests.get(requestKey) === request) {
      workspacePageRequests.delete(requestKey);
    }
  });
  workspacePageRequests.set(requestKey, request);
  return request;
}

export function clearWorkspacePageCache(
  options?: WorkspacePageCacheClearOptions
) {
  if (!options) {
    workspacePageCache.clear();
    workspacePageRequests.clear();
    return;
  }
  const clearOptions = options;

  const scopeKey = clearOptions.scope
    ? buildWorkspacePageCacheScopeKey(clearOptions.scope)
    : null;

  function matches(entryKey: string) {
    if (clearOptions.key && !entryKey.endsWith(`::${clearOptions.key}`)) {
      return false;
    }

    if (clearOptions.keyPrefix) {
      const key = entryKey.slice(entryKey.indexOf("::") + 2);
      if (!key.startsWith(clearOptions.keyPrefix)) {
        return false;
      }
    }

    if (scopeKey && !entryKey.startsWith(`${scopeKey}::`)) {
      return false;
    }

    return true;
  }

  for (const entryKey of workspacePageCache.keys()) {
    if (matches(entryKey)) {
      workspacePageCache.delete(entryKey);
    }
  }

  for (const requestKey of workspacePageRequests.keys()) {
    if (matches(requestKey)) {
      workspacePageRequests.delete(requestKey);
    }
  }
}
