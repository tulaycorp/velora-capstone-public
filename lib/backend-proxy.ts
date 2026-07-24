export function isUnexpectedHtmlProxyResponse(
  status: number,
  contentType: string | null
) {
  if (status < 400) {
    return false;
  }

  return (contentType ?? "").toLowerCase().includes("text/html");
}

export function buildForwardedRequestBody(request: Request) {
  if (request.method === "GET" || request.method === "HEAD") {
    return undefined;
  }

  return request.body ?? undefined;
}

export function buildUnexpectedHtmlProxyErrorDetail(
  targetUrl: string,
  status: number
) {
  return `Velora backend proxy expected API JSON but received an HTML ${status} from ${targetUrl}. Check VELORA_API_BASE_URL on the web app; it must point to the FastAPI service, not the Next.js frontend.`;
}
