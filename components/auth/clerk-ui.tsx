"use client";

import { useEffect, useRef, useState } from "react";
import {
  ClerkProvider,
  SignIn,
  SignUp,
  useAuth,
  useClerk,
  useSignIn,
  useSignUp
} from "@clerk/nextjs";
import { usePathname } from "next/navigation";
import { Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  PASSWORD_RESET_SUCCESS_PATH,
  resolveResetPasswordEmailDeliveryNotice,
  resolveSignUpEmailDeliveryNotice
} from "@/lib/auth-entry-state";
import {
  PASSWORD_RESET_HANDOFF_TIMEOUT_MS,
  resolvePasswordResetSignOutOptions
} from "@/lib/password-reset-handoff";

const postAuthRedirectUrl = "/dashboard";

export function ClerkAppProvider({
  nonce,
  children
}: {
  nonce?: string;
  children: React.ReactNode;
}) {
  return (
    <ClerkProvider
      dynamic={Boolean(nonce)}
      nonce={nonce}
      signInForceRedirectUrl={postAuthRedirectUrl}
      signInFallbackRedirectUrl={postAuthRedirectUrl}
      signUpForceRedirectUrl={postAuthRedirectUrl}
      signUpFallbackRedirectUrl={postAuthRedirectUrl}
    >
      {children}
    </ClerkProvider>
  );
}

export function ClerkSignInCard({
  appearance
}: {
  appearance: Record<string, unknown>;
}) {
  return (
    <ClerkAuthSurface>
      <AuthEmailDeliveryNotice flow="sign-in" />
      <SignIn
        appearance={appearance}
        routing="path"
        path="/sign-in"
        signUpUrl="/sign-up"
        forceRedirectUrl={postAuthRedirectUrl}
        fallbackRedirectUrl={postAuthRedirectUrl}
        signUpForceRedirectUrl={postAuthRedirectUrl}
        signUpFallbackRedirectUrl={postAuthRedirectUrl}
      />
    </ClerkAuthSurface>
  );
}

export function PasswordResetSignInCard({
  appearance
}: {
  appearance: Record<string, unknown>;
}) {
  const { isLoaded } = useAuth();
  const clerk = useClerk();
  const { signIn } = useSignIn();
  const clerkRef = useRef(clerk);
  const signInRef = useRef(signIn);
  const preparedRef = useRef(false);
  const [isReady, setIsReady] = useState(false);
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const [handoffAttempt, setHandoffAttempt] = useState(0);

  clerkRef.current = clerk;
  signInRef.current = signIn;

  useEffect(() => {
    let cancelled = false;
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      if (!cancelled) {
        setHandoffError(
          "Signing out after the password reset is taking too long. Retry the sign-out before continuing."
        );
      }
    }, PASSWORD_RESET_HANDOFF_TIMEOUT_MS);

    if (!isLoaded || preparedRef.current) {
      return () => {
        cancelled = true;
        window.clearTimeout(timeoutId);
      };
    }

    preparedRef.current = true;

    async function prepareSignedOutForm() {
      const activeClerk = clerkRef.current;
      const activeSignIn = signInRef.current;
      const signOutOptions = resolvePasswordResetSignOutOptions(
        activeSignIn.createdSessionId,
        activeClerk.session?.id ?? null,
        activeClerk.client.sessions.map((session) => session.id)
      );

      try {
        if (signOutOptions) {
          await activeClerk.signOut(signOutOptions);
        }

        activeSignIn.reset();
        if (!cancelled && !timedOut) {
          setIsReady(true);
        }
      } catch {
        if (!cancelled && !timedOut) {
          setHandoffError(
            "We could not sign out after the password reset. Retry the sign-out before continuing."
          );
        }
      } finally {
        window.clearTimeout(timeoutId);
      }
    }

    void prepareSignedOutForm();

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [handoffAttempt, isLoaded]);

  if (handoffError) {
    return (
      <div
        role="alert"
        className="border border-destructive/30 bg-destructive/10 px-4 py-4 text-sm text-destructive"
      >
        <p className="leading-6">{handoffError}</p>
        <Button
          type="button"
          variant="outline"
          className="mt-4"
          onClick={() => {
            preparedRef.current = false;
            setHandoffError(null);
            setIsReady(false);
            setHandoffAttempt((attempt) => attempt + 1);
          }}
        >
          Retry sign-out
        </Button>
      </div>
    );
  }

  if (!isReady) {
    return <ClerkAuthLoadingState />;
  }

  return <ClerkSignInCard appearance={appearance} />;
}

export function ClerkSignUpCard({
  appearance
}: {
  appearance: Record<string, unknown>;
}) {
  return (
    <ClerkAuthSurface>
      <AuthEmailDeliveryNotice flow="sign-up" />
      <SignUp
        appearance={appearance}
        routing="path"
        path="/sign-up"
        signInUrl="/sign-in"
        forceRedirectUrl={postAuthRedirectUrl}
        fallbackRedirectUrl={postAuthRedirectUrl}
        signInForceRedirectUrl={postAuthRedirectUrl}
        signInFallbackRedirectUrl={postAuthRedirectUrl}
      />
    </ClerkAuthSurface>
  );
}

function ClerkAuthSurface({ children }: { children: React.ReactNode }) {
  const { isLoaded } = useAuth();

  if (!isLoaded) {
    return <ClerkAuthLoadingState />;
  }

  return <>{children}</>;
}

export function ClerkAuthLoadingState({
  title = "Loading...",
  description = "Loading sign-in options."
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="relative overflow-hidden border border-white/10 bg-white/[0.02]"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(41,183,177,0.14),transparent_34%),linear-gradient(180deg,rgba(255,255,255,0.05),transparent_62%)]" />

      <div className="relative flex min-h-[164px] flex-col justify-center gap-5 px-6 py-6 md:px-7 md:py-7">
        <div className="flex items-center gap-2" aria-hidden="true">
          <span className="h-2 w-2 rounded-full bg-primary/90 motion-safe:animate-pulse" />
          <span
            className="h-2 w-2 rounded-full bg-primary/60 motion-safe:animate-pulse [animation-delay:150ms]"
          />
          <span
            className="h-2 w-2 rounded-full bg-primary/35 motion-safe:animate-pulse [animation-delay:300ms]"
          />
        </div>
        <div className="auth-display text-[2rem] leading-[0.95] text-foreground">{title}</div>
        <div className="h-px w-16 bg-white/10" aria-hidden="true" />
        <p className="text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function AuthEmailDeliveryNotice({
  flow
}: {
  flow: "sign-in" | "sign-up";
}) {
  const pathname = usePathname() ?? "";
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();

  const notice =
    flow === "sign-up"
      ? resolveSignUpEmailDeliveryNotice({
          pathname,
          emailAddress: signUp?.emailAddress ?? null,
          verificationStatus: signUp?.verifications.emailAddress.status ?? null,
          verificationStrategy: signUp?.verifications.emailAddress.strategy ?? null
        })
      : resolveResetPasswordEmailDeliveryNotice({
          pathname,
          identifier: signIn?.identifier ?? null,
          signInStatus: signIn?.status ?? null,
          verificationStrategy: signIn?.firstFactorVerification.strategy ?? null
        });

  if (!notice) {
    return null;
  }

  return (
    <div className="border-y border-white/10 bg-white/[0.02] px-4 py-4 text-foreground">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center border border-primary/20 bg-primary/10 text-primary">
          <Mail className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.28em] text-primary/80">
            {notice.label}
          </div>
          <div className="mt-2 text-sm font-medium text-foreground">
            {notice.title}
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {notice.description}
          </p>
        </div>
      </div>
    </div>
  );
}
