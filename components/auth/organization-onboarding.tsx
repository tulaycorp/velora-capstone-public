"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Building2, KeyRound } from "lucide-react";
import { AuthSignOutControl } from "@/components/auth/auth-page-controls";
import { AppSessionContextProvider, useAppSessionContext } from "@/components/auth/app-session-context";
import { Button } from "@/components/ui/button";
import { CodeInput } from "@/components/ui/code-input";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createOrganization,
  createOrganizationJoinRequest,
  type SessionContext
} from "@/lib/backend-api";
import { cn } from "@/lib/utils";

type AccessPath = "create" | "join";

const accessPathOptions = [
  {
    id: "create" as const,
    eyebrow: "Create workspace",
    title: "Start new",
    description: "Set up the workspace yourself and manage members, stores, and connections.",
    detailTitle: "Name the organization.",
    detailDescription:
      "Only the organization name is required here. You can refine the rest after the workspace opens.",
    fieldLabel: "Organization name",
    fieldPlaceholder: "Nimbus Press",
    buttonLabel: "Create organization",
    helperCopy: "You become the admin right away.",
    icon: Building2
  },
  {
    id: "join" as const,
    eyebrow: "Request access",
    title: "Join existing",
    description: "Use a workspace code from an admin, then wait for approval.",
    detailTitle: "Enter the join code.",
    detailDescription:
      "Your request stays pending until a workspace admin approves it.",
    fieldLabel: "Organization code",
    fieldPlaceholder: "VELORA01",
    buttonLabel: "Request access",
    helperCopy: "Ask a workspace admin for the code they share with collaborators.",
    icon: KeyRound
  }
] as const;

const authInputClassName =
  "h-14 rounded-none border-x-0 border-t-0 border-b border-white/12 bg-transparent px-0 text-base text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-0 focus-visible:ring-offset-0";

const authButtonClassName =
  "h-12 rounded-none px-5 text-sm uppercase tracking-[0.28em]";

function OnboardingContent() {
  const router = useRouter();
  const { sessionContext, refreshSessionContext, setSessionContext } = useAppSessionContext();
  const [organizationName, setOrganizationName] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [selectedPath, setSelectedPath] = useState<AccessPath>("create");
  const [error, setError] = useState<string | null>(null);
  const [createPending, startCreateTransition] = useTransition();
  const [joinPending, startJoinTransition] = useTransition();
  const [refreshPending, startRefreshTransition] = useTransition();

  function handleCreateOrganization(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    startCreateTransition(async () => {
      try {
        await createOrganization({ name: organizationName.trim() });
        const nextContext = await refreshSessionContext();
        if (nextContext.onboarding_status === "approved") {
          router.push("/dashboard");
          router.refresh();
          return;
        }
        setSessionContext(nextContext);
      } catch (createError) {
        setError(
          createError instanceof Error
            ? createError.message
            : "Unable to create the workspace right now."
        );
      }
    });
  }

  function handleJoinOrganization(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    startJoinTransition(async () => {
      try {
        await createOrganizationJoinRequest({ join_code: joinCode.trim().toUpperCase() });
        const nextContext = await refreshSessionContext();
        setSessionContext(nextContext);
        router.refresh();
      } catch (joinError) {
        setError(
          joinError instanceof Error
            ? joinError.message
            : "Unable to send the access request."
        );
      }
    });
  }

  function handleRefreshPendingState() {
    setError(null);
    startRefreshTransition(async () => {
      try {
        const nextContext = await refreshSessionContext();
        if (nextContext.onboarding_status === "approved") {
          router.push("/dashboard");
          router.refresh();
        }
      } catch (refreshError) {
        setError(
          refreshError instanceof Error
            ? refreshError.message
            : "Unable to refresh your access status."
        );
      }
    });
  }

  const pendingOrganization = sessionContext.pending_join_request?.organization_name ?? "your organization";
  const activePath = accessPathOptions.find((option) => option.id === selectedPath) ?? accessPathOptions[0];

  return (
    <main className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_top,_rgba(27,173,174,0.14),_transparent_28%),radial-gradient(circle_at_88%_18%,_rgba(112,118,255,0.08),_transparent_24%),linear-gradient(180deg,_#06080c_0%,_#0a0d13_42%,_#090b10_100%)] px-6 py-8 text-foreground md:px-10">
      <div className="pointer-events-none absolute inset-0">
        <div className="auth-drift absolute -left-24 top-20 h-80 w-80 rounded-full bg-primary/8 blur-3xl" />
        <div className="absolute inset-y-0 left-[60%] hidden w-px bg-white/8 lg:block" />
      </div>
      <div className="relative mx-auto grid min-h-[calc(100vh-4rem)] max-w-7xl gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(420px,520px)]">
        <section className="flex flex-col justify-between py-4">
          <div className="auth-rise">
            <Link href="/" className="inline-flex items-center gap-3">
              <span className="auth-display text-[2.15rem] leading-none text-foreground">Velora</span>
              <span className="mt-1 text-[10px] uppercase tracking-[0.32em] text-muted-foreground">
                Organization access
              </span>
            </Link>
            <div className="mt-16 max-w-3xl">
              <div className="text-[10px] uppercase tracking-[0.34em] text-primary/75">Workspace approval</div>
              <h1 className="auth-display mt-5 max-w-3xl text-5xl leading-[0.92] text-foreground md:text-7xl lg:text-[5.35rem]">
                {sessionContext.onboarding_status === "pending"
                  ? "Your access request is waiting for an organization admin."
                  : "Choose how you want to enter Velora."}
              </h1>
              <p className="mt-6 max-w-xl text-sm leading-7 text-muted-foreground md:text-base">
                {sessionContext.onboarding_status === "pending"
                  ? `You are signed in as ${sessionContext.user.display_name}. Once the admin approves your request, the workspace will unlock automatically.`
                  : `You are signed in as ${sessionContext.user.display_name}. Create a new organization if you are setting up Velora for the first time, or request access to an existing one with its join code.`}
              </p>
            </div>
          </div>

          <div className="auth-rise-delay grid gap-4 pt-10 text-sm text-muted-foreground md:grid-cols-3">
            {[
              ["Sign in", "Your account gets you in the door, then the workspace decides access."],
              ["Approval", "Workspace admins decide who can enter and who stays pending."],
              ["Admin controls", "Admins manage members, stores, and connection settings."]
            ].map(([label, copy]) => (
              <div key={label} className="border-t border-white/10 pt-4">
                <div className="text-[10px] uppercase tracking-[0.28em] text-primary/75">{label}</div>
                <p className="mt-3 leading-6 text-muted-foreground">{copy}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="flex py-4">
          <div className="relative z-10 flex w-full flex-col justify-center">
            {sessionContext.auth_mode === "clerk" ? (
              <div className="mb-8 flex justify-start lg:justify-end">
                <AuthSignOutControl />
              </div>
            ) : null}
            {error ? (
              <div className="mb-6 border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {error}
              </div>
            ) : null}

            {sessionContext.onboarding_status === "pending" ? (
              <div className="max-w-lg space-y-10">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
                    Pending approval
                  </div>
                  <div className="auth-display mt-4 text-4xl leading-none text-foreground">
                    {pendingOrganization}
                  </div>
                  <p className="mt-5 max-w-md text-sm leading-7 text-muted-foreground">
                    Access requests need approval. The workspace stays locked until an admin accepts your request.
                  </p>
                </div>

                <div className="grid gap-3 border-y border-white/8 py-6 text-sm text-muted-foreground">
                  <div className="flex items-start justify-between gap-4">
                    <span>1</span>
                    <p className="flex-1 leading-6">An organization admin reviews the request.</p>
                  </div>
                  <div className="flex items-start justify-between gap-4">
                    <span>2</span>
                    <p className="flex-1 leading-6">
                      Approved members can use the workspace, while admin tools stay with admins.
                    </p>
                  </div>
                  <div className="flex items-start justify-between gap-4">
                    <span>3</span>
                    <p className="flex-1 leading-6">
                      Store connections and member approvals stay with admins.
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    className={authButtonClassName}
                    onClick={handleRefreshPendingState}
                    disabled={refreshPending}
                  >
                    <ArrowRight className={refreshPending ? "animate-pulse" : ""} />
                    Check access again
                  </Button>
                  <div className="text-sm text-muted-foreground">
                    Refresh after the admin approves the request.
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-8">
                <div className="space-y-4">
                  <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
                    Step 1
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {accessPathOptions.map((option) => {
                      const isSelected = selectedPath === option.id;
                      const OptionIcon = option.icon;

                      return (
                        <button
                          key={option.id}
                          type="button"
                          aria-pressed={isSelected}
                          onClick={() => {
                            setError(null);
                            setSelectedPath(option.id);
                          }}
                          className={cn(
                            "group flex min-h-[18.5rem] flex-col border px-6 py-6 text-left transition-all",
                            isSelected
                              ? "border-primary/55"
                              : "border-white/10 hover:border-white/22"
                          )}
                        >
                          <div className="flex items-center gap-3">
                            <OptionIcon
                              className={cn(
                                "size-4 transition-colors",
                                isSelected ? "text-primary" : "text-muted-foreground"
                              )}
                            />
                            <span
                              className={cn(
                                "text-[10px] uppercase tracking-[0.24em]",
                                isSelected ? "text-primary" : "text-muted-foreground"
                              )}
                            >
                              {option.eyebrow}
                            </span>
                          </div>
                          <div className="mt-8 flex flex-1 flex-col">
                            <div className="auth-display text-[2rem] leading-[0.95] text-foreground">
                              {option.title}
                            </div>
                            <p className="mt-4 max-w-[18rem] text-sm leading-7 text-muted-foreground">
                              {option.description}
                            </p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="border-t border-white/10 pt-8">
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
                      Step 2
                    </div>
                    <div className="auth-display mt-4 text-4xl leading-none text-foreground">
                      {activePath.detailTitle}
                    </div>
                    <p className="mt-5 max-w-md text-sm leading-7 text-muted-foreground">
                      {activePath.detailDescription}
                    </p>
                  </div>

                  {selectedPath === "create" ? (
                    <form className="mt-8 max-w-lg space-y-6" onSubmit={handleCreateOrganization}>
                      <div className="space-y-2">
                        <Label htmlFor="organization-name">{activePath.fieldLabel}</Label>
                        <Input
                          id="organization-name"
                          value={organizationName}
                          onChange={(event) => setOrganizationName(event.target.value)}
                          placeholder={activePath.fieldPlaceholder}
                          autoComplete="organization"
                          className={authInputClassName}
                        />
                      </div>
                      <div className="flex flex-wrap items-center gap-4">
                        <Button
                          type="submit"
                          className={authButtonClassName}
                          disabled={createPending || organizationName.trim().length === 0}
                        >
                          <ArrowRight />
                          {createPending ? "Creating organization..." : activePath.buttonLabel}
                        </Button>
                        <p className="text-sm text-muted-foreground">{activePath.helperCopy}</p>
                      </div>
                    </form>
                  ) : (
                    <form className="mt-8 max-w-lg space-y-6" onSubmit={handleJoinOrganization}>
                      <div className="space-y-2">
                        <Label htmlFor="organization-code">{activePath.fieldLabel}</Label>
                        <CodeInput
                          id="organization-code"
                          codeKind="alphanumeric"
                          maxLength={8}
                          value={joinCode}
                          onChange={(event) => setJoinCode(event.target.value.toUpperCase())}
                          placeholder={activePath.fieldPlaceholder}
                          className={authInputClassName}
                        />
                      </div>
                      <div className="flex flex-wrap items-center gap-4">
                        <Button
                          type="submit"
                          className={authButtonClassName}
                          disabled={joinPending || joinCode.trim().length === 0}
                        >
                          <ArrowRight />
                          {joinPending ? "Submitting request..." : activePath.buttonLabel}
                        </Button>
                        <p className="text-sm text-muted-foreground">{activePath.helperCopy}</p>
                      </div>
                    </form>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}

export function OrganizationOnboarding({
  initialSessionContext
}: {
  initialSessionContext: SessionContext;
}) {
  return (
    <AppSessionContextProvider initialSessionContext={initialSessionContext}>
      <OnboardingContent />
    </AppSessionContextProvider>
  );
}
