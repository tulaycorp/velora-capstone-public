const ACTIVE_PUBLISHING_STATUSES = new Set(["queued", "leased", "publishing", "pending", "running"]);
const SUCCESS_PUBLISHING_STATUSES = new Set(["succeeded", "published", "ready"]);

export function isPublishingActiveStatus(status: string | null | undefined) {
  return ACTIVE_PUBLISHING_STATUSES.has(String(status ?? "").trim().toLowerCase());
}

export function isPublishingSuccessStatus(status: string | null | undefined) {
  return SUCCESS_PUBLISHING_STATUSES.has(String(status ?? "").trim().toLowerCase());
}

type PublishingRevision = {
  status: string;
  product_revision: number;
};

export function hasPendingStorefrontChanges(
  productRevision: number,
  latestPublishingJob: PublishingRevision | null | undefined
) {
  if (!latestPublishingJob || !isPublishingSuccessStatus(latestPublishingJob.status)) {
    return true;
  }

  return productRevision > latestPublishingJob.product_revision;
}

type PublishingJobLike = {
  status: string;
};

type PollPublishingJobUntilSettledOptions = {
  jobId: string;
  fetchJob: (jobId: string) => Promise<PublishingJobLike>;
  intervalMs?: number;
  timeoutMs?: number;
  wait?: (milliseconds: number) => Promise<void>;
  now?: () => number;
  onStatus?: (status: string) => void;
};

type PollPublishingJobResult = {
  status: string;
  timedOut: boolean;
};

async function defaultWait(milliseconds: number) {
  await new Promise<void>((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

export async function pollPublishingJobUntilSettled(
  options: PollPublishingJobUntilSettledOptions
): Promise<PollPublishingJobResult> {
  const {
    jobId,
    fetchJob,
    intervalMs = 1500,
    timeoutMs = 180000,
    wait = defaultWait,
    now = Date.now,
    onStatus
  } = options;
  const startedAt = now();
  let lastStatus = "queued";

  while (now() - startedAt <= timeoutMs) {
    await wait(intervalMs);
    const job = await fetchJob(jobId);
    lastStatus = job.status;
    onStatus?.(lastStatus);

    if (!isPublishingActiveStatus(lastStatus)) {
      return {
        status: lastStatus,
        timedOut: false
      };
    }
  }

  return {
    status: lastStatus,
    timedOut: true
  };
}
