"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useReverification, useSession, useUser } from "@clerk/nextjs";
import { isClerkRuntimeError, isReverificationCancelledError } from "@clerk/nextjs/errors";
import type { EmailAddressResource, SessionWithActivitiesResource, UserResource } from "@clerk/shared/types";
import {
  CheckCircle2,
  Copy,
  LoaderCircle,
  LogOut,
  Mail,
  RefreshCw,
  ShieldCheck,
  Trash2
} from "lucide-react";
import { useAppSessionContext } from "@/components/auth/app-session-context";
import { PageHeader } from "@/components/workspace/page-header";
import { SettingsSkeleton } from "@/components/workspace/resource-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import { Separator } from "@/components/ui/separator";
import { leaveCurrentOrganization } from "@/lib/backend-api";
import { cn } from "@/lib/utils";

type ProfileDraft = {
  firstName: string;
  lastName: string;
};

type PasswordDraft = {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
};

async function fetchSortedSessions(user: UserResource) {
  const nextSessions = await user.getSessions();
  nextSessions.sort((left, right) => right.lastActiveAt.getTime() - left.lastActiveAt.getTime());
  return nextSessions;
}

export function AccountSettingsPage({
  clerkEnabled
}: {
  clerkEnabled: boolean;
}) {
  const { sessionContext } = useAppSessionContext();

  if (!clerkEnabled) {
    return <LocalModeAccountSettings emailLabel={sessionContext.user.email ?? sessionContext.user.display_name} />;
  }

  return <ClerkAccountSettingsContent />;
}

function LocalModeAccountSettings({ emailLabel }: { emailLabel: string }) {
  const { sessionContext } = useAppSessionContext();

  return (
    <>
      <PageHeader
        title="Account settings"
        description="Manage your profile and workspace access from one place."
      />

      <div className="max-w-3xl rounded-lg border border-border bg-card">
        <div className="border-b border-border px-5 py-4">
          <div className="text-base font-semibold text-foreground">Preview mode</div>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Full email, password, and signed-in device tools are not enabled in this environment yet.
          </p>
        </div>
        <div className="grid gap-3 px-5 py-5 sm:grid-cols-3">
          <SummaryField label="Email" value={emailLabel} className="break-all" />
          <SummaryField
            label="Organization"
            value={sessionContext.organization?.name ?? "No organization"}
          />
          <SummaryField
            label="Role"
            value={sessionContext.membership?.role ?? "No role"}
            className="capitalize"
          />
        </div>
      </div>
    </>
  );
}

function ClerkAccountSettingsContent() {
  const router = useRouter();
  const { sessionContext, setSessionContext } = useAppSessionContext();
  const { isLoaded, isSignedIn, user } = useUser();
  const { session } = useSession();

  const [profileDraft, setProfileDraft] = useState<ProfileDraft>({
    firstName: "",
    lastName: ""
  });
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileNotice, setProfileNotice] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [emailDraft, setEmailDraft] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [pendingEmailId, setPendingEmailId] = useState<string | null>(null);
  const [isAddingEmail, setIsAddingEmail] = useState(false);
  const [isVerifyingEmail, setIsVerifyingEmail] = useState(false);
  const [emailActionId, setEmailActionId] = useState<string | null>(null);
  const [emailNotice, setEmailNotice] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);

  const [passwordDraft, setPasswordDraft] = useState<PasswordDraft>({
    currentPassword: "",
    newPassword: "",
    confirmPassword: ""
  });
  const [signOutOfOtherSessions, setSignOutOfOtherSessions] = useState(true);
  const [isUpdatingPassword, setIsUpdatingPassword] = useState(false);
  const [passwordNotice, setPasswordNotice] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const [sessions, setSessions] = useState<SessionWithActivitiesResource[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [sessionActionId, setSessionActionId] = useState<string | null>(null);
  const [sessionsNotice, setSessionsNotice] = useState<string | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const [isLeaving, setIsLeaving] = useState(false);
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false);
  const [leaveError, setLeaveError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  const createEmailAddress = useReverification((email: string) => user?.createEmailAddress({ email }));
  const makePrimaryEmail = useReverification((emailAddressId: string) =>
    user?.update({ primaryEmailAddressId: emailAddressId })
  );
  const updatePassword = useReverification(
    (params: { currentPassword?: string; newPassword: string; signOutOfOtherSessions: boolean }) =>
      user?.updatePassword(params)
  );

  useEffect(() => {
    if (!user) {
      return;
    }

    setProfileDraft({
      firstName: user.firstName ?? "",
      lastName: user.lastName ?? ""
    });
  }, [user]);

  useEffect(() => {
    if (pendingEmailId && user && !user.emailAddresses.find((email) => email.id === pendingEmailId)) {
      setPendingEmailId(null);
      setVerificationCode("");
    }
  }, [pendingEmailId, user]);

  async function loadSessions() {
    if (!user) {
      return;
    }

    try {
      setIsLoadingSessions(true);
      setSessionsError(null);
      setSessions(await fetchSortedSessions(user));
    } catch (error) {
      setSessionsError(extractErrorMessage(error, "Unable to load signed-in devices."));
    } finally {
      setIsLoadingSessions(false);
    }
  }

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !user) {
      return;
    }

    const activeUser = user;
    let isActive = true;

    async function hydrateSessions() {
      try {
        setIsLoadingSessions(true);
        setSessionsError(null);
        const nextSessions = await fetchSortedSessions(activeUser);
        if (!isActive) {
          return;
        }
        setSessions(nextSessions);
      } catch (error) {
        if (!isActive) {
          return;
        }
        setSessionsError(extractErrorMessage(error, "Unable to load signed-in devices."));
      } finally {
        if (isActive) {
          setIsLoadingSessions(false);
        }
      }
    }

    void hydrateSessions();

    return () => {
      isActive = false;
    };
  }, [isLoaded, isSignedIn, user]);

  useEffect(() => {
    if (copyState === "idle") {
      return;
    }

    const timeout = window.setTimeout(() => {
      setCopyState("idle");
    }, 1800);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [copyState]);

  const organization = sessionContext.organization;
  const membership = sessionContext.membership;
  const joinCode = organization?.join_code ?? null;
  const isAdmin = membership?.role === "admin";
  const currentSessionId = session?.id ?? null;
  const emailLabel = user?.primaryEmailAddress?.emailAddress ?? sessionContext.user.email ?? sessionContext.user.display_name;
  const displayName = user?.fullName?.trim() || sessionContext.user.display_name;
  const pendingEmail = user?.emailAddresses.find((email) => email.id === pendingEmailId) ?? null;
  const otherSessions = sessions.filter((item) => item.id !== currentSessionId);

  function mirrorClerkUserToSession(nextUser: UserResource) {
    const nextEmail = nextUser.primaryEmailAddress?.emailAddress ?? sessionContext.user.email;
    const nextFullName = [nextUser.firstName, nextUser.lastName].filter(Boolean).join(" ").trim();
    const nextDisplayName = nextEmail ?? (nextFullName.length > 0 ? nextFullName : nextUser.id);

    setSessionContext({
      ...sessionContext,
      user: {
        ...sessionContext.user,
        email: nextEmail,
        first_name: nextUser.firstName ?? null,
        last_name: nextUser.lastName ?? null,
        image_url: nextUser.imageUrl ?? null,
        display_name: nextDisplayName
      }
    });
  }

  async function handleProfileSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) {
      return;
    }

    try {
      setIsSavingProfile(true);
      setProfileError(null);
      setProfileNotice(null);
      const firstName = profileDraft.firstName.trim();
      const lastName = profileDraft.lastName.trim();
      const nextUser = await user.update({
        firstName: firstName || null,
        lastName: lastName || null
      });
      mirrorClerkUserToSession(nextUser);
      setProfileNotice("Profile details updated.");
    } catch (error) {
      setProfileError(extractErrorMessage(error, "Unable to update profile details."));
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function startEmailVerification(emailAddress: EmailAddressResource) {
    await emailAddress.prepareVerification({ strategy: "email_code" });
    setPendingEmailId(emailAddress.id);
    setVerificationCode("");
    setEmailNotice(`We sent a verification code to ${emailAddress.emailAddress}.`);
  }

  async function handleAddEmail(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) {
      return;
    }

    try {
      setIsAddingEmail(true);
      setEmailError(null);
      setEmailNotice(null);
      const normalizedEmail = emailDraft.trim();
      if (!normalizedEmail) {
        throw new Error("Enter an email address first.");
      }

      const createdEmail = await createEmailAddress(normalizedEmail);
      if (!createdEmail) {
        throw new Error("Unable to create that email address.");
      }

      await user.reload();
      const nextEmail = user.emailAddresses.find((item) => item.id === createdEmail.id);
      if (!nextEmail) {
        throw new Error("The new email address could not be loaded.");
      }

      await startEmailVerification(nextEmail);
      setEmailDraft("");
    } catch (error) {
      setEmailError(extractErrorMessage(error, "Unable to add that email address."));
    } finally {
      setIsAddingEmail(false);
    }
  }

  async function handleVerifyEmail(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user || !pendingEmail) {
      return;
    }

    try {
      setIsVerifyingEmail(true);
      setEmailError(null);
      setEmailNotice(null);
      const attempt = await pendingEmail.attemptVerification({ code: verificationCode.trim() });
      if (attempt.verification.status !== "verified") {
        throw new Error("The verification code is still pending. Try again.");
      }

      const nextUser = await makePrimaryEmail(attempt.id);
      if (!nextUser) {
        throw new Error("The verified email could not be made primary.");
      }

      await user.reload();
      mirrorClerkUserToSession(nextUser);
      setPendingEmailId(null);
      setVerificationCode("");
      setEmailNotice("Primary email updated.");
    } catch (error) {
      setEmailError(extractErrorMessage(error, "Unable to verify that email address."));
    } finally {
      setIsVerifyingEmail(false);
    }
  }

  async function handleMakePrimary(emailAddressId: string) {
    if (!user) {
      return;
    }

    try {
      setEmailActionId(emailAddressId);
      setEmailError(null);
      setEmailNotice(null);
      const nextUser = await makePrimaryEmail(emailAddressId);
      if (!nextUser) {
        throw new Error("Unable to update the primary email address.");
      }

      await user.reload();
      mirrorClerkUserToSession(nextUser);
      setEmailNotice("Primary email updated.");
    } catch (error) {
      setEmailError(extractErrorMessage(error, "Unable to change the primary email address."));
    } finally {
      setEmailActionId(null);
    }
  }

  async function handleRemoveEmail(emailAddress: EmailAddressResource) {
    if (!user) {
      return;
    }

    try {
      setEmailActionId(emailAddress.id);
      setEmailError(null);
      setEmailNotice(null);
      await emailAddress.destroy();
      await user.reload();
      if (pendingEmailId === emailAddress.id) {
        setPendingEmailId(null);
        setVerificationCode("");
      }
      setEmailNotice("Email address removed.");
    } catch (error) {
      setEmailError(extractErrorMessage(error, "Unable to remove that email address."));
    } finally {
      setEmailActionId(null);
    }
  }

  async function handlePasswordSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user) {
      return;
    }

    try {
      setIsUpdatingPassword(true);
      setPasswordError(null);
      setPasswordNotice(null);

      if (passwordDraft.newPassword.trim().length === 0) {
        throw new Error("Enter a new password.");
      }
      if (passwordDraft.newPassword !== passwordDraft.confirmPassword) {
        throw new Error("New password and confirmation do not match.");
      }
      if (user.passwordEnabled && passwordDraft.currentPassword.trim().length === 0) {
        throw new Error("Enter your current password.");
      }

      await updatePassword({
        currentPassword: user.passwordEnabled ? passwordDraft.currentPassword.trim() : undefined,
        newPassword: passwordDraft.newPassword.trim(),
        signOutOfOtherSessions
      });

      setPasswordDraft({
        currentPassword: "",
        newPassword: "",
        confirmPassword: ""
      });
      setPasswordNotice(user.passwordEnabled ? "Password updated." : "Password created.");
      if (signOutOfOtherSessions) {
        await loadSessions();
      }
    } catch (error) {
      setPasswordError(extractErrorMessage(error, "Unable to update the password."));
    } finally {
      setIsUpdatingPassword(false);
    }
  }

  async function handleRevokeSession(sessionId: string) {
    const target = sessions.find((item) => item.id === sessionId);
    if (!target) {
      return;
    }

    try {
      setSessionActionId(sessionId);
      setSessionsError(null);
      setSessionsNotice(null);
      await target.revoke();
      await loadSessions();
      setSessionsNotice("Device signed out.");
    } catch (error) {
      setSessionsError(extractErrorMessage(error, "Unable to sign out that device."));
    } finally {
      setSessionActionId(null);
    }
  }

  async function handleRevokeOtherSessions() {
    if (otherSessions.length === 0) {
      return;
    }

    try {
      setSessionActionId("all-other-sessions");
      setSessionsError(null);
      setSessionsNotice(null);
      await Promise.all(otherSessions.map((item) => item.revoke()));
      await loadSessions();
      setSessionsNotice("Signed out of other sessions.");
    } catch (error) {
      setSessionsError(extractErrorMessage(error, "Unable to sign out of other sessions."));
    } finally {
      setSessionActionId(null);
    }
  }

  async function handleCopyJoinCode() {
    if (!joinCode) {
      return;
    }

    try {
      await navigator.clipboard.writeText(joinCode);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  async function handleLeaveOrganization() {
    try {
      setIsLeaving(true);
      setLeaveError(null);
      const response = await leaveCurrentOrganization();
      setSessionContext(response.session_context);
      setLeaveConfirmOpen(false);
      router.push(
        response.session_context.onboarding_status === "approved" ? "/dashboard" : "/onboarding"
      );
      router.refresh();
    } catch (error) {
      setLeaveError(extractErrorMessage(error, "Unable to leave the organization."));
    } finally {
      setIsLeaving(false);
    }
  }

  if (!isLoaded) {
    return (
      <>
        <PageHeader
          title="Account settings"
          description="Manage your profile, sign-in methods, devices, and workspace access in one place."
        />
        <SettingsSkeleton />
      </>
    );
  }

  if (!isSignedIn || !user) {
    return (
      <>
        <PageHeader
          title="Account settings"
          description="Manage your profile, sign-in methods, devices, and workspace access in one place."
        />
        <Card>
          <CardContent className="p-6">
            <p className="text-sm text-muted-foreground">You must be signed in to access this page.</p>
          </CardContent>
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Account settings"
        description="Manage your profile, sign-in methods, devices, and workspace access in one place."
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_360px]">
        <div className="space-y-5">
          <Card>
            <CardContent className="grid gap-4 p-5 sm:grid-cols-2 xl:grid-cols-4">
              <SummaryField label="Primary email" value={emailLabel} className="break-all" />
              <SummaryField label="Display name" value={displayName} />
              <SummaryField label="Organization" value={organization?.name ?? "No organization"} />
              <SummaryField label="Role" value={membership?.role ?? "No role"} className="capitalize" />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border px-5 py-4">
              <CardTitle className="text-base font-semibold tracking-normal">Profile</CardTitle>
              <CardDescription>Keep your profile details up to date.</CardDescription>
            </CardHeader>
            <CardContent className="p-5">
              <form className="space-y-4" onSubmit={handleProfileSubmit}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <FieldBlock label="First name" htmlFor="first-name">
                    <Input
                      id="first-name"
                      value={profileDraft.firstName}
                      onChange={(event) =>
                        setProfileDraft((current) => ({ ...current, firstName: event.target.value }))
                      }
                      className="border-border bg-background/70"
                    />
                  </FieldBlock>
                  <FieldBlock label="Last name" htmlFor="last-name">
                    <Input
                      id="last-name"
                      value={profileDraft.lastName}
                      onChange={(event) =>
                        setProfileDraft((current) => ({ ...current, lastName: event.target.value }))
                      }
                      className="border-border bg-background/70"
                    />
                  </FieldBlock>
                </div>

                <InlineMessage variant="success" message={profileNotice} />
                <InlineMessage variant="error" message={profileError} />

                <div className="flex justify-end">
                  <Button type="submit" disabled={isSavingProfile}>
                    {isSavingProfile ? <LoaderCircle className="animate-spin" /> : null}
                    Save profile
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border px-5 py-4">
              <CardTitle className="text-base font-semibold tracking-normal">Email addresses</CardTitle>
              <CardDescription>
                Add another email address and choose which one you sign in with.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5 p-5">
              <div className="rounded-md border border-border/80 bg-background/40">
                {user.emailAddresses.map((email, index) => {
                  const isPrimary = email.id === user.primaryEmailAddressId;
                  const isVerified = email.verification.status === "verified";
                  const isBusy = emailActionId === email.id;

                  return (
                    <div key={email.id}>
                      <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="truncate text-sm font-medium text-foreground">
                              {email.emailAddress}
                            </div>
                            {isPrimary ? (
                              <Badge variant="outline" className="border-primary/25 bg-primary/10 text-primary">
                                Primary
                              </Badge>
                            ) : null}
                            <Badge
                              variant="outline"
                              className={cn(
                                "border-border bg-background/80",
                                isVerified ? "text-emerald-300" : "text-amber-300"
                              )}
                            >
                              {isVerified ? "Verified" : "Pending"}
                            </Badge>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          {!isPrimary && isVerified ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={isBusy}
                              onClick={() => void handleMakePrimary(email.id)}
                            >
                              {isBusy ? <LoaderCircle className="animate-spin" /> : <CheckCircle2 />}
                              Make primary
                            </Button>
                          ) : null}

                          {!isPrimary ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={isBusy}
                              onClick={() => void handleRemoveEmail(email)}
                            >
                              {isBusy ? <LoaderCircle className="animate-spin" /> : <Trash2 />}
                              Remove
                            </Button>
                          ) : null}
                        </div>
                      </div>
                      {index < user.emailAddresses.length - 1 ? <Separator className="bg-border/80" /> : null}
                    </div>
                  );
                })}
              </div>

              <form className="space-y-4" onSubmit={handleAddEmail}>
                <FieldBlock label="Add new primary email" htmlFor="new-email">
                  <Input
                    id="new-email"
                    type="email"
                    placeholder="you@company.com"
                    value={emailDraft}
                    onChange={(event) => setEmailDraft(event.target.value)}
                    className="border-border bg-background/70"
                  />
                </FieldBlock>
                <div className="flex justify-end">
                  <Button type="submit" disabled={isAddingEmail}>
                    {isAddingEmail ? <LoaderCircle className="animate-spin" /> : <Mail />}
                    Add email
                  </Button>
                </div>
              </form>

              {pendingEmail ? (
                <form
                  className="rounded-md border border-border/80 bg-background/35 p-4"
                  onSubmit={handleVerifyEmail}
                >
                  <div className="text-sm font-medium text-foreground">Verify {pendingEmail.emailAddress}</div>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    Enter the code sent to this inbox. After verification, you can make it your primary email.
                  </p>
                  <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                    <FieldBlock label="Verification code" htmlFor="email-verification-code">
                      <Input
                        id="email-verification-code"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        value={verificationCode}
                        onChange={(event) => setVerificationCode(event.target.value)}
                        className="border-border bg-background/70"
                      />
                    </FieldBlock>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        disabled={isVerifyingEmail}
                        onClick={() => void startEmailVerification(pendingEmail)}
                      >
                        Resend code
                      </Button>
                      <Button type="submit" disabled={isVerifyingEmail}>
                        {isVerifyingEmail ? <LoaderCircle className="animate-spin" /> : null}
                        Verify email
                      </Button>
                    </div>
                  </div>
                </form>
              ) : null}

              <InlineMessage variant="success" message={emailNotice} />
              <InlineMessage variant="error" message={emailError} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border px-5 py-4">
              <CardTitle className="text-base font-semibold tracking-normal">
                {user.passwordEnabled ? "Change password" : "Create password"}
              </CardTitle>
              <CardDescription>
                {user.passwordEnabled
                  ? "Update your password and optionally sign out the rest of your devices."
                  : "This account signs in without a password today. Add one here for a fallback sign-in method."}
              </CardDescription>
            </CardHeader>
            <CardContent className="p-5">
              <form className="space-y-4" onSubmit={handlePasswordSubmit}>
                {user.passwordEnabled ? (
                  <FieldBlock label="Current password" htmlFor="current-password">
                    <PasswordInput
                      id="current-password"
                      autoComplete="current-password"
                      value={passwordDraft.currentPassword}
                      onChange={(event) =>
                        setPasswordDraft((current) => ({
                          ...current,
                          currentPassword: event.target.value
                        }))
                      }
                      className="border-border bg-background/70"
                    />
                  </FieldBlock>
                ) : null}

                <div className="grid gap-4 sm:grid-cols-2">
                  <FieldBlock label="New password" htmlFor="new-password">
                    <PasswordInput
                      id="new-password"
                      autoComplete="new-password"
                      value={passwordDraft.newPassword}
                      onChange={(event) =>
                        setPasswordDraft((current) => ({
                          ...current,
                          newPassword: event.target.value
                        }))
                      }
                      className="border-border bg-background/70"
                    />
                  </FieldBlock>
                  <FieldBlock label="Confirm password" htmlFor="confirm-password">
                    <PasswordInput
                      id="confirm-password"
                      autoComplete="new-password"
                      value={passwordDraft.confirmPassword}
                      onChange={(event) =>
                        setPasswordDraft((current) => ({
                          ...current,
                          confirmPassword: event.target.value
                        }))
                      }
                      className="border-border bg-background/70"
                    />
                  </FieldBlock>
                </div>

                <label className="flex items-center gap-3 rounded-md border border-border/80 bg-background/35 px-3 py-3 text-sm text-foreground">
                  <input
                    type="checkbox"
                    checked={signOutOfOtherSessions}
                    onChange={(event) => setSignOutOfOtherSessions(event.target.checked)}
                    className="size-4 rounded border-border bg-background accent-[#29b7b1]"
                  />
                  Sign out of other active sessions after the password changes
                </label>

                <InlineMessage variant="success" message={passwordNotice} />
                <InlineMessage variant="error" message={passwordError} />

                <div className="flex justify-end">
                  <Button type="submit" disabled={isUpdatingPassword}>
                    {isUpdatingPassword ? <LoaderCircle className="animate-spin" /> : <ShieldCheck />}
                    {user.passwordEnabled ? "Update password" : "Create password"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border px-5 py-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle className="text-base font-semibold tracking-normal">Active sessions</CardTitle>
                  <CardDescription>
                    Review signed-in devices and remove any you no longer trust.
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="ghost" size="sm" onClick={() => void loadSessions()} disabled={isLoadingSessions}>
                    {isLoadingSessions ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
                    Refresh
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleRevokeOtherSessions()}
                    disabled={otherSessions.length === 0 || sessionActionId === "all-other-sessions"}
                  >
                    {sessionActionId === "all-other-sessions" ? (
                      <LoaderCircle className="animate-spin" />
                    ) : (
                      <LogOut />
                    )}
                    Sign out others
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 p-5">
              <InlineMessage variant="success" message={sessionsNotice} />
              <InlineMessage variant="error" message={sessionsError} />

              {isLoadingSessions ? (
                <div className="text-sm text-muted-foreground">Loading signed-in devices...</div>
              ) : sessions.length === 0 ? (
                <div className="text-sm text-muted-foreground">No active sessions found.</div>
              ) : (
                <div className="rounded-md border border-border/80 bg-background/40">
                  {sessions.map((item, index) => {
                    const isCurrent = item.id === currentSessionId;
                    const isBusy = sessionActionId === item.id;
                    return (
                      <div key={item.id}>
                        <div className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="text-sm font-medium text-foreground">
                                {describeSession(item)}
                              </div>
                              {isCurrent ? (
                                <Badge
                                  variant="outline"
                                  className="border-primary/25 bg-primary/10 text-primary"
                                >
                                  Current
                                </Badge>
                              ) : null}
                            </div>
                            <div className="mt-1 text-sm text-muted-foreground">
                              Last active {formatDate(item.lastActiveAt)}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground/80">
                              {formatSessionLocation(item)}
                            </div>
                          </div>

                          {!isCurrent ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={isBusy}
                              onClick={() => void handleRevokeSession(item.id)}
                            >
                              {isBusy ? <LoaderCircle className="animate-spin" /> : <LogOut />}
                              Sign out
                            </Button>
                          ) : null}
                        </div>
                        {index < sessions.length - 1 ? <Separator className="bg-border/80" /> : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader className="border-b border-border px-5 py-4">
              <CardTitle className="text-base font-semibold tracking-normal">Security overview</CardTitle>
              <CardDescription>Quick readouts from your account security settings.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 p-5">
              <SecurityRow
                label="Password"
                value={user.passwordEnabled ? "Enabled" : "Not set"}
                detail={
                  user.passwordEnabled
                    ? "You can sign in with a password."
                    : "This account currently relies on a non-password method."
                }
              />
              <SecurityRow
                label="Two-factor"
                value={user.twoFactorEnabled ? "Enabled" : "Not enabled"}
                detail={
                  user.twoFactorEnabled
                    ? "A second factor is currently protecting this account."
                    : "No second factor is active on this account yet."
                }
              />
              <SecurityRow
                label="Recovery codes"
                value={user.backupCodeEnabled ? "Available" : "Not generated"}
                detail={
                  user.backupCodeEnabled
                    ? "Recovery codes exist for fallback account access."
                    : "No backup recovery codes are available yet."
                }
              />
              <SecurityRow
                label="Sessions"
                value={`${sessions.length}`}
                detail="Active devices currently signed into this account."
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b border-border px-5 py-4">
              <CardTitle className="text-base font-semibold tracking-normal">Workspace access</CardTitle>
              <CardDescription>
                Your workspace membership and invite tools live here.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5 p-5">
              <div className="grid gap-3 rounded-md border border-border/80 bg-background/40 px-4 py-3">
                <SummaryField label="Organization" value={organization?.name ?? "No organization"} />
                <SummaryField
                  label={joinCode ? "Join code" : "Owner"}
                  value={joinCode ?? organization?.admin_name ?? "Unassigned"}
                  className={joinCode ? "font-mono uppercase tracking-[0.18em]" : undefined}
                />
              </div>

              {isAdmin ? (
                <div className="rounded-md border border-border/80 bg-background/35 p-4">
                  <div className="text-sm font-medium text-foreground">Organization settings</div>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    Open settings to manage members, stores, and printing partners.
                  </p>
                  <Button className="mt-4" variant="outline" onClick={() => router.push("/settings")}>
                    Open settings
                  </Button>
                </div>
              ) : null}

              {joinCode ? (
                <div className="rounded-md border border-border/80 bg-background/35 p-4">
                  <div className="text-sm font-medium text-foreground">Copy join code</div>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    Share this code when another member should request access to the workspace.
                  </p>
                  <Button className="mt-4" variant="outline" onClick={() => void handleCopyJoinCode()}>
                    <Copy />
                    {copyState === "copied" ? "Copied" : "Copy code"}
                  </Button>
                  {copyState === "failed" ? (
                    <p className="mt-3 text-sm text-red-300">Unable to copy the join code.</p>
                  ) : null}
                </div>
              ) : null}

              <div className="rounded-md border border-red-500/20 bg-red-500/5 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <LogOut className="size-4 text-red-300" />
                  Leave current organization
                </div>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {isAdmin
                    ? "If another approved member exists, Velora transfers admin ownership before you leave. If you are the only approved member, the action is blocked."
                    : "You will lose access to this workspace and return to onboarding until you join or create another organization."}
                </p>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className="border-red-500/30 bg-transparent text-red-300 hover:bg-red-500/10 hover:text-red-200"
                    onClick={() => {
                      setLeaveConfirmOpen((current) => !current);
                      setLeaveError(null);
                    }}
                    disabled={isLeaving}
                  >
                    {leaveConfirmOpen ? "Cancel" : "Leave organization"}
                  </Button>
                </div>

                {leaveConfirmOpen ? (
                  <div className="mt-4 rounded-md border border-red-500/20 bg-black/20 p-3">
                    <p className="text-sm leading-6 text-muted-foreground">
                      Confirm leaving <span className="text-foreground">{organization?.name}</span>. This
                      removes your current workspace membership immediately.
                    </p>
                    {leaveError ? <p className="mt-3 text-sm text-red-300">{leaveError}</p> : null}
                    <div className="mt-4 flex flex-wrap justify-end gap-2">
                      <Button variant="ghost" onClick={() => setLeaveConfirmOpen(false)} disabled={isLeaving}>
                        Keep access
                      </Button>
                      <Button
                        className="border-red-500 bg-red-500 text-white hover:bg-red-500/90"
                        onClick={() => void handleLeaveOrganization()}
                        disabled={isLeaving}
                      >
                        {isLeaving ? <LoaderCircle className="animate-spin" /> : null}
                        Confirm leave
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function FieldBlock({
  label,
  htmlFor,
  children
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor} className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function SecurityRow({
  label,
  value,
  detail
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-md border border-border/80 bg-background/35 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-sm font-medium text-foreground">{value}</div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{detail}</p>
    </div>
  );
}

function SummaryField({
  label,
  value,
  className
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </div>
      <div className={cn("mt-1 truncate text-sm font-medium text-foreground", className)}>{value}</div>
    </div>
  );
}

function InlineMessage({
  variant,
  message
}: {
  variant: "success" | "error";
  message: string | null;
}) {
  if (!message) {
    return null;
  }

  return (
    <div
      className={cn(
        "rounded-md px-3 py-2 text-sm",
        variant === "success"
          ? "border border-emerald-500/20 bg-emerald-500/10 text-emerald-200"
          : "border border-destructive/30 bg-destructive/10 text-destructive"
      )}
    >
      {message}
    </div>
  );
}

function describeSession(session: SessionWithActivitiesResource) {
  const browserName = session.latestActivity?.browserName?.trim();
  const browserVersion = session.latestActivity?.browserVersion?.trim();
  const deviceType = session.latestActivity?.deviceType?.trim();
  const pieces = [deviceType, browserName, browserVersion].filter(Boolean);

  if (pieces.length > 0) {
    return pieces.join(" • ");
  }

  return "Browser session";
}

function formatSessionLocation(session: SessionWithActivitiesResource) {
  const city = session.latestActivity?.city?.trim();
  const country = session.latestActivity?.country?.trim();
  const ipAddress = session.latestActivity?.ipAddress?.trim();
  return [city, country, ipAddress].filter(Boolean).join(" • ") || "Location unavailable";
}

function formatDate(value: Date) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(value);
}

function extractErrorMessage(error: unknown, fallback: string) {
  if (isClerkRuntimeError(error) && isReverificationCancelledError(error)) {
    return "Verification was cancelled before the change completed.";
  }

  if (typeof error === "object" && error !== null && "errors" in error) {
    const candidate = (error as { errors?: Array<{ longMessage?: string; message?: string }> }).errors?.[0];
    if (candidate?.longMessage) {
      return candidate.longMessage;
    }
    if (candidate?.message) {
      return candidate.message;
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return fallback;
}
