import assert from "node:assert/strict";
import test from "node:test";

import {
  STORE_SELECTION_COOKIE_NAME,
  STORE_SELECTION_LOCAL_STORAGE_KEY,
  persistStoreSelectionInBrowser,
  readPersistedStoreSelectionFromBrowser,
  syncStoreSelection
} from "./store-context-state.ts";

test("syncStoreSelection does not reset a persisted store before store connections finish loading", () => {
  const nextState = syncStoreSelection({
    canValidateSelection: false,
    selectedStoreId: "store-1",
    storeConnections: []
  });

  assert.equal(nextState.shouldUpdateSelectedStoreId, false);
  assert.equal(nextState.nextSelectedStoreId, "store-1");
});

test("syncStoreSelection falls back to all stores when a saved store no longer exists", () => {
  const nextState = syncStoreSelection({
    canValidateSelection: true,
    selectedStoreId: "store-1",
    storeConnections: [{ id: "store-2" }, { id: "store-3" }]
  });

  assert.equal(nextState.shouldUpdateSelectedStoreId, true);
  assert.equal(nextState.nextSelectedStoreId, "all");
});

test("syncStoreSelection falls back to all stores after a completed load with no stores", () => {
  const nextState = syncStoreSelection({
    canValidateSelection: true,
    selectedStoreId: "store-1",
    storeConnections: []
  });

  assert.equal(nextState.shouldUpdateSelectedStoreId, true);
  assert.equal(nextState.nextSelectedStoreId, "all");
});

test("persistStoreSelectionInBrowser writes both local storage and cookie state", () => {
  const originalWindow = globalThis.window;
  const originalDocument = globalThis.document;
  const storage = new Map<string, string>();

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        }
      }
    }
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      cookie: ""
    }
  });

  try {
    persistStoreSelectionInBrowser("store-42");

    assert.equal(storage.get(STORE_SELECTION_LOCAL_STORAGE_KEY), "store-42");
    assert.match(globalThis.document.cookie, new RegExp(`^${STORE_SELECTION_COOKIE_NAME}=store-42`));
    assert.match(globalThis.document.cookie, /SameSite=Lax/);
  } finally {
    if (originalWindow === undefined) {
      delete (globalThis as { window?: Window }).window;
    } else {
      Object.defineProperty(globalThis, "window", {
        configurable: true,
        value: originalWindow
      });
    }

    if (originalDocument === undefined) {
      delete (globalThis as { document?: Document }).document;
    } else {
      Object.defineProperty(globalThis, "document", {
        configurable: true,
        value: originalDocument
      });
    }
  }
});

test("readPersistedStoreSelectionFromBrowser falls back to cookie when local storage is empty", () => {
  const originalWindow = globalThis.window;
  const originalDocument = globalThis.document;

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: () => null,
        setItem: () => {}
      }
    }
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      cookie: `${STORE_SELECTION_COOKIE_NAME}=store-cookie; another=value`
    }
  });

  try {
    assert.equal(readPersistedStoreSelectionFromBrowser(), "store-cookie");
  } finally {
    if (originalWindow === undefined) {
      delete (globalThis as { window?: Window }).window;
    } else {
      Object.defineProperty(globalThis, "window", {
        configurable: true,
        value: originalWindow
      });
    }

    if (originalDocument === undefined) {
      delete (globalThis as { document?: Document }).document;
    } else {
      Object.defineProperty(globalThis, "document", {
        configurable: true,
        value: originalDocument
      });
    }
  }
});
