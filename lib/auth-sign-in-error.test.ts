import assert from "node:assert/strict";
import test from "node:test";
import {
  INCORRECT_PASSWORD_MESSAGE,
  SIGN_IN_UNAVAILABLE_MESSAGE,
  resolvePasswordSignInError
} from "./auth-sign-in-error.ts";

test("incorrect passwords use concise actionable copy", () => {
  assert.equal(
    resolvePasswordSignInError({
      code: "form_password_incorrect",
      longMessage: "Password is incorrect."
    }),
    INCORRECT_PASSWORD_MESSAGE
  );
});

test("other Clerk errors retain their user-facing long message", () => {
  assert.equal(
    resolvePasswordSignInError({
      code: "identifier_not_found",
      longMessage: "No account was found for that email address."
    }),
    "No account was found for that email address."
  );
});

test("missing error details fall back to a safe sign-in message", () => {
  assert.equal(resolvePasswordSignInError(null), SIGN_IN_UNAVAILABLE_MESSAGE);
});
