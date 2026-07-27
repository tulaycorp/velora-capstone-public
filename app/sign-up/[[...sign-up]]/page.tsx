import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { AuthRouteLink } from "@/components/auth/auth-page-controls";
import { AuthShell, clerkAuthAppearance } from "@/components/auth/auth-shell";
import { ClerkSignUpCard } from "@/components/auth/clerk-ui";
import { ClerkStatusCard } from "@/components/auth/clerk-status-card";
import {
  hasNestedAuthEntryRoute,
  resolvePostAuthLandingPath
} from "@/lib/auth-entry-state";
import { getMissingClerkFrontendEnvKeys, isClerkFrontendConfigured } from "@/lib/clerk-config";
import { fetchServerSessionContext } from "@/lib/server-session-context";

export default async function SignUpPage({
  params
}: {
  params: Promise<{ "sign-up"?: string[] }>;
}) {
  const clerkEnabled = isClerkFrontendConfigured();
  const routeParams = await params;
  const authPathSegments = routeParams["sign-up"] ?? [];

  if (clerkEnabled) {
    const session = await auth();
    if (session.userId && !hasNestedAuthEntryRoute(authPathSegments)) {
      const sessionContext = await fetchServerSessionContext();
      redirect(resolvePostAuthLandingPath(sessionContext.onboarding_status));
    }
  }

  return (
    <AuthShell
      eyebrow="Create account"
      title="Create your account, then join the right workspace."
      description="Start your account first, then open a new workspace or request access to one your team already uses."
      panelLabel="New account"
      panelTone="setup"
      panelContext={
        <div className="mb-6 w-full max-w-md" aria-label="Account setup progress">
          <div className="flex items-center justify-between gap-4">
            <div className="text-sm font-medium text-foreground">Set up your access</div>
            <div className="text-[10px] uppercase tracking-[0.22em] text-primary">
              Step 1 of 2
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2" aria-hidden="true">
            <div className="h-px bg-primary" />
            <div className="h-px bg-white/[0.12]" />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="text-foreground">Account</div>
            <div className="text-muted-foreground">Workspace</div>
          </div>
        </div>
      }
      footer={
        <>
          Already have an account?{" "}
          <AuthRouteLink
            href="/sign-in"
            className="font-medium text-primary hover:text-primary/80"
          >
            Sign in
          </AuthRouteLink>
          .
        </>
      }
    >
      {clerkEnabled ? (
        <ClerkSignUpCard appearance={clerkAuthAppearance} />
      ) : (
        <ClerkStatusCard mode="sign-up" missingEnv={getMissingClerkFrontendEnvKeys()} />
      )}
    </AuthShell>
  );
}
