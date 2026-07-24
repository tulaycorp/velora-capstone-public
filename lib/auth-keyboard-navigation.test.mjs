import assert from "node:assert/strict";
import test from "node:test";

import { getAdjacentAuthFocusTarget } from "./auth-keyboard-navigation.ts";

const controls = ["google", "email", "password", "visibility", "continue", "create-account"];

test("auth focus moves forward through controls in document order", () => {
  assert.equal(getAdjacentAuthFocusTarget(controls, "email", "forward"), "password");
  assert.equal(getAdjacentAuthFocusTarget(controls, "password", "forward"), "visibility");
  assert.equal(getAdjacentAuthFocusTarget(controls, "visibility", "forward"), "continue");
});

test("auth focus can prefer the password field over Clerk's generated DOM order", () => {
  const clerkControls = ["email", "continue", "password", "visibility"];

  assert.equal(
    getAdjacentAuthFocusTarget(clerkControls, "email", "forward", "password"),
    "password"
  );
  assert.equal(
    getAdjacentAuthFocusTarget(clerkControls, "password", "backward", "email"),
    "email"
  );
});

test("auth focus moves backward for Shift+Tab", () => {
  assert.equal(getAdjacentAuthFocusTarget(controls, "continue", "backward"), "visibility");
  assert.equal(getAdjacentAuthFocusTarget(controls, "password", "backward"), "email");
});

test("auth focus does not wrap or trap the user at a document boundary", () => {
  assert.equal(getAdjacentAuthFocusTarget(controls, "google", "backward"), null);
  assert.equal(getAdjacentAuthFocusTarget(controls, "create-account", "forward"), null);
  assert.equal(getAdjacentAuthFocusTarget(controls, "missing", "forward"), null);
});
