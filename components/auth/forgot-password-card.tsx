"use client";

import { useState } from "react";
import { useSignIn } from "@clerk/nextjs";
import { LoaderCircle } from "lucide-react";
import { ClerkAuthLoadingState } from "@/components/auth/clerk-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import { PASSWORD_RESET_SUCCESS_PATH } from "@/lib/auth-entry-state";

const fieldClassName =
  "h-14 rounded-none border-x-0 border-t-0 border-b border-white/12 bg-transparent px-0 text-base text-foreground shadow-none placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-0 focus-visible:ring-offset-0";

const labelClassName =
  "text-[10px] uppercase tracking-[0.28em] text-muted-foreground";

export function ForgotPasswordCard() {
  const { signIn, errors, fetchStatus } = useSignIn();
  const [emailAddress, setEmailAddress] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [signOutOfOtherSessions, setSignOutOfOtherSessions] = useState(true);
  const [localError, setLocalError] = useState<string | null>(null);
  const [isCompletingReset, setIsCompletingReset] = useState(false);
  const isSubmitting = fetchStatus === "fetching" || isCompletingReset;

  async function sendCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);

    try {
      const { error: createError } = await signIn.create({
        identifier: emailAddress.trim()
      });
      if (createError) {
        setLocalError(readClerkError(createError, "We could not start password recovery."));
        return;
      }

      const { error: sendCodeError } = await signIn.resetPasswordEmailCode.sendCode();
      if (sendCodeError) {
        setLocalError(readClerkError(sendCodeError, "We could not send the reset code."));
        return;
      }

      setCodeSent(true);
    } catch {
      setLocalError("We could not send the reset code. Try again in a moment.");
    }
  }

  async function resendCode() {
    setLocalError(null);

    try {
      const { error } = await signIn.resetPasswordEmailCode.sendCode();
      if (error) {
        setLocalError(readClerkError(error, "We could not send another reset code."));
      }
    } catch {
      setLocalError("We could not send another reset code. Try again in a moment.");
    }
  }

  async function verifyCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);

    try {
      const { error } = await signIn.resetPasswordEmailCode.verifyCode({ code: code.trim() });
      if (error) {
        setLocalError(readClerkError(error, "That reset code could not be verified."));
      }
    } catch {
      setLocalError("That reset code could not be verified. Try again.");
    }
  }

  async function submitPassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);

    if (password !== confirmPassword) {
      setLocalError("The passwords do not match.");
      return;
    }

    setIsCompletingReset(true);

    try {
      const { error } = await signIn.resetPasswordEmailCode.submitPassword({
        password,
        signOutOfOtherSessions
      });
      if (error) {
        setIsCompletingReset(false);
        setLocalError(readClerkError(error, "We could not update the password."));
        return;
      }

      window.location.replace(PASSWORD_RESET_SUCCESS_PATH);
    } catch {
      setIsCompletingReset(false);
      setLocalError("We could not update the password. Try again in a moment.");
    }
  }

  function restart() {
    signIn.reset();
    setCodeSent(false);
    setCode("");
    setPassword("");
    setConfirmPassword("");
    setLocalError(null);
  }

  const errorMessage =
    localError
    ?? errors.fields.identifier?.message
    ?? errors.fields.code?.message
    ?? errors.fields.password?.message
    ?? null;

  if (isCompletingReset) {
    return (
      <ClerkAuthLoadingState
        title="Finishing password reset"
        description="Preparing the sign-in screen."
      />
    );
  }

  if (signIn.status === "needs_new_password") {
    return (
      <AuthResetSection
        title="Choose a new password"
        description="Use a password you have not used for this account before."
        errorMessage={errorMessage}
      >
        <form className="space-y-6" onSubmit={submitPassword}>
          <AuthField label="New password" htmlFor="reset-password">
            <PasswordInput
              id="reset-password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter a new password"
              className={fieldClassName}
              required
            />
          </AuthField>
          <AuthField label="Confirm password" htmlFor="reset-password-confirmation">
            <PasswordInput
              id="reset-password-confirmation"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Enter the password again"
              className={fieldClassName}
              required
            />
          </AuthField>
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={signOutOfOtherSessions}
              onChange={(event) => setSignOutOfOtherSessions(event.target.checked)}
            />
            Sign out of other devices
          </label>
          <ResetSubmitButton isSubmitting={isSubmitting} label="Save new password" />
        </form>
      </AuthResetSection>
    );
  }

  if (codeSent) {
    return (
      <AuthResetSection
        title="Check your email"
        description={`Enter the reset code sent to ${emailAddress.trim()}. Check your junk folder if it is not in your inbox.`}
        errorMessage={errorMessage}
      >
        <form className="space-y-6" onSubmit={verifyCode}>
          <AuthField label="Reset code" htmlFor="reset-code">
            <Input
              id="reset-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="Enter the code"
              className={fieldClassName}
              required
            />
          </AuthField>
          <ResetSubmitButton isSubmitting={isSubmitting} label="Verify code" />
        </form>
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          <button
            type="button"
            className="min-h-11 text-muted-foreground transition-colors hover:text-foreground"
            onClick={restart}
          >
            Use another email
          </button>
          <button
            type="button"
            className="min-h-11 font-medium text-primary transition-colors hover:text-primary/80"
            onClick={() => {
              void resendCode();
            }}
            disabled={isSubmitting}
          >
            Send another code
          </button>
        </div>
      </AuthResetSection>
    );
  }

  return (
    <AuthResetSection
      title="Reset your password"
      description="Enter the email address connected to your account. We will send you a reset code."
      errorMessage={errorMessage}
    >
      <form className="space-y-6" onSubmit={sendCode}>
        <AuthField label="Email address" htmlFor="reset-email">
          <Input
            id="reset-email"
            type="email"
            inputMode="email"
            autoComplete="email"
            value={emailAddress}
            onChange={(event) => setEmailAddress(event.target.value)}
            placeholder="Enter your email address"
            className={fieldClassName}
            required
          />
        </AuthField>
        <ResetSubmitButton isSubmitting={isSubmitting} label="Send reset code" />
      </form>
    </AuthResetSection>
  );
}

function AuthResetSection({
  title,
  description,
  errorMessage,
  children
}: {
  title: string;
  description: string;
  errorMessage: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
      {errorMessage ? (
        <div
          role="alert"
          className="border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {errorMessage}
        </div>
      ) : null}
      {children}
    </div>
  );
}

function AuthField({
  label,
  htmlFor,
  children
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-3">
      <Label htmlFor={htmlFor} className={labelClassName}>
        {label}
      </Label>
      {children}
    </div>
  );
}

function ResetSubmitButton({
  isSubmitting,
  label
}: {
  isSubmitting: boolean;
  label: string;
}) {
  return (
    <Button
      type="submit"
      disabled={isSubmitting}
      className="h-12 w-full rounded-none text-sm uppercase tracking-[0.22em]"
    >
      {isSubmitting ? <LoaderCircle className="animate-spin" /> : null}
      {isSubmitting ? "Working..." : label}
    </Button>
  );
}

function readClerkError(error: unknown, fallback: string) {
  if (!error || typeof error !== "object" || !("errors" in error)) {
    return fallback;
  }

  const entries = (error as { errors?: Array<{ longMessage?: string; message?: string }> }).errors;
  return entries?.[0]?.longMessage ?? entries?.[0]?.message ?? fallback;
}
