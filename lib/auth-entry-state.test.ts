import assert from "node:assert/strict";
import test from "node:test";

import {
  hasNestedAuthEntryRoute,
  isForgotPasswordEntryRoute,
  POST_AUTH_HANDOFF_PATH,
  resolvePostAuthLandingPath,
  resolveResetPasswordEmailDeliveryNotice,
  SIGN_UP_POST_AUTH_PATH,
  resolveSignUpEmailDeliveryNotice,
  shouldRedirectSignedInAuthEntry
} from "./auth-entry-state.ts";

test("auth completion paths avoid mounting the workspace before access is resolved", () => {
  assert.equal(POST_AUTH_HANDOFF_PATH, "/auth/complete");
  assert.equal(SIGN_UP_POST_AUTH_PATH, "/onboarding");
});

test("root auth routes are not treated as nested Clerk subflows", () => {
  assert.equal(hasNestedAuthEntryRoute(undefined), false);
  assert.equal(hasNestedAuthEntryRoute([]), false);
  assert.equal(hasNestedAuthEntryRoute(["verify-email-address"]), true);
});

test("forgot-password route is recognized without matching unrelated nested steps", () => {
  assert.equal(isForgotPasswordEntryRoute(["forgot-password"]), true);
  assert.equal(isForgotPasswordEntryRoute(["forgot-password", "verify"]), true);
  assert.equal(isForgotPasswordEntryRoute(["reset-password"]), false);
  assert.equal(isForgotPasswordEntryRoute([]), false);
});

test("post-auth landing path follows onboarding status", () => {
  assert.equal(resolvePostAuthLandingPath("approved"), "/dashboard");
  assert.equal(resolvePostAuthLandingPath("needs_organization"), "/onboarding");
  assert.equal(resolvePostAuthLandingPath("pending"), "/onboarding");
});

test("reset-success handoff stays reachable while Clerk clears its temporary session", () => {
  assert.equal(
    shouldRedirectSignedInAuthEntry({
      userId: "user_reset",
      hasNestedRoute: false,
      passwordResetSucceeded: true
    }),
    false
  );
  assert.equal(
    shouldRedirectSignedInAuthEntry({
      userId: "user_normal",
      hasNestedRoute: false,
      passwordResetSucceeded: false
    }),
    true
  );
  assert.equal(
    shouldRedirectSignedInAuthEntry({
      userId: "user_nested",
      hasNestedRoute: true,
      passwordResetSucceeded: false
    }),
    false
  );
});

test("sign-up email delivery notice appears only on email-code verification steps", () => {
  assert.deepEqual(
    resolveSignUpEmailDeliveryNotice({
      pathname: "/sign-up/verify-email-address",
      emailAddress: "creator@velora.test",
      verificationStatus: "unverified",
      verificationStrategy: "email_code"
    }),
    {
      description:
        "Check your inbox and junk folder for the verification code, then return here to finish creating the account.",
      label: "Verification email",
      title: "Email sent to creator@velora.test"
    }
  );

  assert.equal(
    resolveSignUpEmailDeliveryNotice({
      pathname: "/sign-up",
      emailAddress: "creator@velora.test",
      verificationStatus: "unverified",
      verificationStrategy: "email_code"
    }),
    null
  );

  assert.equal(
    resolveSignUpEmailDeliveryNotice({
      pathname: "/sign-up/verify-email-address",
      emailAddress: "creator@velora.test",
      verificationStatus: "verified",
      verificationStrategy: "email_code"
    }),
    null
  );
});

test("reset-password notice appears for reset email code and new-password steps only", () => {
  assert.deepEqual(
    resolveResetPasswordEmailDeliveryNotice({
      pathname: "/sign-in/verify/factor-one",
      identifier: "member@velora.test",
      signInStatus: "needs_first_factor",
      verificationStrategy: "reset_password_email_code"
    }),
    {
      description:
        "Check your inbox and junk folder for the password reset code, then come back here to choose a new password.",
      label: "Password reset",
      title: "Password reset email sent to member@velora.test"
    }
  );

  assert.deepEqual(
    resolveResetPasswordEmailDeliveryNotice({
      pathname: "/sign-in/reset-password",
      identifier: "member@velora.test",
      signInStatus: "needs_new_password",
      verificationStrategy: "reset_password_email_code"
    }),
    {
      description:
        "Check your inbox and junk folder for the password reset code, then come back here to choose a new password.",
      label: "Password reset",
      title: "Password reset email sent to member@velora.test"
    }
  );

  assert.equal(
    resolveResetPasswordEmailDeliveryNotice({
      pathname: "/sign-in/verify/factor-one",
      identifier: "member@velora.test",
      signInStatus: "needs_first_factor",
      verificationStrategy: "email_code"
    }),
    null
  );
});
