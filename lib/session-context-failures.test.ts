import assert from "node:assert/strict";
import test from "node:test";

import {
  classifySessionContextFailure,
  isAuthSessionContextFailure,
  isRetryableSessionContextFailure
} from "./session-context-failures.ts";

test("retryable session-context failures include not-yet-active Clerk tokens", () => {
  assert.equal(
    isRetryableSessionContextFailure(401, "Session token is not active yet."),
    true
  );
  assert.equal(
    classifySessionContextFailure(401, "Session token is not active yet."),
    "retryable"
  );
});

test("authentication failures include expired or missing sessions", () => {
  assert.equal(isAuthSessionContextFailure(401, "Not authenticated"), true);
  assert.equal(isAuthSessionContextFailure(401, "Session token has expired."), true);
  assert.equal(classifySessionContextFailure(401, "Not authenticated"), "sign_in");
});

test("non-auth backend failures stay classified as backend errors", () => {
  assert.equal(
    isAuthSessionContextFailure(500, "Internal Server Error"),
    false
  );
  assert.equal(
    classifySessionContextFailure(500, "Internal Server Error"),
    "backend"
  );
});
