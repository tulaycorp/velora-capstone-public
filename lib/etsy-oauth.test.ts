import assert from "node:assert/strict";
import test from "node:test";

import {
  ETSY_OAUTH_MESSAGE_TYPE,
  buildEtsyOAuthPopupFeatures,
  createEtsyOAuthErrorMessage,
  createEtsyOAuthSuccessMessage,
  isEtsyOAuthMessage
} from "./etsy-oauth.ts";

test("buildEtsyOAuthPopupFeatures centers a small popup window", () => {
  const features = buildEtsyOAuthPopupFeatures({
    width: 520,
    height: 720,
    screenX: 100,
    screenY: 40,
    outerWidth: 1440,
    outerHeight: 900
  });

  assert.equal(
    features,
    "popup=yes,width=520,height=720,left=560,top=130,resizable=yes,scrollbars=yes"
  );
});

test("isEtsyOAuthMessage accepts same-origin success and error payloads", () => {
  assert.equal(
    isEtsyOAuthMessage(createEtsyOAuthSuccessMessage("opaque-state")),
    true
  );

  assert.equal(
    isEtsyOAuthMessage(createEtsyOAuthErrorMessage("Unable to finish the Etsy connection.", "opaque-state")),
    true
  );

  assert.equal(
    isEtsyOAuthMessage(createEtsyOAuthErrorMessage("Unable to finish the Etsy connection.")),
    true
  );
});

test("isEtsyOAuthMessage rejects unrelated payloads", () => {
  assert.equal(isEtsyOAuthMessage(null), false);
  assert.equal(isEtsyOAuthMessage({ type: "other:event", success: true }), false);
  assert.equal(isEtsyOAuthMessage({ type: ETSY_OAUTH_MESSAGE_TYPE }), false);
  assert.equal(isEtsyOAuthMessage({ type: ETSY_OAUTH_MESSAGE_TYPE, success: false }), false);
  assert.equal(isEtsyOAuthMessage({ type: ETSY_OAUTH_MESSAGE_TYPE, success: true, state: "" }), false);
});
