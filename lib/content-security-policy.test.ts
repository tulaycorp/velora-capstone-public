import assert from "node:assert/strict";
import test from "node:test";

import {
  buildContentSecurityPolicy,
  isHtmlDocumentRequest,
  resolveContentSecurityPolicyProfile,
} from "./content-security-policy.ts";

test("buildContentSecurityPolicy includes nonce and public-page restrictions", () => {
  const csp = buildContentSecurityPolicy({
    nonce: "nonce-123",
    profile: "public",
    isDevelopment: false,
  });

  assert.match(csp, /script-src [^;]*'nonce-nonce-123'/);
  assert.match(csp, /script-src [^;]*https:\/\/\*\.clerk\.accounts\.dev/);
  assert.match(csp, /style-src [^;]*'nonce-nonce-123'/);
  assert.doesNotMatch(csp, /style-src [^;]*'unsafe-inline'/);
  assert.match(csp, /img-src [^;]*https:\/\/images\.clerk\.com/);
  assert.doesNotMatch(csp, /img-src 'self' https:/);
  assert.match(csp, /frame-src [^;]*https:\/\/challenges\.cloudflare\.com/);
});

test("buildContentSecurityPolicy keeps workspace image loading broad", () => {
  const csp = buildContentSecurityPolicy({
    nonce: "nonce-456",
    profile: "workspace",
    isDevelopment: true,
  });

  assert.match(csp, /img-src [^;]* https:/);
  assert.match(csp, /script-src [^;]*'unsafe-eval'/);
});

test("resolveContentSecurityPolicyProfile distinguishes public auth routes", () => {
  assert.equal(resolveContentSecurityPolicyProfile("/sign-in"), "public");
  assert.equal(resolveContentSecurityPolicyProfile("/sign-up/reset"), "public");
  assert.equal(resolveContentSecurityPolicyProfile("/dashboard"), "workspace");
});

test("isHtmlDocumentRequest only returns true for document navigations", () => {
  assert.equal(
    isHtmlDocumentRequest({
      method: "GET",
      accept: "text/html,application/xhtml+xml",
      secFetchDest: "document",
    }),
    true,
  );
  assert.equal(
    isHtmlDocumentRequest({
      method: "POST",
      accept: "text/html",
      secFetchDest: "document",
    }),
    false,
  );
  assert.equal(
    isHtmlDocumentRequest({
      method: "GET",
      accept: "application/json",
      secFetchDest: "empty",
    }),
    false,
  );
});
