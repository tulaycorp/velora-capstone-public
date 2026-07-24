"use client";

import { useEffect, useRef } from "react";

type UseRefetchOnWindowFocusOptions = {
  enabled?: boolean;
  minIntervalMs?: number;
  shouldRefetch?: () => boolean;
};

export const DEFAULT_WINDOW_FOCUS_REFETCH_INTERVAL_MS = 60_000;

export function shouldRunWindowFocusRefetch({
  enabled,
  isVisible,
  lastRunAt,
  minIntervalMs,
  now,
  resourceNeedsRefresh
}: {
  enabled: boolean;
  isVisible: boolean;
  lastRunAt: number;
  minIntervalMs: number;
  now: number;
  resourceNeedsRefresh: boolean;
}) {
  return (
    enabled &&
    isVisible &&
    resourceNeedsRefresh &&
    now - lastRunAt >= minIntervalMs
  );
}

export function useRefetchOnWindowFocus(
  refetch: () => Promise<void> | void,
  options: UseRefetchOnWindowFocusOptions = {}
) {
  const {
    enabled = true,
    minIntervalMs = DEFAULT_WINDOW_FOCUS_REFETCH_INTERVAL_MS,
    shouldRefetch
  } = options;
  const inFlightRef = useRef<Promise<void> | null>(null);
  const lastRunAtRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    async function runRefetch() {
      const now = Date.now();
      if (
        !shouldRunWindowFocusRefetch({
          enabled,
          isVisible: document.visibilityState !== "hidden",
          lastRunAt: lastRunAtRef.current,
          minIntervalMs,
          now,
          resourceNeedsRefresh: shouldRefetch ? shouldRefetch() : true
        })
      ) {
        return;
      }

      if (inFlightRef.current) {
        return;
      }

      lastRunAtRef.current = now;
      const activeRequest = Promise.resolve(refetch());
      inFlightRef.current = activeRequest;

      try {
        await activeRequest;
      } finally {
        if (inFlightRef.current === activeRequest) {
          inFlightRef.current = null;
        }
      }
    }

    function handleFocus() {
      void runRefetch();
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        void runRefetch();
      }
    }

    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, minIntervalMs, refetch, shouldRefetch]);
}
