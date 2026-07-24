import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { resolveFrontendAuthMode } from "./clerk-config.ts";

const SECURITY_ENV_KEYS = [
  "VELORA_ENVIRONMENT",
  "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
  "CLERK_SECRET_KEY",
] as const;

function withEnvironment(
  values: Partial<Record<(typeof SECURITY_ENV_KEYS)[number], string>>,
  callback: () => void,
) {
  const originals = Object.fromEntries(
    SECURITY_ENV_KEYS.map((key) => [key, process.env[key]]),
  );
  try {
    for (const key of SECURITY_ENV_KEYS) {
      const value = values[key];
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    callback();
  } finally {
    for (const key of SECURITY_ENV_KEYS) {
      const value = originals[key];
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

test("uses Clerk when both frontend credentials are configured", () => {
  withEnvironment(
    {
      VELORA_ENVIRONMENT: "production",
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_test_configured",
      CLERK_SECRET_KEY: "sk_test_configured",
    },
    () => assert.equal(resolveFrontendAuthMode(), "clerk"),
  );
});

test("allows Clerk-free local mode only in development and test", () => {
  for (const environment of ["development", "test"]) {
    withEnvironment({ VELORA_ENVIRONMENT: environment }, () => {
      assert.equal(resolveFrontendAuthMode(), "local");
    });
  }
});

test("rejects each missing Clerk credential outside local environments", () => {
  for (const [environment, configured] of [
    ["staging", { CLERK_SECRET_KEY: "sk_test_configured" }],
    ["production", { NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "pk_test_configured" }],
  ] as const) {
    withEnvironment({ VELORA_ENVIRONMENT: environment, ...configured }, () => {
      assert.throws(
        () => resolveFrontendAuthMode(),
        /Clerk authentication is required/,
      );
    });
  }
});

test("treats unknown environment names as non-local", () => {
  withEnvironment({ VELORA_ENVIRONMENT: "preview" }, () => {
    assert.throws(() => resolveFrontendAuthMode(), /missing:/);
  });
});

test("middleware and BFF share the fail-closed auth-mode resolver", () => {
  const middlewareSource = readFileSync(new URL("../middleware.ts", import.meta.url), "utf8");
  const bffSource = readFileSync(
    new URL("../app/api/backend/[...path]/route.ts", import.meta.url),
    "utf8",
  );

  for (const source of [middlewareSource, bffSource]) {
    assert.match(source, /resolveFrontendAuthMode\(\)/);
    assert.doesNotMatch(source, /isClerkFrontendConfigured\(\) \?/);
  }
});
