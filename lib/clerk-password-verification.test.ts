import assert from "node:assert/strict";
import test from "node:test";

import { verifySessionWithCurrentPassword } from "./clerk-password-verification.ts";

test("reuses the entered current password for Clerk first-factor verification", async () => {
  const attempts: Array<{ strategy: string; password: string }> = [];
  const session = {
    startVerification: async () => ({
      status: "needs_first_factor",
      supportedFirstFactors: [{ strategy: "password" }]
    }),
    attemptFirstFactorVerification: async (attempt: {
      strategy: string;
      password: string;
    }) => {
      attempts.push(attempt);
      return { status: "complete" };
    }
  };

  const complete = await verifySessionWithCurrentPassword(
    session as never,
    "current-password"
  );

  assert.equal(complete, true);
  assert.deepEqual(attempts, [
    {
      strategy: "password",
      password: "current-password"
    }
  ]);
});

test("does not prompt again when the session first factor is already fresh", async () => {
  let attemptCount = 0;
  const session = {
    startVerification: async () => ({
      status: "complete",
      supportedFirstFactors: [{ strategy: "password" }]
    }),
    attemptFirstFactorVerification: async () => {
      attemptCount += 1;
      return { status: "complete" };
    }
  };

  const complete = await verifySessionWithCurrentPassword(
    session as never,
    "current-password"
  );

  assert.equal(complete, true);
  assert.equal(attemptCount, 0);
});

test("leaves unsupported or additional factors to Clerk reverification", async () => {
  let attemptCount = 0;
  const session = {
    startVerification: async () => ({
      status: "needs_first_factor",
      supportedFirstFactors: [{ strategy: "email_code" }]
    }),
    attemptFirstFactorVerification: async () => {
      attemptCount += 1;
      return { status: "complete" };
    }
  };

  const complete = await verifySessionWithCurrentPassword(
    session as never,
    "current-password"
  );

  assert.equal(complete, false);
  assert.equal(attemptCount, 0);
});
