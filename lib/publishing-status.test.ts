import assert from "node:assert/strict";
import test from "node:test";

import {
  hasPendingStorefrontChanges,
  isPublishingSuccessStatus,
  pollPublishingJobUntilSettled
} from "./publishing-status.ts";

test("tracks saved revisions that still need a storefront send", () => {
  assert.equal(hasPendingStorefrontChanges(7, null), true);
  assert.equal(
    hasPendingStorefrontChanges(7, { status: "succeeded", product_revision: 7 }),
    false
  );
  assert.equal(
    hasPendingStorefrontChanges(8, { status: "succeeded", product_revision: 7 }),
    true
  );
  assert.equal(
    hasPendingStorefrontChanges(7, { status: "failed", product_revision: 7 }),
    true
  );
});

test("isPublishingSuccessStatus recognizes settled success states", () => {
  assert.equal(isPublishingSuccessStatus("succeeded"), true);
  assert.equal(isPublishingSuccessStatus("published"), true);
  assert.equal(isPublishingSuccessStatus("ready"), true);
  assert.equal(isPublishingSuccessStatus("failed"), false);
  assert.equal(isPublishingSuccessStatus("running"), false);
});

test("leased publishing jobs remain active while a worker owns them", async () => {
  const { isPublishingActiveStatus } = await import("./publishing-status.ts");
  assert.equal(isPublishingActiveStatus("leased"), true);
});

test("pollPublishingJobUntilSettled keeps polling until the job actually settles", async () => {
  const statuses = [
    "queued",
    "running",
    "running",
    "running",
    "running",
    "running",
    "running",
    "running",
    "running",
    "succeeded"
  ];
  let fetchCount = 0;
  let now = 0;

  const result = await pollPublishingJobUntilSettled({
    jobId: "job-1",
    intervalMs: 1000,
    timeoutMs: 15000,
    fetchJob: async () => {
      const status = statuses[Math.min(fetchCount, statuses.length - 1)];
      fetchCount += 1;
      return { status };
    },
    wait: async (milliseconds) => {
      now += milliseconds;
    },
    now: () => now,
    onStatus: () => undefined
  });

  assert.equal(result.status, "succeeded");
  assert.equal(result.timedOut, false);
  assert.equal(fetchCount, statuses.length);
});

test("pollPublishingJobUntilSettled reports a timeout when the job never settles", async () => {
  let fetchCount = 0;
  let now = 0;

  const result = await pollPublishingJobUntilSettled({
    jobId: "job-2",
    intervalMs: 1000,
    timeoutMs: 2500,
    fetchJob: async () => {
      fetchCount += 1;
      return { status: "running" };
    },
    wait: async (milliseconds) => {
      now += milliseconds;
    },
    now: () => now
  });

  assert.equal(result.status, "running");
  assert.equal(result.timedOut, true);
  assert.ok(fetchCount >= 1);
});
