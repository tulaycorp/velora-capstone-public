import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { getBackendApiBaseUrl } from "@/lib/api-base-url";
import {
  buildUnexpectedHtmlProxyErrorDetail,
  isUnexpectedHtmlProxyResponse
} from "@/lib/backend-proxy";
import {
  getUploadMaxRequestBytes,
  isBackendMediaUpload,
  validateKnownUploadLength
} from "@/lib/backend-upload-proxy";
import { resolveFrontendAuthMode } from "@/lib/clerk-config";
import { getOrCreateRequestId, logServerEvent } from "@/lib/server-logging";

const BACKEND_UNAVAILABLE_MESSAGE = `Velora backend is unavailable at ${getBackendApiBaseUrl()}. Start ./run.sh or the FastAPI server before continuing.`;

function buildTargetUrl(request: NextRequest, path: string[]) {
  const nextPath = path.join("/");
  const targetUrl = new URL(`${getBackendApiBaseUrl()}/${nextPath}`);
  targetUrl.search = request.nextUrl.search;
  return targetUrl;
}

function copyRequestHeaders(request: NextRequest, token: string | null, requestId: string) {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");

  if (contentType) {
    headers.set("content-type", contentType);
  }

  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  headers.set("x-request-id", requestId);
  return headers;
}

function copyResponseHeaders(response: Response, requestId: string) {
  const headers = new Headers();
  const contentType = response.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }
  headers.set("x-request-id", response.headers.get("x-request-id") ?? requestId);
  return headers;
}

function buildProxyPath(path: string[]) {
  return `/${path.join("/")}`;
}

function jsonErrorResponse(detail: string, status: number, requestId: string) {
  return Response.json(
    { detail },
    {
      status,
      headers: {
        "x-request-id": requestId
      }
    }
  );
}

async function forwardRequest(request: NextRequest, path: string[]) {
  const requestId = getOrCreateRequestId(request.headers.get("x-request-id"));
  const proxyPath = buildProxyPath(path);
  const targetUrl = buildTargetUrl(request, path);
  const startedAt = performance.now();
  let token: string | null = null;
  let actorId: string | null = null;
  const authMode = resolveFrontendAuthMode();

  if (authMode === "clerk") {
    const session = await auth();
    if (!session.userId) {
      logServerEvent("warn", "bff.request.unauthenticated", {
        request_id: requestId,
        method: request.method,
        path: proxyPath
      });
      return jsonErrorResponse("Not authenticated", 401, requestId);
    }
    actorId = session.userId;
    token = await session.getToken();
    if (!token) {
      logServerEvent("warn", "bff.request.unauthenticated", {
        request_id: requestId,
        method: request.method,
        path: proxyPath
      });
      return jsonErrorResponse("Not authenticated", 401, requestId);
    }
  }

  if (isBackendMediaUpload(path, request.method)) {
    const uploadLength = validateKnownUploadLength(
      request.headers.get("content-length"),
      getUploadMaxRequestBytes()
    );
    if (!uploadLength.allowed) {
      return jsonErrorResponse(uploadLength.detail, uploadLength.status, requestId);
    }
  }

  logServerEvent("info", "bff.request.started", {
    request_id: requestId,
    actor_id: actorId,
    method: request.method,
    path: proxyPath,
    target_path: targetUrl.pathname,
    auth_mode: authMode,
    query_present: Boolean(request.nextUrl.search),
  });

  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : request.body;

  let backendResponse: Response;

  try {
    const fetchInit: RequestInit & { duplex?: "half" } = {
      method: request.method,
      headers: copyRequestHeaders(request, token, requestId),
      body,
      cache: "no-store",
      duplex: body ? "half" : undefined
    };
    backendResponse = await fetch(targetUrl, fetchInit);
  } catch (error) {
    logServerEvent("error", "bff.request.failed", {
      request_id: requestId,
      actor_id: actorId,
      method: request.method,
      path: proxyPath,
      target_path: targetUrl.pathname,
      duration_ms: Number((performance.now() - startedAt).toFixed(2)),
      error: error instanceof Error ? error.message : BACKEND_UNAVAILABLE_MESSAGE
    });
    return jsonErrorResponse(BACKEND_UNAVAILABLE_MESSAGE, 503, requestId);
  }

  const backendResponseContentType = backendResponse.headers.get("content-type");
  if (
    isUnexpectedHtmlProxyResponse(
      backendResponse.status,
      backendResponseContentType
    )
  ) {
    const detail = buildUnexpectedHtmlProxyErrorDetail(
      targetUrl.toString(),
      backendResponse.status
    );

    logServerEvent("error", "bff.request.invalid_upstream_html", {
      request_id: requestId,
      actor_id: actorId,
      method: request.method,
      path: proxyPath,
      target_path: targetUrl.pathname,
      target_url: targetUrl.toString(),
      status_code: backendResponse.status,
      content_type: backendResponseContentType,
      duration_ms: Number((performance.now() - startedAt).toFixed(2)),
      error: detail
    });

    return jsonErrorResponse(detail, 502, requestId);
  }

  const responseBody = backendResponse.status === 204 ? null : backendResponse.body;

  logServerEvent("info", "bff.request.completed", {
    request_id: requestId,
    actor_id: actorId,
    method: request.method,
    path: proxyPath,
    target_path: targetUrl.pathname,
    status_code: backendResponse.status,
    duration_ms: Number((performance.now() - startedAt).toFixed(2))
  });

  return new Response(responseBody, {
    status: backendResponse.status,
    headers: copyResponseHeaders(backendResponse, requestId)
  });
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forwardRequest(request, path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forwardRequest(request, path);
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forwardRequest(request, path);
}

export async function PUT(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forwardRequest(request, path);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forwardRequest(request, path);
}
