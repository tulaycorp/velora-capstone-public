import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import {
  AuthReturnToSignInControl,
  AuthRouteLink
} from "@/components/auth/auth-page-controls";
import { AuthShell, clerkAuthAppearance } from "@/components/auth/auth-shell";
import {
  ClerkSignInCard,
  PasswordResetSignInCard
} from "@/components/auth/clerk-ui";
import { ClerkStatusCard } from "@/components/auth/clerk-status-card";
import { ForgotPasswordCard } from "@/components/auth/forgot-password-card";
import {
  hasNestedAuthEntryRoute,
  isForgotPasswordEntryRoute,
  resolvePostAuthLandingPath,
  shouldRedirectSignedInAuthEntry
} from "@/lib/auth-entry-state";
import { getMissingClerkFrontendEnvKeys, isClerkFrontendConfigured } from "@/lib/clerk-config";
import { fetchServerSessionContext } from "@/lib/server-session-context";

export default async function SignInPage({
  params,
  searchParams
}: {
  params: Promise<{ "sign-in"?: string[] }>;
  searchParams: Promise<{ "password-reset"?: string }>;
}) {
  const clerkEnabled = isClerkFrontendConfigured();
  const routeParams = await params;
  const routeSearchParams = await searchParams;
  const authPathSegments = routeParams["sign-in"] ?? [];
  const showReturnToSignInControl = hasNestedAuthEntryRoute(authPathSegments);
  const showForgotPassword = isForgotPasswordEntryRoute(authPathSegments);
  const passwordResetSucceeded =
    !showForgotPassword && routeSearchParams["password-reset"] === "success";

  if (clerkEnabled) {
    const session = await auth();
    if (
      shouldRedirectSignedInAuthEntry({
        userId: session.userId,
        hasNestedRoute: showReturnToSignInControl,
        passwordResetSucceeded
      })
    ) {
      const sessionContext = await fetchServerSessionContext();
      redirect(resolvePostAuthLandingPath(sessionContext.onboarding_status));
    }
  }

  return (
    <AuthShell
      eyebrow={showForgotPassword ? "Password recovery" : "Sign in"}
      title={
        showForgotPassword
          ? "Reset your password, then sign in again."
          : "Sign in to keep your product work moving."
      }
      description={
        showForgotPassword
          ? "Verify the email connected to your account, choose a new password, then return to sign in."
          : "Bring artwork, mockups, and listing details together in one workspace, then turn them into polished products with less repetitive setup."
      }
      panelLabel={showForgotPassword ? "Reset password" : "Sign in"}
      controls={showReturnToSignInControl ? <AuthReturnToSignInControl /> : undefined}
      footer={
        showForgotPassword ? (
          <>
            Need an account?{" "}
            <AuthRouteLink
              href="/sign-up"
              className="font-medium text-primary hover:text-primary/80"
            >
              Create one
            </AuthRouteLink>
            .
          </>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
            <span>
              Need an account?{" "}
              <AuthRouteLink
                href="/sign-up"
                className="font-medium text-primary hover:text-primary/80"
              >
                Create one
              </AuthRouteLink>
              .
            </span>
            <AuthRouteLink
              href="/sign-in/forgot-password"
              className="font-medium text-primary hover:text-primary/80"
            >
              Forgot password?
            </AuthRouteLink>
          </div>
        )
      }
    >
      {clerkEnabled ? (
        showForgotPassword ? (
          <ForgotPasswordCard />
        ) : (
          <div className="space-y-5">
            {passwordResetSucceeded ? (
              <div
                role="status"
                className="border border-primary/25 bg-primary/10 px-4 py-3 text-sm leading-6 text-foreground"
              >
                Password updated. Sign in with your new password.
              </div>
            ) : null}
            {passwordResetSucceeded ? (
              <PasswordResetSignInCard appearance={clerkAuthAppearance} />
            ) : (
              <ClerkSignInCard appearance={clerkAuthAppearance} />
            )}
          </div>
        )
      ) : (
        <ClerkStatusCard mode="sign-in" missingEnv={getMissingClerkFrontendEnvKeys()} />
      )}
    </AuthShell>
  );
}
