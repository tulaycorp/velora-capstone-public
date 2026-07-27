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
import { ui } from "@clerk/ui";
import { shadcn } from "@clerk/ui/themes";
import { usePathname, useRouter } from "next/navigation";
import { LoaderCircle, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import {
  PASSWORD_RESET_SUCCESS_PATH,
  POST_AUTH_HANDOFF_PATH,
  resolveResetPasswordEmailDeliveryNotice,
  SIGN_UP_POST_AUTH_PATH,
  resolveSignUpEmailDeliveryNotice
} from "@/lib/auth-entry-state";
import { resolvePasswordSignInError } from "@/lib/auth-sign-in-error";
import {
  PASSWORD_RESET_HANDOFF_TIMEOUT_MS,
  resolvePasswordResetSignOutOptions
} from "@/lib/password-reset-handoff";

const weakPasswordMessage =
  "Your password is not strong enough. Add more words that are less common.";

export function ClerkAppProvider({
  nonce,
  children
}: {
  nonce?: string;
  children: React.ReactNode;
}) {
  return (
    <ClerkProvider
      ui={ui}
      dynamic={Boolean(nonce)}
      nonce={nonce}
      appearance={{ theme: shadcn }}
      localization={{
        unstable__errors: {
          form_password_length_too_short: weakPasswordMessage,
          form_password_not_strong_enough: weakPasswordMessage,
          passwordComplexity: {
            sentencePrefix: "",
            minimumLength: weakPasswordMessage
          },
          zxcvbn: {
            notEnough: weakPasswordMessage
          }
        }
      }}
      signInForceRedirectUrl={POST_AUTH_HANDOFF_PATH}
      signInFallbackRedirectUrl={POST_AUTH_HANDOFF_PATH}
      signUpForceRedirectUrl={SIGN_UP_POST_AUTH_PATH}
      signUpFallbackRedirectUrl={SIGN_UP_POST_AUTH_PATH}
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
  const pathname = usePathname() ?? "";

  return (
    <ClerkAuthSurface>
      <AuthEmailDeliveryNotice flow="sign-in" />
      {pathname === "/sign-in" ? (
        <PasswordSignInForm appearance={appearance} />
      ) : (
        <ClerkSignInContinuation appearance={appearance} />
      )}
    </ClerkAuthSurface>
  );
}

function ClerkSignInContinuation({
  appearance
}: {
  appearance: Record<string, unknown>;
}) {
  return (
    <SignIn
      appearance={appearance}
      routing="path"
      path="/sign-in"
      signUpUrl="/sign-up"
      forceRedirectUrl={POST_AUTH_HANDOFF_PATH}
      fallbackRedirectUrl={POST_AUTH_HANDOFF_PATH}
      signUpForceRedirectUrl={SIGN_UP_POST_AUTH_PATH}
      signUpFallbackRedirectUrl={SIGN_UP_POST_AUTH_PATH}
    />
  );
}

function PasswordSignInForm({
  appearance
}: {
  appearance: Record<string, unknown>;
}) {
  const router = useRouter();
  const { signIn, fetchStatus } = useSignIn();
  const [emailAddress, setEmailAddress] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showContinuation, setShowContinuation] = useState(false);

  async function finalizeSignIn() {
    await signIn.finalize({
      navigate: ({ session, decorateUrl }) => {
        const destination = session.currentTask
          ? `/sign-in/tasks/${session.currentTask.key}`
          : POST_AUTH_HANDOFF_PATH;
        const url = decorateUrl(destination);

        if (url.startsWith("http")) {
          window.location.assign(url);
          return;
        }

        router.push(url);
      }
    });
  }

  async function handlePasswordSignIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);

    if (!emailAddress.trim() || !password) {
      setLocalError("Enter your email address and password.");
      return;
    }

    setIsSubmitting(true);

    try {
      const { error } = await signIn.password({
        emailAddress: emailAddress.trim(),
        password
      });

      if (error) {
        const message = resolvePasswordSignInError(error);
        signIn.reset();
        setLocalError(message);
        return;
      }

      if (signIn.status === "complete") {
        await finalizeSignIn();
        return;
      }

      setShowContinuation(true);
    } catch {
      setLocalError(resolvePasswordSignInError(null));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleGoogleSignIn() {
    setLocalError(null);
    setIsSubmitting(true);

    try {
      const { error } = await signIn.sso({
        strategy: "oauth_google",
        redirectUrl: POST_AUTH_HANDOFF_PATH,
        redirectCallbackUrl: "/sign-in/sso-callback"
      });

      if (error) {
        setLocalError(resolvePasswordSignInError(error));
      }
    } catch {
      setLocalError(resolvePasswordSignInError(null));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (showContinuation) {
    return <ClerkSignInContinuation appearance={appearance} />;
  }

  const submitting = isSubmitting || fetchStatus === "fetching";
  const fieldClassName =
    "h-14 !w-full rounded-none border-x-0 border-t-0 border-b border-white/12 bg-transparent px-0 text-base text-foreground shadow-none placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-0 focus-visible:ring-offset-0";

  return (
    <div className="w-full space-y-6">
      <button
        type="button"
        onClick={() => {
          void handleGoogleSignIn();
        }}
        disabled={submitting}
        className="velora-social-provider-button h-12 w-full rounded-none border border-white/10 bg-white/[0.02] px-4 font-medium text-foreground shadow-none transition-colors hover:border-primary/40 hover:bg-white/[0.04] disabled:pointer-events-none disabled:opacity-50"
      >
        <span>
          <span
            aria-hidden="true"
            className="velora-social-provider-icon cl-socialButtonsProviderIcon__google"
          />
          <span>Continue with Google</span>
        </span>
      </button>

      <div className="flex items-center gap-3" aria-hidden="true">
        <div className="h-px flex-1 bg-white/10" />
        <span className="text-[10px] uppercase tracking-[0.32em] text-muted-foreground">
          or
        </span>
        <div className="h-px flex-1 bg-white/10" />
      </div>

      <form className="w-full space-y-5" onSubmit={handlePasswordSignIn} noValidate>
        <div className="space-y-2">
          <label
            htmlFor="sign-in-email"
            className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground"
          >
            Email address
          </label>
          <Input
            id="sign-in-email"
            name="emailAddress"
            type="email"
            autoComplete="email"
            placeholder="Enter your email address"
            value={emailAddress}
            disabled={submitting}
            aria-invalid={Boolean(localError)}
            aria-describedby={localError ? "sign-in-password-error" : undefined}
            onChange={(event) => {
              setEmailAddress(event.target.value);
              setLocalError(null);
            }}
            className={fieldClassName}
          />
        </div>

        <div className="space-y-2">
          <label
            htmlFor="sign-in-password"
            className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground"
          >
            Password
          </label>
          <PasswordInput
            id="sign-in-password"
            name="password"
            autoComplete="current-password"
            placeholder="Enter your password"
            value={password}
            disabled={submitting}
            aria-invalid={Boolean(localError)}
            aria-describedby={localError ? "sign-in-password-error" : undefined}
            onChange={(event) => {
              setPassword(event.target.value);
              setLocalError(null);
            }}
            className={fieldClassName}
          />
          {localError ? (
            <p
              id="sign-in-password-error"
              role="alert"
              className="text-[0.8125rem] leading-[1.35rem] text-destructive"
            >
              {localError}
            </p>
          ) : null}
        </div>

        <Button
          type="submit"
          disabled={submitting}
          className="mt-2 h-12 w-full rounded-none px-5 text-sm uppercase leading-none tracking-[0.28em]"
        >
          {submitting ? (
            <>
              <LoaderCircle className="animate-spin" aria-hidden="true" />
              Signing in...
            </>
          ) : (
            "Continue"
          )}
        </Button>
      </form>
    </div>
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
        forceRedirectUrl={SIGN_UP_POST_AUTH_PATH}
        fallbackRedirectUrl={SIGN_UP_POST_AUTH_PATH}
        signInForceRedirectUrl={POST_AUTH_HANDOFF_PATH}
        signInFallbackRedirectUrl={POST_AUTH_HANDOFF_PATH}
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
