export const ETSY_OAUTH_MESSAGE_TYPE = "velora:etsy-oauth";

export type EtsyOAuthMessage =
  | {
      type: typeof ETSY_OAUTH_MESSAGE_TYPE;
      success: true;
      state: string;
    }
  | {
      type: typeof ETSY_OAUTH_MESSAGE_TYPE;
      success: false;
      error: string;
      state: string | null;
    };

type EtsyOAuthPopupFeaturesInput = {
  width?: number;
  height?: number;
  screenX?: number;
  screenY?: number;
  outerWidth?: number;
  outerHeight?: number;
};

export function buildEtsyOAuthPopupFeatures({
  width = 520,
  height = 720,
  screenX = 0,
  screenY = 0,
  outerWidth = width,
  outerHeight = height
}: EtsyOAuthPopupFeaturesInput = {}) {
  const left = Math.max(Math.round(screenX + (outerWidth - width) / 2), 0);
  const top = Math.max(Math.round(screenY + (outerHeight - height) / 2), 0);

  return [
    "popup=yes",
    `width=${width}`,
    `height=${height}`,
    `left=${left}`,
    `top=${top}`,
    "resizable=yes",
    "scrollbars=yes"
  ].join(",");
}

export function createEtsyOAuthSuccessMessage(state: string): EtsyOAuthMessage {
  return {
    type: ETSY_OAUTH_MESSAGE_TYPE,
    success: true,
    state
  };
}

export function createEtsyOAuthErrorMessage(
  error: string,
  state: string | null = null
): EtsyOAuthMessage {
  return {
    type: ETSY_OAUTH_MESSAGE_TYPE,
    success: false,
    error,
    state
  };
}

export function isEtsyOAuthMessage(value: unknown): value is EtsyOAuthMessage {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as {
    type?: unknown;
    success?: unknown;
    error?: unknown;
    state?: unknown;
  };
  if (candidate.type !== ETSY_OAUTH_MESSAGE_TYPE || typeof candidate.success !== "boolean") {
    return false;
  }

  if (candidate.success) {
    return typeof candidate.state === "string" && candidate.state.trim().length > 0;
  }

  return (
    typeof candidate.error === "string"
    && candidate.error.trim().length > 0
    && (candidate.state === null || (typeof candidate.state === "string" && candidate.state.trim().length > 0))
  );
}
