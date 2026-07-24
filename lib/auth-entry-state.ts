import type { OnboardingStatus } from "@/lib/backend-api";

export const PASSWORD_RESET_SUCCESS_PATH = "/sign-in?password-reset=success";

export type AuthEmailDeliveryNotice = {
  description: string;
  label: string;
  title: string;
};

export function hasNestedAuthEntryRoute(segments: string[] | undefined) {
  return Array.isArray(segments) && segments.length > 0;
}

export function isForgotPasswordEntryRoute(segments: string[] | undefined) {
  return Array.isArray(segments) && segments[0] === "forgot-password";
}

export function resolvePostAuthLandingPath(onboardingStatus: OnboardingStatus) {
  return onboardingStatus === "approved" ? "/dashboard" : "/onboarding";
}

export function shouldRedirectSignedInAuthEntry(options: {
  userId: string | null;
  hasNestedRoute: boolean;
  passwordResetSucceeded: boolean;
}) {
  return Boolean(
    options.userId
    && !options.hasNestedRoute
    && !options.passwordResetSucceeded
  );
}

export function resolveSignUpEmailDeliveryNotice(options: {
  pathname: string;
  emailAddress: string | null;
  verificationStatus: string | null;
  verificationStrategy: string | null;
}): AuthEmailDeliveryNotice | null {
  const email = normalizeEmailAddress(options.emailAddress);
  if (!email) {
    return null;
  }

  if (!options.pathname.startsWith("/sign-up") || options.pathname === "/sign-up") {
    return null;
  }

  if (options.verificationStrategy !== "email_code" || options.verificationStatus === "verified") {
    return null;
  }

  return {
    description:
      "Check your inbox and junk folder for the verification code, then return here to finish creating the account.",
    label: "Verification email",
    title: `Email sent to ${email}`
  };
}

export function resolveResetPasswordEmailDeliveryNotice(options: {
  pathname: string;
  identifier: string | null;
  signInStatus: string | null;
  verificationStrategy: string | null;
}): AuthEmailDeliveryNotice | null {
  const email = normalizeEmailAddress(options.identifier);
  if (!email) {
    return null;
  }

  if (!options.pathname.startsWith("/sign-in")) {
    return null;
  }

  const isResetPasswordVerification =
    options.verificationStrategy === "reset_password_email_code";
  const isWaitingForNewPassword = options.signInStatus === "needs_new_password";
  const isExplicitResetPasswordRoute =
    options.pathname === "/sign-in/reset-password"
    || options.pathname.startsWith("/sign-in/reset-password/");

  if (
    !isResetPasswordVerification
    && !isWaitingForNewPassword
    && !isExplicitResetPasswordRoute
  ) {
    return null;
  }

  return {
    description:
      "Check your inbox and junk folder for the password reset code, then come back here to choose a new password.",
    label: "Password reset",
    title: `Password reset email sent to ${email}`
  };
}

function normalizeEmailAddress(value: string | null) {
  const normalizedValue = value?.trim() ?? "";
  if (!normalizedValue || !normalizedValue.includes("@")) {
    return null;
  }

  return normalizedValue;
}
