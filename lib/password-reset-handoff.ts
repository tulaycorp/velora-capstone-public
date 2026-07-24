export const PASSWORD_RESET_HANDOFF_TIMEOUT_MS = 6_000;

export function resolvePasswordResetSignOutOptions(
  createdSessionId: string | null,
  activeSessionId: string | null,
  availableSessionIds: readonly string[]
) {
  const sessionId = [createdSessionId, activeSessionId].find(
    (candidate): candidate is string =>
      candidate !== null && availableSessionIds.includes(candidate)
  );
  return sessionId ? { sessionId } : null;
}
