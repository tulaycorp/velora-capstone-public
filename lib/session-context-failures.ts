export type SessionContextFailureCode = "retryable" | "sign_in" | "backend";

const RETRYABLE_DETAIL_SNIPPETS = [
  "session token is not active yet",
  "unable to verify session token"
] as const;

const AUTH_DETAIL_SNIPPETS = [
  "not authenticated",
  "session token has expired",
  "invalid session token",
  "invalid session issuer",
  "invalid authorized party",
  ...RETRYABLE_DETAIL_SNIPPETS
] as const;

function normalizeDetail(detail: string) {
  return detail.trim().toLowerCase();
}

export function isRetryableSessionContextFailure(status: number, detail: string) {
  if (status < 500 && status !== 401 && status !== 403) {
    return false;
  }

  const normalizedDetail = normalizeDetail(detail);
  return RETRYABLE_DETAIL_SNIPPETS.some((snippet) => normalizedDetail.includes(snippet));
}

export function isAuthSessionContextFailure(status: number, detail: string) {
  if (status === 401 || status === 403) {
    return true;
  }

  const normalizedDetail = normalizeDetail(detail);
  return AUTH_DETAIL_SNIPPETS.some((snippet) => normalizedDetail.includes(snippet));
}

export function classifySessionContextFailure(status: number, detail: string): SessionContextFailureCode {
  if (isRetryableSessionContextFailure(status, detail)) {
    return "retryable";
  }

  if (isAuthSessionContextFailure(status, detail)) {
    return "sign_in";
  }

  return "backend";
}
