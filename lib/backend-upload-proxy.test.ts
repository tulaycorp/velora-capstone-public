import assert from "node:assert/strict";
import test from "node:test";

import {
  isBackendMediaUpload,
  validateKnownUploadLength
} from "./backend-upload-proxy.ts";

test("identifies only the two media upload boundaries", () => {
  assert.equal(isBackendMediaUpload(["design-assets"], "POST"), true);
  assert.equal(isBackendMediaUpload(["products", "product-1", "mockups"], "POST"), true);
  assert.equal(isBackendMediaUpload(["products", "product-1", "publish"], "POST"), false);
  assert.equal(isBackendMediaUpload(["design-assets"], "GET"), false);
});

test("rejects malformed or oversized known upload lengths", () => {
  assert.deepEqual(validateKnownUploadLength(null, 100), { allowed: true, declaredBytes: null });
  assert.deepEqual(validateKnownUploadLength("100", 100), { allowed: true, declaredBytes: 100 });
  assert.deepEqual(validateKnownUploadLength("101", 100), {
    allowed: false,
    status: 413,
    detail: "Upload request exceeds the 100 byte limit."
  });
  assert.deepEqual(validateKnownUploadLength("invalid", 100), {
    allowed: false,
    status: 400,
    detail: "Invalid Content-Length header."
  });
});
