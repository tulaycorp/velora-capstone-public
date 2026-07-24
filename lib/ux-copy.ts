const STATUS_LABELS: Record<string, string> = {
  active: "Active",
  approved: "Approved",
  connected: "Connected",
  created: "Saved",
  draft: "Draft",
  failed: "Needs attention",
  needs_credentials: "Needs setup",
  needs_organization: "Needs setup",
  not_created: "Not started",
  not_started: "Not started",
  pending: "Pending",
  published: "Published",
  publishing: "Sending",
  queued: "Queued",
  ready: "Ready",
  rejected: "Declined",
  review: "Needs review",
  running: "Sending",
  submitted: "Submitted",
  succeeded: "Sent",
  validated: "Ready"
};

function titleCaseWords(value: string) {
  return value
    .replace(/[_-]/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function humanizeStatusLabel(value: string | null | undefined) {
  const rawLabel = value?.trim();
  if (!rawLabel) {
    return "Unknown";
  }

  const normalized = rawLabel.toLowerCase();
  return STATUS_LABELS[normalized] ?? titleCaseWords(rawLabel);
}

export function formatQueuedPushMessage(storefrontAction: string) {
  return `Starting your send to ${storefrontAction}.`;
}

export function formatPushStatusMessage(storefrontAction: string, status: string) {
  const normalized = status.trim().toLowerCase();

  if (normalized === "queued" || normalized === "pending") {
    return `Your product is lined up to send to ${storefrontAction}.`;
  }

  if (normalized === "running" || normalized === "publishing") {
    return `Sending your product to ${storefrontAction}.`;
  }

  if (normalized === "succeeded" || normalized === "published" || normalized === "ready") {
    return `Your product was sent to ${storefrontAction}.`;
  }

  if (normalized === "failed" || normalized === "rejected") {
    return `We couldn't send this product to ${storefrontAction}. Try again.`;
  }

  return `${humanizeStatusLabel(status)} for ${storefrontAction}.`;
}

export function formatPushHelperCopy(storefrontAction: string) {
  return `Save your work, then send it to ${storefrontAction} when you're ready.`;
}

export function humanizeApiErrorDetail(detail: string) {
  const normalized = detail.trim();

  if (!normalized) {
    return "Something went wrong. Please try again.";
  }

  if (/^Not authenticated$/i.test(normalized)) {
    return "Please sign in again.";
  }
  if (/Clerk session tokens were received/i.test(normalized)) {
    return "Sign-in is not fully set up in this environment yet.";
  }
  if (/Organization membership is required to access the workspace/i.test(normalized)) {
    return "You need workspace access before you can open this page.";
  }
  if (/Admin access is required/i.test(normalized)) {
    return "Only workspace admins can do that.";
  }
  if (/Organization code was not found/i.test(normalized)) {
    return "That invite code wasn't recognized.";
  }
  if (/pending organization access request/i.test(normalized)) {
    return "Your access request is already waiting for approval.";
  }
  if (/Join request was not found/i.test(normalized)) {
    return "That access request could not be found.";
  }
  if (/Join request has already been reviewed/i.test(normalized)) {
    return "That access request has already been reviewed.";
  }
  if (/That user already belongs to an organization/i.test(normalized)) {
    return "That person already has workspace access.";
  }
  if (/Organization member was not found/i.test(normalized)) {
    return "That member could not be found.";
  }
  if (/Use the leave organization flow to remove yourself/i.test(normalized)) {
    return "Use the leave workspace action instead.";
  }
  if (/Organization membership is required to leave an organization/i.test(normalized)) {
    return "You are not part of a workspace right now.";
  }
  if (/You must transfer organization ownership before leaving the only admin role/i.test(normalized)) {
    return "Add another admin before leaving this workspace.";
  }
  if (/Provider credential not found/i.test(normalized)) {
    return "That saved key could not be found.";
  }
  if (/Provider credential is still referenced/i.test(normalized)) {
    return "This saved key is still connected to active stores or products.";
  }
  if (/Provider store connection not found/i.test(normalized)) {
    return "That connected store could not be found.";
  }
  if (/Provider store connection is still referenced/i.test(normalized)) {
    return "This store is still being used by products or blueprints.";
  }
  if (/Credentials for '([^']+)' are incomplete/i.test(normalized)) {
    const match = normalized.match(/Credentials for '([^']+)' are incomplete/i);
    const provider = match?.[1];
    if (provider) {
      return `Finish setting up ${titleCaseWords(provider)} before continuing.`;
    }
    return "Finish setup before continuing.";
  }
  if (/Blueprint not found/i.test(normalized)) {
    return "That blueprint could not be found.";
  }
  if (/Blueprint still has product drafts/i.test(normalized)) {
    return "This blueprint is still being used by saved products.";
  }
  if (/Blueprint reference must be validated before publishing/i.test(normalized)) {
    return "Refresh the blueprint details before sending this product.";
  }
  if (/Design asset not found/i.test(normalized)) {
    return "That artwork file could not be found.";
  }
  if (/Product draft not found/i.test(normalized)) {
    return "That product could not be found.";
  }
  if (/Product already has an active publishing job/i.test(normalized)) {
    return "This product is already being sent to the store.";
  }
  if (/Product mockup not found/i.test(normalized)) {
    return "That image could not be found.";
  }
  if (/Publishing job not found/i.test(normalized)) {
    return "That send could not be found.";
  }
  if (/Uploaded asset is empty/i.test(normalized) || /Uploaded mockup is empty/i.test(normalized)) {
    return "That file was empty.";
  }
  if (/^(500\s+)?Internal Server Error$/i.test(normalized)) {
    return "Something went wrong on our side. Try again in a moment.";
  }
  if (/Velora backend is unavailable at/i.test(normalized)) {
    return "Velora isn't available right now. Try again in a moment.";
  }
  if (/Velora backend proxy expected API JSON/i.test(normalized)) {
    return "Velora isn't fully configured right now. The web app can't reach the backend service.";
  }
  if (/^<!DOCTYPE html>/i.test(normalized) || /<html[\s>]/i.test(normalized)) {
    return "Velora isn't fully configured right now. The web app can't reach the backend service.";
  }

  return normalized;
}

type ApiValidationIssue = {
  loc?: unknown;
  msg?: unknown;
  type?: unknown;
};

export function humanizeApiErrorPayload(payload: unknown) {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return null;
  }

  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) {
    return humanizeApiErrorDetail(detail);
  }

  if (!Array.isArray(detail)) {
    return null;
  }

  const issues = detail.filter(
    (issue): issue is ApiValidationIssue => Boolean(issue && typeof issue === "object")
  );
  const missingFile = issues.some((issue) => {
    const location = Array.isArray(issue.loc) ? issue.loc : [];
    return issue.type === "missing" && location.includes("body") && location.includes("file");
  });

  if (missingFile) {
    return "The upload arrived without a file. Choose the image again and retry.";
  }

  const messages = issues
    .map((issue) => (typeof issue.msg === "string" ? issue.msg.trim() : ""))
    .filter(Boolean);

  return messages.length ? humanizeApiErrorDetail(messages.join(" ")) : null;
}
