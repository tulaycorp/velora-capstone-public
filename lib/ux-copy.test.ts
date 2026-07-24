import assert from "node:assert/strict";
import test from "node:test";

import {
  formatPushHelperCopy,
  formatPushStatusMessage,
  formatQueuedPushMessage,
  humanizeApiErrorDetail,
  humanizeApiErrorPayload,
  humanizeStatusLabel
} from "./ux-copy.ts";

test("humanizeStatusLabel rewrites internal status codes into merchant-facing labels", () => {
  assert.equal(humanizeStatusLabel("validated"), "Ready");
  assert.equal(humanizeStatusLabel("publishing"), "Sending");
  assert.equal(humanizeStatusLabel("needs_credentials"), "Needs setup");
});

test("humanizeApiErrorPayload rewrites missing multipart file validation", () => {
  assert.equal(
    humanizeApiErrorPayload({
      detail: [
        {
          type: "missing",
          loc: ["body", "file"],
          msg: "Field required",
          input: null
        }
      ]
    }),
    "The upload arrived without a file. Choose the image again and retry."
  );
});

test("push status copy avoids job ids and backend wording", () => {
  assert.equal(formatQueuedPushMessage("Etsy"), "Starting your send to Etsy.");
  assert.equal(
    formatPushStatusMessage("Etsy", "running"),
    "Sending your product to Etsy."
  );
  assert.equal(
    formatPushHelperCopy("Etsy"),
    "Save your work, then send it to Etsy when you're ready."
  );
});

test("humanizeApiErrorDetail rewrites technical backend messages", () => {
  assert.equal(
    humanizeApiErrorDetail("Credentials for 'printify' are incomplete."),
    "Finish setting up Printify before continuing."
  );
  assert.equal(
    humanizeApiErrorDetail("Blueprint reference must be validated before publishing."),
    "Refresh the blueprint details before sending this product."
  );
  assert.equal(
    humanizeApiErrorDetail("Internal Server Error"),
    "Something went wrong on our side. Try again in a moment."
  );
  assert.equal(
    humanizeApiErrorDetail(
      "Velora backend proxy expected API JSON but received an HTML 404 from https://velora-web.example.com/sync-jobs/orders/run. Check VELORA_API_BASE_URL on the web app; it must point to the FastAPI service, not the Next.js frontend."
    ),
    "Velora isn't fully configured right now. The web app can't reach the backend service."
  );
  assert.equal(
    humanizeApiErrorDetail("<!DOCTYPE html><html><head><title>404</title></head><body>Not found</body></html>"),
    "Velora isn't fully configured right now. The web app can't reach the backend service."
  );
});
