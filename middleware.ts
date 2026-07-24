import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { resolveFrontendAuthMode } from "@/lib/clerk-config";
import {
  buildContentSecurityPolicy,
  CONTENT_SECURITY_POLICY_NONCE_HEADER,
  createContentSecurityPolicyNonce,
  isHtmlDocumentRequest,
  resolveContentSecurityPolicyProfile,
} from "@/lib/content-security-policy";

const authMode = resolveFrontendAuthMode();

const isProtectedRoute = createRouteMatcher([
  "/onboarding(.*)",
  "/dashboard(.*)",
  "/product-studio(.*)",
  "/blueprints(.*)",
  "/products(.*)",
  "/orders(.*)",
  "/analytics(.*)",
  "/account(.*)",
  "/settings(.*)",
  "/api/backend(.*)"
]);

export default clerkMiddleware(async (auth, req) => {
  const shouldApplyRuntimeCsp = isHtmlDocumentRequest({
    method: req.method,
    accept: req.headers.get("accept"),
    secFetchDest: req.headers.get("sec-fetch-dest"),
  });
  const requestHeaders = new Headers(req.headers);
  const nonce = shouldApplyRuntimeCsp ? createContentSecurityPolicyNonce() : null;

  if (nonce) {
    requestHeaders.set(CONTENT_SECURITY_POLICY_NONCE_HEADER, nonce);
  }

  if (authMode === "local") {
    const response = NextResponse.next({ request: { headers: requestHeaders } });
    if (nonce) {
      response.headers.set(
        "Content-Security-Policy",
        buildContentSecurityPolicy({
          nonce,
          profile: resolveContentSecurityPolicyProfile(req.nextUrl.pathname),
        }),
      );
    }
    return response;
  }

  if (isProtectedRoute(req)) {
    await auth.protect();
  }

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  if (nonce) {
    response.headers.set(
      "Content-Security-Policy",
      buildContentSecurityPolicy({
        nonce,
        profile: resolveContentSecurityPolicyProfile(req.nextUrl.pathname),
      }),
    );
  }
  return response;
});

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/__clerk/(.*)",
    "/(api|trpc)(.*)"
  ]
};
