const REQUIRED_FRONTEND_ENV_KEYS = [
  "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
  "CLERK_SECRET_KEY"
] as const;

const REQUIRED_BACKEND_VERIFIER_ENV_KEYS = ["VELORA_CLERK_JWKS_URL"] as const;

export type FrontendAuthMode = "clerk" | "local";

const LOCAL_FRONTEND_ENVIRONMENTS = new Set(["development", "test"]);

function hasValue(value: string | undefined) {
  return typeof value === "string" && value.trim().length > 0;
}

export function isClerkFrontendConfigured() {
  return REQUIRED_FRONTEND_ENV_KEYS.every((key) => hasValue(process.env[key]));
}

export function getMissingClerkFrontendEnvKeys() {
  return REQUIRED_FRONTEND_ENV_KEYS.filter((key) => !hasValue(process.env[key]));
}

export function resolveFrontendAuthMode(): FrontendAuthMode {
  if (isClerkFrontendConfigured()) {
    return "clerk";
  }

  const environment = (process.env.VELORA_ENVIRONMENT || "development")
    .trim()
    .toLowerCase();
  if (LOCAL_FRONTEND_ENVIRONMENTS.has(environment)) {
    return "local";
  }

  const missingKeys = getMissingClerkFrontendEnvKeys().join(", ");
  throw new Error(
    `Clerk authentication is required in ${environment}; missing: ${missingKeys}.`,
  );
}

export function isClerkBackendVerifierConfigured() {
  return REQUIRED_BACKEND_VERIFIER_ENV_KEYS.every((key) => hasValue(process.env[key]));
}

export function getMissingClerkBackendVerifierEnvKeys() {
  return REQUIRED_BACKEND_VERIFIER_ENV_KEYS.filter((key) => !hasValue(process.env[key]));
}

export function isClerkAppConfigured() {
  return isClerkFrontendConfigured() && isClerkBackendVerifierConfigured();
}
