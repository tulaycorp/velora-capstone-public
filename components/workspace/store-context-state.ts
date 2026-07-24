type StoreConnectionSeed = {
  id: string;
};

export const STORE_SELECTION_LOCAL_STORAGE_KEY = "velora.selected-store-id";
export const STORE_SELECTION_COOKIE_NAME = "velora-selected-store-id";

const STORE_SELECTION_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

type StoreSelectionSyncInput = {
  canValidateSelection: boolean;
  selectedStoreId: string;
  storeConnections: StoreConnectionSeed[];
};

type StoreSelectionSyncResult = {
  nextSelectedStoreId: string;
  shouldUpdateSelectedStoreId: boolean;
};

export function syncStoreSelection({
  canValidateSelection,
  selectedStoreId,
  storeConnections
}: StoreSelectionSyncInput): StoreSelectionSyncResult {
  if (!canValidateSelection) {
    return {
      nextSelectedStoreId: selectedStoreId,
      shouldUpdateSelectedStoreId: false
    };
  }

  const exists = storeConnections.some((connection) => connection.id === selectedStoreId);

  if (storeConnections.length === 0) {
    return {
      nextSelectedStoreId: "all",
      shouldUpdateSelectedStoreId: selectedStoreId !== "all"
    };
  }

  if (storeConnections.length === 1) {
    const onlyStoreId = storeConnections[0]?.id ?? "all";
    return {
      nextSelectedStoreId: onlyStoreId,
      shouldUpdateSelectedStoreId: selectedStoreId !== onlyStoreId
    };
  }

  if (selectedStoreId !== "all" && !exists) {
    return {
      nextSelectedStoreId: "all",
      shouldUpdateSelectedStoreId: true
    };
  }

  return {
    nextSelectedStoreId: selectedStoreId,
    shouldUpdateSelectedStoreId: false
  };
}

export function readPersistedStoreSelectionFromBrowser() {
  if (typeof window === "undefined") {
    return null;
  }

  const savedValue = window.localStorage.getItem(STORE_SELECTION_LOCAL_STORAGE_KEY);
  if (savedValue) {
    return savedValue;
  }

  const cookiePrefix = `${STORE_SELECTION_COOKIE_NAME}=`;
  const matchingCookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(cookiePrefix));

  if (!matchingCookie) {
    return null;
  }

  return decodeURIComponent(matchingCookie.slice(cookiePrefix.length));
}

export function persistStoreSelectionInBrowser(value: string) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(STORE_SELECTION_LOCAL_STORAGE_KEY, value);
  document.cookie = [
    `${STORE_SELECTION_COOKIE_NAME}=${encodeURIComponent(value)}`,
    "Path=/",
    `Max-Age=${STORE_SELECTION_COOKIE_MAX_AGE_SECONDS}`,
    "SameSite=Lax"
  ].join("; ");
}
