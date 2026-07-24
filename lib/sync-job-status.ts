const ACTIVE_SYNC_JOB_STATUSES = new Set(["pending", "queued", "leased", "running"]);
export const ORDER_SYNC_AUTO_STALE_AFTER_MS = 5 * 60 * 60 * 1000;

type SyncJobLike = {
  status: string;
};

type SyncJobTimestampLike = SyncJobLike & {
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  result_json?: Record<string, unknown> | null;
};

export type OrderSyncOutcomeCounts = {
  fetched: number;
  inserted: number;
  updated: number;
  skipped: number;
  failed: number;
};

type PollSyncJobUntilSettledOptions<TJob extends SyncJobLike> = {
  jobId: string;
  fetchJob: (jobId: string) => Promise<TJob>;
  intervalMs?: number;
  timeoutMs?: number;
  wait?: (milliseconds: number) => Promise<void>;
  now?: () => number;
  onJob?: (job: TJob) => void;
};

type PollSyncJobResult<TJob extends SyncJobLike> = {
  job: TJob | null;
  timedOut: boolean;
};

export function isSyncJobActiveStatus(status: string | null | undefined) {
  return ACTIVE_SYNC_JOB_STATUSES.has(String(status ?? "").trim().toLowerCase());
}

export function getLatestSyncJobActivityAt(job: SyncJobTimestampLike | null | undefined) {
  if (!job) {
    return null;
  }

  for (const candidate of [job.completed_at, job.updated_at, job.started_at, job.created_at]) {
    const normalized = String(candidate ?? "").trim();
    if (normalized) {
      return normalized;
    }
  }

  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asCount(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : 0;
}

export function getOrderSyncOutcomeCounts(
  job: SyncJobTimestampLike | null | undefined
): OrderSyncOutcomeCounts | null {
  const orders = asRecord(asRecord(job?.result_json)?.orders);
  if (!orders) {
    return null;
  }

  return {
    fetched: asCount(orders.fetched),
    inserted: asCount(orders.inserted),
    updated: asCount(orders.updated),
    skipped: asCount(orders.skipped),
    failed: asCount(orders.failed)
  };
}

export function getLastSuccessfulOrderSyncAt(
  job: SyncJobTimestampLike | null | undefined
) {
  if (!job) {
    return null;
  }

  const resultTimestamp = String(asRecord(job.result_json)?.last_successful_at ?? "").trim();
  if (resultTimestamp) {
    return resultTimestamp;
  }

  if (job.status === "completed") {
    return getLatestSyncJobActivityAt(job);
  }

  return null;
}

export function shouldAutoStartSync(
  job: SyncJobTimestampLike | null | undefined,
  options?: {
    staleAfterMs?: number;
    now?: () => number;
  }
) {
  if (!job) {
    return true;
  }

  if (isSyncJobActiveStatus(job.status)) {
    return false;
  }

  const staleAfterMs = options?.staleAfterMs ?? ORDER_SYNC_AUTO_STALE_AFTER_MS;
  const now = options?.now ?? Date.now;
  const latestActivityAt = getLatestSyncJobActivityAt(job);
  if (!latestActivityAt) {
    return true;
  }

  const parsed = Date.parse(latestActivityAt);
  if (Number.isNaN(parsed)) {
    return true;
  }

  return now() - parsed >= staleAfterMs;
}

async function defaultWait(milliseconds: number) {
  await new Promise<void>((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

export async function pollSyncJobUntilSettled<TJob extends SyncJobLike>(
  options: PollSyncJobUntilSettledOptions<TJob>
): Promise<PollSyncJobResult<TJob>> {
  const {
    jobId,
    fetchJob,
    intervalMs = 3000,
    timeoutMs = 180000,
    wait = defaultWait,
    now = Date.now,
    onJob
  } = options;
  const startedAt = now();
  let lastJob: TJob | null = null;

  while (now() - startedAt <= timeoutMs) {
    await wait(intervalMs);
    lastJob = await fetchJob(jobId);
    onJob?.(lastJob);

    if (!isSyncJobActiveStatus(lastJob.status)) {
      return {
        job: lastJob,
        timedOut: false
      };
    }
  }

  return {
    job: lastJob,
    timedOut: true
  };
}
