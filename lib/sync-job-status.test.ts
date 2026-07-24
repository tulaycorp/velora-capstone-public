import assert from "node:assert/strict";
import test from "node:test";

import {
  getLastSuccessfulOrderSyncAt,
  getLatestSyncJobActivityAt,
  getOrderSyncOutcomeCounts,
  isSyncJobActiveStatus,
  ORDER_SYNC_AUTO_STALE_AFTER_MS,
  pollSyncJobUntilSettled,
  shouldAutoStartSync
} from "./sync-job-status.ts";

test("isSyncJobActiveStatus recognizes legacy and leased lifecycle active states", () => {
  assert.equal(isSyncJobActiveStatus("pending"), true);
  assert.equal(isSyncJobActiveStatus("queued"), true);
  assert.equal(isSyncJobActiveStatus("leased"), true);
  assert.equal(isSyncJobActiveStatus("running"), true);
  assert.equal(isSyncJobActiveStatus("completed"), false);
  assert.equal(isSyncJobActiveStatus("failed"), false);
});

test("getLatestSyncJobActivityAt prefers completed then updated timestamps", () => {
  assert.equal(
    getLatestSyncJobActivityAt({
      status: "completed",
      created_at: "2026-06-21T10:00:00.000Z",
      updated_at: "2026-06-21T10:01:00.000Z",
      started_at: "2026-06-21T10:02:00.000Z",
      completed_at: "2026-06-21T10:03:00.000Z"
    }),
    "2026-06-21T10:03:00.000Z"
  );
});

test("order sync helpers expose bounded counts and prior successful freshness", () => {
  const partialJob = {
    status: "partial",
    completed_at: "2026-07-16T12:00:00.000Z",
    result_json: {
      last_successful_at: "2026-07-15T09:00:00.000Z",
      orders: {
        fetched: 7,
        inserted: 3,
        updated: 2,
        skipped: 1,
        failed: 1
      }
    }
  };

  assert.deepEqual(getOrderSyncOutcomeCounts(partialJob), {
    fetched: 7,
    inserted: 3,
    updated: 2,
    skipped: 1,
    failed: 1
  });
  assert.equal(getLastSuccessfulOrderSyncAt(partialJob), "2026-07-15T09:00:00.000Z");
  assert.equal(
    getLastSuccessfulOrderSyncAt({
      status: "completed",
      completed_at: "2026-07-16T12:00:00.000Z"
    }),
    "2026-07-16T12:00:00.000Z"
  );
});

test("shouldAutoStartSync uses a five-hour automatic sync cooldown", () => {
  assert.equal(ORDER_SYNC_AUTO_STALE_AFTER_MS, 5 * 60 * 60 * 1000);
  assert.equal(shouldAutoStartSync(null), true);

  const completedJob = {
    status: "completed",
    completed_at: "2026-06-21T10:00:00.000Z",
    created_at: "2026-06-21T10:00:00.000Z"
  };

  assert.equal(
    shouldAutoStartSync(
      completedJob,
      {
        now: () => Date.parse("2026-06-21T14:59:59.000Z")
      }
    ),
    false
  );
  assert.equal(
    shouldAutoStartSync(
      completedJob,
      {
        now: () => Date.parse("2026-06-21T15:00:00.000Z")
      }
    ),
    true
  );
});

test("shouldAutoStartSync does not auto-retry recent failed jobs or active jobs", () => {
  assert.equal(
    shouldAutoStartSync(
      {
        status: "failed",
        completed_at: "2026-06-21T10:00:00.000Z",
        created_at: "2026-06-21T09:59:00.000Z"
      },
      {
        now: () => Date.parse("2026-06-21T10:01:00.000Z")
      }
    ),
    false
  );
  assert.equal(
    shouldAutoStartSync(
      {
        status: "running",
        started_at: "2026-06-21T10:00:00.000Z",
        created_at: "2026-06-21T10:00:00.000Z"
      },
      {
        now: () => Date.parse("2026-06-21T10:05:00.000Z")
      }
    ),
    false
  );
});

test("pollSyncJobUntilSettled keeps polling until the sync job settles", async () => {
  const statuses = ["pending", "running", "completed"];
  let fetchCount = 0;
  let now = 0;

  const result = await pollSyncJobUntilSettled({
    jobId: "sync-job-1",
    intervalMs: 1000,
    timeoutMs: 5000,
    fetchJob: async () => {
      const status = statuses[Math.min(fetchCount, statuses.length - 1)];
      fetchCount += 1;
      return {
        id: "sync-job-1",
        status
      };
    },
    wait: async (milliseconds) => {
      now += milliseconds;
    },
    now: () => now
  });

  assert.equal(result.job?.status, "completed");
  assert.equal(result.timedOut, false);
  assert.equal(fetchCount, statuses.length);
});

test("pollSyncJobUntilSettled reports timeout for jobs that never settle", async () => {
  let now = 0;
  let fetchCount = 0;

  const result = await pollSyncJobUntilSettled({
    jobId: "sync-job-2",
    intervalMs: 1000,
    timeoutMs: 2500,
    fetchJob: async () => {
      fetchCount += 1;
      return {
        id: "sync-job-2",
        status: "running"
      };
    },
    wait: async (milliseconds) => {
      now += milliseconds;
    },
    now: () => now
  });

  assert.equal(result.job?.status, "running");
  assert.equal(result.timedOut, true);
  assert.ok(fetchCount >= 1);
});
