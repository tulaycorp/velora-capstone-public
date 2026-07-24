import "server-only";

import { cache } from "react";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { getBackendApiBaseUrl } from "@/lib/api-base-url";
import { type SessionContext } from "@/lib/backend-api";
import { isClerkFrontendConfigured } from "@/lib/clerk-config";
import { classifySessionContextFailure, type SessionContextFailureCode } from "@/lib/session-context-failures";

const BACKEND_UNAVAILABLE_MESSAGE = `Velora backend is unavailable at ${getBackendApiBaseUrl()}. Retry in a moment.`;
const SESSION_CONTEXT_RETRY_DELAY_MS = 750;
const SESSION_CONTEXT_MAX_ATTEMPTS = 2;
const SIGN_IN_PATH = "/sign-in";

class ServerSessionContextError extends Error {
  code: SessionContextFailureCode;

  constructor(code: SessionContextFailureCode, message: string) {
    super(message);
    this.name = "ServerSessionContextError";
    this.code = code;
  }
}

function sleep(milliseconds: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

async function extractServerError(response: Response) {
  let text = "";
  try {
    text = await response.text();
  } catch {
    // Ignore read failures and use fallback text.
  }

  try {
    const payload = JSON.parse(text) as { detail?: string };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    // Ignore parse failures and use fallback text.
  }

  return text || `${response.status} ${response.statusText}`;
}

async function requestServerSessionContext(token: string | null) {
  let response: Response;

  try {
    response = await fetch(`${getBackendApiBaseUrl()}/session-context`, {
      method: "GET",
      headers: token
        ? {
            authorization: `Bearer ${token}`
          }
        : undefined,
      cache: "no-store"
    });
  } catch {
    throw new ServerSessionContextError("retryable", BACKEND_UNAVAILABLE_MESSAGE);
  }

  if (!response.ok) {
    const detail = await extractServerError(response);
    throw new ServerSessionContextError(
      classifySessionContextFailure(response.status, detail),
      detail
    );
  }

  return (await response.json()) as SessionContext;
}

async function fetchServerSessionContextImpl() {
  let token: string | null = null;

  if (isClerkFrontendConfigured()) {
    const session = await auth();
    if (!session.userId) {
      redirect(SIGN_IN_PATH);
    }

    token = await session.getToken();
    if (!token) {
      redirect(SIGN_IN_PATH);
    }
  }

  for (let attempt = 0; attempt < SESSION_CONTEXT_MAX_ATTEMPTS; attempt += 1) {
    try {
      return await requestServerSessionContext(token);
    } catch (error) {
      if (!(error instanceof ServerSessionContextError)) {
        throw error;
      }

      if (error.code === "sign_in") {
        redirect(SIGN_IN_PATH);
      }

      const hasAttemptsRemaining = attempt + 1 < SESSION_CONTEXT_MAX_ATTEMPTS;
      if (error.code === "retryable" && hasAttemptsRemaining) {
        await sleep(SESSION_CONTEXT_RETRY_DELAY_MS);
        continue;
      }

      throw error;
    }
  }

  throw new Error(BACKEND_UNAVAILABLE_MESSAGE);
}

/**
 * Fetch the session context from the backend. Uses React `cache()` so
 * multiple calls within a single server-render pass share one result.
 * The backend response is session-specific, so the underlying request
 * must stay runtime-only instead of being statically prerendered or
 * reused across users.
 */
export const fetchServerSessionContext = cache(fetchServerSessionContextImpl);
