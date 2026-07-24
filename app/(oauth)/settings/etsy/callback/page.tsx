"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { completeEtsyOAuthCallback } from "@/lib/backend-api";
import {
  createEtsyOAuthErrorMessage,
  createEtsyOAuthSuccessMessage
} from "@/lib/etsy-oauth";

function humanizeOAuthError(error: string, description: string) {
  const normalizedError = error.trim();
  const normalizedDescription = description.trim();
  if (normalizedDescription) {
    return normalizedDescription;
  }
  if (!normalizedError) {
    return "Etsy did not return a usable authorization response.";
  }
  return normalizedError.replace(/_/g, " ");
}

function notifyParentWindow(message: ReturnType<typeof createEtsyOAuthSuccessMessage> | ReturnType<typeof createEtsyOAuthErrorMessage>) {
  if (!window.opener || window.opener.closed) {
    return false;
  }

  window.opener.postMessage(message, window.location.origin);
  return true;
}

export default function EtsyOAuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const hasStartedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const code = searchParams?.get("code")?.trim() ?? "";
  const state = searchParams?.get("state")?.trim() ?? "";
  const oauthError = searchParams?.get("error")?.trim() ?? "";
  const oauthErrorDescription = searchParams?.get("error_description")?.trim() ?? "";

  useEffect(() => {
    if (hasStartedRef.current) {
      return;
    }
    hasStartedRef.current = true;

    if (oauthError) {
      const nextError = humanizeOAuthError(oauthError, oauthErrorDescription);
      if (notifyParentWindow(createEtsyOAuthErrorMessage(nextError, state || null))) {
        window.close();
        return;
      }
      setError(nextError);
      return;
    }

    if (!code || !state) {
      const nextError = "Etsy did not return the code and state needed to finish this connection.";
      if (notifyParentWindow(createEtsyOAuthErrorMessage(nextError, state || null))) {
        window.close();
        return;
      }
      setError(nextError);
      return;
    }

    void completeEtsyOAuthCallback({ code, state })
      .then(() => {
        if (notifyParentWindow(createEtsyOAuthSuccessMessage(state))) {
          window.close();
          return;
        }

        router.replace("/settings");
        router.refresh();
      })
      .catch((callbackError) => {
        const nextError =
          callbackError instanceof Error
            ? callbackError.message
            : "Unable to finish the Etsy connection.";

        if (notifyParentWindow(createEtsyOAuthErrorMessage(nextError, state))) {
          window.close();
          return;
        }

        setError(nextError);
      });
  }, [code, oauthError, oauthErrorDescription, router, state]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 py-10">
      <div className="w-full max-w-lg rounded-xl border border-border bg-card px-5 py-5 shadow-sm">
        <div className="space-y-1">
          <p className="text-sm font-medium text-muted-foreground">Etsy account</p>
          <h1 className="text-lg font-semibold text-foreground">Finish Etsy connection</h1>
          <p className="text-sm text-muted-foreground">
            Velora is finishing the Etsy authorization and refreshing your shop mapping.
          </p>
        </div>

        <div className="mt-5">
          {error ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {error}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => router.replace("/settings")}>
                  Back to Settings
                </Button>
                <Button type="button" variant="outline" onClick={() => window.location.reload()}>
                  Reload
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <LoaderCircle className="h-4 w-4 animate-spin text-primary" />
              Finishing Etsy connection and refreshing shop discovery.
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
