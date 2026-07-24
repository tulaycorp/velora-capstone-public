import assert from "node:assert/strict";
import test from "node:test";

import {
  buildForwardedRequestBody
} from "./backend-proxy.ts";

test("detects unexpected HTML responses from the configured backend origin", async () => {
  const proxyModule = await import("./backend-proxy.ts").catch(() => null);

  assert.ok(proxyModule, "Expected backend-proxy helpers to exist.");
  assert.equal(
    proxyModule?.isUnexpectedHtmlProxyResponse(404, "text/html; charset=utf-8"),
    true
  );
  assert.equal(
    proxyModule?.isUnexpectedHtmlProxyResponse(404, "application/json"),
    false
  );
  assert.equal(
    proxyModule?.isUnexpectedHtmlProxyResponse(200, "text/html; charset=utf-8"),
    false
  );
});

test("builds an actionable backend proxy misconfiguration message", async () => {
  const proxyModule = await import("./backend-proxy.ts").catch(() => null);

  assert.ok(proxyModule, "Expected backend-proxy helpers to exist.");
  assert.equal(
    proxyModule?.buildUnexpectedHtmlProxyErrorDetail(
      "https://velora-web.example.com/sync-jobs/orders/run",
      404
    ),
    "Velora backend proxy expected API JSON but received an HTML 404 from https://velora-web.example.com/sync-jobs/orders/run. Check VELORA_API_BASE_URL on the web app; it must point to the FastAPI service, not the Next.js frontend."
  );
});

test("streams multipart uploads with their file and fields intact", async () => {
  const formData = new FormData();
  formData.append(
    "file",
    new File(["image-bytes"], "artwork.png", { type: "image/png" })
  );
  formData.append("position", "3");
  const request = new Request("http://localhost/api/backend/design-assets", {
    method: "POST",
    body: formData
  });

  const forwardedBody = buildForwardedRequestBody(request);
  assert.ok(forwardedBody instanceof ReadableStream);
  const outboundOptions: RequestInit & { duplex: "half" } = {
    method: "POST",
    headers: { "content-type": request.headers.get("content-type") ?? "" },
    body: forwardedBody,
    duplex: "half"
  };
  const outboundRequest = new Request("http://localhost:8000/design-assets", {
    ...outboundOptions
  });
  const outboundFormData = await outboundRequest.formData();
  const outboundFile = outboundFormData.get("file");
  assert.ok(outboundFile instanceof File);
  assert.equal(outboundFile.name, "artwork.png");
  assert.equal(outboundFile.type, "image/png");
  assert.equal(outboundFile.size, 11);
  assert.equal(outboundFormData.get("position"), "3");
});

test("keeps non-multipart request bodies byte-for-byte", async () => {
  const request = new Request("http://localhost/api/backend/products", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ title: "Poster" })
  });

  const forwardedBody = buildForwardedRequestBody(request);
  assert.ok(forwardedBody instanceof ReadableStream);
  const outboundOptions: RequestInit & { duplex: "half" } = {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: forwardedBody,
    duplex: "half"
  };
  const outboundRequest = new Request(
    "http://localhost:8000/products",
    outboundOptions
  );
  assert.equal(await outboundRequest.text(), '{"title":"Poster"}');
});
