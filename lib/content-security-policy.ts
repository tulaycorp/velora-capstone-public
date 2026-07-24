export const CONTENT_SECURITY_POLICY_NONCE_HEADER = "x-velora-csp-nonce";

const CLERK_SOURCES = [
  "https://*.clerk.accounts.dev",
  "https://*.clerk.dev",
  "https://*.clerk.com",
];

const CLERK_WEBSOCKET_SOURCES = [
  "wss://*.clerk.accounts.dev",
  "wss://*.clerk.dev",
  "wss://*.clerk.com",
];

const CLERK_IMAGE_SOURCES = ["https://images.clerk.com"];
const CLOUDFLARE_TURNSTILE_SOURCES = ["https://challenges.cloudflare.com"];
const PUBLIC_AUTH_ROUTE_PREFIXES = ["/sign-in", "/sign-up", "/__clerk"];

export type ContentSecurityPolicyProfile = "public" | "workspace";

type BuildContentSecurityPolicyOptions = {
  nonce: string;
  profile: ContentSecurityPolicyProfile;
  isDevelopment?: boolean;
};

function formatDirective(name: string, values: string[]) {
  return `${name} ${values.join(" ")}`;
}

export function isHtmlDocumentRequest(input: {
  method: string;
  accept: string | null | undefined;
  secFetchDest: string | null | undefined;
}) {
  if (input.method !== "GET" && input.method !== "HEAD") {
    return false;
  }

  if (input.secFetchDest === "document") {
    return true;
  }

  return (input.accept ?? "").includes("text/html");
}

export function resolveContentSecurityPolicyProfile(pathname: string): ContentSecurityPolicyProfile {
  return PUBLIC_AUTH_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
    ? "public"
    : "workspace";
}

export function createContentSecurityPolicyNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function buildContentSecurityPolicy({
  nonce,
  profile,
  isDevelopment = process.env.NODE_ENV !== "production",
}: BuildContentSecurityPolicyOptions) {
  const imgSources =
    profile === "public"
      ? ["'self'", "data:", "blob:", ...CLERK_SOURCES, ...CLERK_IMAGE_SOURCES]
      : ["'self'", "https:", "blob:", "data:"];

  return [
    formatDirective("default-src", ["'self'"]),
    formatDirective("script-src", [
      "'self'",
      `'nonce-${nonce}'`,
      ...(isDevelopment ? ["'unsafe-eval'"] : []),
      ...CLERK_SOURCES,
      ...CLOUDFLARE_TURNSTILE_SOURCES,
    ]),
    formatDirective("style-src", ["'self'"]),
    formatDirective("img-src", imgSources),
    formatDirective("font-src", ["'self'", "data:"]),
    formatDirective("connect-src", [
      "'self'",
      ...CLERK_SOURCES,
      ...CLERK_WEBSOCKET_SOURCES,
      ...CLOUDFLARE_TURNSTILE_SOURCES,
    ]),
    formatDirective("frame-src", [
      "'self'",
      ...CLERK_SOURCES,
      ...CLOUDFLARE_TURNSTILE_SOURCES,
    ]),
    formatDirective("worker-src", ["'self'", "blob:"]),
    formatDirective("object-src", ["'none'"]),
    formatDirective("base-uri", ["'self'"]),
    formatDirective("form-action", ["'self'"]),
    formatDirective("frame-ancestors", ["'none'"]),
    ...(!isDevelopment ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}
