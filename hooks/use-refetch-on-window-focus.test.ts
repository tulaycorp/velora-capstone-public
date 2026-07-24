import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_WINDOW_FOCUS_REFETCH_INTERVAL_MS,
  shouldRunWindowFocusRefetch
} from "./use-refetch-on-window-focus.ts";

test("focus refetch waits for the default interval", () => {
  assert.equal(DEFAULT_WINDOW_FOCUS_REFETCH_INTERVAL_MS, 60_000);
  assert.equal(
    shouldRunWindowFocusRefetch({
      enabled: true,
      isVisible: true,
      lastRunAt: 1_000,
      minIntervalMs: 60_000,
      now: 60_999,
      resourceNeedsRefresh: true
    }),
    false
  );
  assert.equal(
    shouldRunWindowFocusRefetch({
      enabled: true,
      isVisible: true,
      lastRunAt: 1_000,
      minIntervalMs: 60_000,
      now: 61_000,
      resourceNeedsRefresh: true
    }),
    true
  );
});

test("focus refetch skips fresh, hidden, and disabled resources", () => {
  const base = {
    enabled: true,
    isVisible: true,
    lastRunAt: 0,
    minIntervalMs: 60_000,
    now: 60_000,
    resourceNeedsRefresh: true
  };

  assert.equal(
    shouldRunWindowFocusRefetch({ ...base, resourceNeedsRefresh: false }),
    false
  );
  assert.equal(
    shouldRunWindowFocusRefetch({ ...base, isVisible: false }),
    false
  );
  assert.equal(
    shouldRunWindowFocusRefetch({ ...base, enabled: false }),
    false
  );
});
