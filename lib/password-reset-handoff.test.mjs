import assert from "node:assert/strict";
import test from "node:test";

import {
  PASSWORD_RESET_HANDOFF_TIMEOUT_MS,
  resolvePasswordResetSignOutOptions
} from "./password-reset-handoff.ts";

test("password reset handoff uses a bounded cleanup window", () => {
  assert.equal(PASSWORD_RESET_HANDOFF_TIMEOUT_MS, 6_000);
});

test("password reset sign-out targets one live session without a redirect", () => {
  assert.deepEqual(
    resolvePasswordResetSignOutOptions(
      "session_reset",
      "session_active",
      ["session_reset", "session_active"]
    ),
    { sessionId: "session_reset" }
  );
  assert.deepEqual(
    resolvePasswordResetSignOutOptions(null, "session_active", ["session_active"]),
    { sessionId: "session_active" }
  );
  assert.deepEqual(
    resolvePasswordResetSignOutOptions(
      "session_stale",
      "session_active",
      ["session_active"]
    ),
    { sessionId: "session_active" }
  );
  assert.equal(
    resolvePasswordResetSignOutOptions("session_stale", null, []),
    null
  );
});
