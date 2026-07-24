import assert from "node:assert/strict";
import test from "node:test";

import {
  buildWorkspacePageCacheScopeKey,
  clearWorkspacePageCache,
  hasWorkspacePageCache,
  loadWorkspacePageResource,
  readWorkspacePageCache,
  writeWorkspacePageCache
} from "./workspace-page-cache.ts";

const tulayScope = {
  organizationId: "org-tulay",
  userId: "user-angelo"
};

const otherScope = {
  organizationId: "org-other",
  userId: "user-angelo"
};

test("workspace page cache stores and reads values by key and scope", () => {
  const cachedValue = { count: 3 };

  writeWorkspacePageCache("workspace:dashboard", cachedValue, {
    scope: tulayScope
  });

  assert.equal(
    hasWorkspacePageCache("workspace:dashboard", {
      scope: tulayScope
    }),
    true
  );
  assert.equal(
    readWorkspacePageCache("workspace:dashboard", {
      scope: tulayScope
    }),
    cachedValue
  );
  clearWorkspacePageCache();
});

test("workspace page cache isolates entries by workspace scope", () => {
  writeWorkspacePageCache("workspace:products", ["product-1"], {
    scope: tulayScope
  });
  writeWorkspacePageCache("workspace:products", ["product-2"], {
    scope: otherScope
  });

  assert.deepEqual(
    readWorkspacePageCache("workspace:products", {
      scope: tulayScope
    }),
    ["product-1"]
  );
  assert.deepEqual(
    readWorkspacePageCache("workspace:products", {
      scope: otherScope
    }),
    ["product-2"]
  );
  clearWorkspacePageCache();
});

test("workspace page cache does not reuse expired entries", () => {
  writeWorkspacePageCache("workspace:analytics", { scope: "all" }, {
    now: () => 1_000,
    scope: tulayScope
  });

  assert.equal(
    readWorkspacePageCache("workspace:analytics", {
      maxAgeMs: 1_500,
      now: () => 2_000,
      scope: tulayScope
    })?.scope,
    "all"
  );
  assert.equal(
    readWorkspacePageCache("workspace:analytics", {
      maxAgeMs: 1_500,
      now: () => 2_600,
      scope: tulayScope
    }),
    undefined
  );
  assert.equal(
    hasWorkspacePageCache("workspace:analytics", {
      maxAgeMs: 1_500,
      now: () => 2_600,
      scope: tulayScope
    }),
    false
  );
  clearWorkspacePageCache();
});

test("workspace page cache clears individual keys, scopes, and the full cache", () => {
  writeWorkspacePageCache("workspace:analytics", { scope: "all" }, {
    scope: tulayScope
  });
  writeWorkspacePageCache("workspace:analytics", { scope: "other" }, {
    scope: otherScope
  });
  writeWorkspacePageCache("workspace:blueprints", { total: 2 }, {
    scope: tulayScope
  });

  clearWorkspacePageCache({
    key: "workspace:analytics",
    scope: tulayScope
  });
  assert.equal(
    hasWorkspacePageCache("workspace:analytics", {
      scope: tulayScope
    }),
    false
  );
  assert.deepEqual(
    readWorkspacePageCache("workspace:analytics", {
      scope: otherScope
    }),
    { scope: "other" }
  );

  clearWorkspacePageCache({
    scope: otherScope
  });
  assert.equal(
    hasWorkspacePageCache("workspace:analytics", {
      scope: otherScope
    }),
    false
  );
  assert.deepEqual(
    readWorkspacePageCache("workspace:blueprints", {
      scope: tulayScope
    }),
    { total: 2 }
  );

  clearWorkspacePageCache();
  assert.equal(
    hasWorkspacePageCache("workspace:blueprints", {
      scope: tulayScope
    }),
    false
  );
});

test("workspace page cache clears matching prefixes inside one scope", () => {
  writeWorkspacePageCache("workspace:orders:page:1", ["order-1"], {
    scope: tulayScope
  });
  writeWorkspacePageCache("workspace:orders:page:2", ["order-2"], {
    scope: tulayScope
  });
  writeWorkspacePageCache("workspace:orders:page:1", ["other-order"], {
    scope: otherScope
  });
  writeWorkspacePageCache("workspace:products", ["product-1"], {
    scope: tulayScope
  });

  clearWorkspacePageCache({
    keyPrefix: "workspace:orders:",
    scope: tulayScope
  });

  assert.equal(
    hasWorkspacePageCache("workspace:orders:page:1", { scope: tulayScope }),
    false
  );
  assert.equal(
    hasWorkspacePageCache("workspace:orders:page:2", { scope: tulayScope }),
    false
  );
  assert.equal(
    hasWorkspacePageCache("workspace:orders:page:1", { scope: otherScope }),
    true
  );
  assert.equal(
    hasWorkspacePageCache("workspace:products", { scope: tulayScope }),
    true
  );
  clearWorkspacePageCache();
});

test("workspace page resource loading deduplicates concurrent scoped requests", async () => {
  let loadCount = 0;
  let release: ((value: string[]) => void) | undefined;
  const loader = () => {
    loadCount += 1;
    return new Promise<string[]>((resolve) => {
      release = resolve;
    });
  };

  const first = loadWorkspacePageResource(
    "workspace:analytics:all",
    tulayScope,
    loader
  );
  const second = loadWorkspacePageResource(
    "workspace:analytics:all",
    tulayScope,
    loader
  );

  assert.equal(loadCount, 1);
  assert.equal(first, second);
  release?.(["complete"]);
  assert.deepEqual(await first, ["complete"]);

  await loadWorkspacePageResource(
    "workspace:analytics:all",
    tulayScope,
    async () => {
      loadCount += 1;
      return ["next"];
    }
  );
  assert.equal(loadCount, 2);
});

test("prefix invalidation prevents a post-mutation load from joining stale work", async () => {
  let loadCount = 0;
  let releaseFirst: ((value: string[]) => void) | undefined;
  const first = loadWorkspacePageResource(
    "workspace:orders:page=1",
    tulayScope,
    () => {
      loadCount += 1;
      return new Promise<string[]>((resolve) => {
        releaseFirst = resolve;
      });
    }
  );

  clearWorkspacePageCache({
    keyPrefix: "workspace:orders:",
    scope: tulayScope
  });
  const second = loadWorkspacePageResource(
    "workspace:orders:page=1",
    tulayScope,
    async () => {
      loadCount += 1;
      return ["fresh"];
    }
  );

  assert.equal(loadCount, 2);
  assert.deepEqual(await second, ["fresh"]);
  releaseFirst?.(["stale"]);
  assert.deepEqual(await first, ["stale"]);
  clearWorkspacePageCache();
});

test("workspace page cache scope keys are stable and organization-aware", () => {
  assert.equal(
    buildWorkspacePageCacheScopeKey(tulayScope),
    "org:org-tulay|user:user-angelo"
  );
  assert.equal(
    buildWorkspacePageCacheScopeKey({
      organizationId: null,
      userId: "user-angelo"
    }),
    "org:none|user:user-angelo"
  );
});
