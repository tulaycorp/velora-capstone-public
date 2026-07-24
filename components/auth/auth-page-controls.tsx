"use client";

import { useState } from "react";
import { useAuth, useClerk, useSignIn } from "@clerk/nextjs";
import { ArrowLeft, LoaderCircle, LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function AuthRouteLink({
  href,
  className,
  children
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={className}
      onClick={(event) => {
        event.preventDefault();
        window.location.assign(href);
      }}
    >
      {children}
    </Link>
  );
}

export function AuthSignOutControl({
  signOutRedirectUrl = "/sign-in",
  label = "Switch account",
  className
}: {
  signOutRedirectUrl?: string;
  label?: string;
  className?: string;
}) {
  const router = useRouter();
  const { signOut } = useClerk();
  const { userId } = useAuth();
  const [isSigningOut, setIsSigningOut] = useState(false);

  async function handleSignOut() {
    if (!userId) {
      router.push(signOutRedirectUrl);
      return;
    }

    try {
      setIsSigningOut(true);
      await signOut({ redirectUrl: signOutRedirectUrl });
    } catch {
      setIsSigningOut(false);
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => {
        void handleSignOut();
      }}
      disabled={isSigningOut}
      className={cn(
        "h-9 rounded-none border border-white/10 bg-white/[0.02] px-3 text-[10px] uppercase tracking-[0.22em] text-muted-foreground hover:border-white/18 hover:bg-white/[0.04] hover:text-foreground",
        className
      )}
    >
      {isSigningOut ? <LoaderCircle className="size-3.5 animate-spin text-primary" /> : <LogOut className="size-3.5" />}
      {isSigningOut ? "Signing out..." : label}
    </Button>
  );
}

export function AuthReturnToSignInControl({
  redirectUrl = "/sign-in",
  label = "Back to sign in",
  className
}: {
  redirectUrl?: string;
  label?: string;
  className?: string;
}) {
  const router = useRouter();
  const { signOut } = useClerk();
  const { userId } = useAuth();
  const { signIn } = useSignIn();
  const [isReturning, setIsReturning] = useState(false);

  async function handleReturnToSignIn() {
    try {
      setIsReturning(true);
      await signIn?.reset();
    } catch {
      // Fall through and still send the user back to the root sign-in route.
    }

    if (userId) {
      try {
        await signOut({ redirectUrl });
        return;
      } catch {
        setIsReturning(false);
      }
    }

    router.push(redirectUrl);
    router.refresh();
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => {
        void handleReturnToSignIn();
      }}
      disabled={isReturning}
      className={cn(
        "h-9 rounded-none border border-white/10 bg-white/[0.02] px-3 text-[10px] uppercase tracking-[0.22em] text-muted-foreground hover:border-white/18 hover:bg-white/[0.04] hover:text-foreground",
        className
      )}
    >
      {isReturning ? (
        <LoaderCircle className="size-3.5 animate-spin text-primary" />
      ) : (
        <ArrowLeft className="size-3.5" />
      )}
      {isReturning ? "Returning..." : label}
    </Button>
  );
}
