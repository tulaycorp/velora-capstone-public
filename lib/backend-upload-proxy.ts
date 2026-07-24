// Leave room for multipart boundaries and form fields around one 95 MiB image.
export const DEFAULT_UPLOAD_MAX_REQUEST_BYTES = 100 * 1024 * 1024;

const PRODUCT_MOCKUP_UPLOAD_PATH = /^products\/[^/]+\/mockups$/;

export function isBackendMediaUpload(path: string[], method: string) {
  const normalizedPath = path.join("/");
  return method.toUpperCase() === "POST"
    && (normalizedPath === "design-assets" || PRODUCT_MOCKUP_UPLOAD_PATH.test(normalizedPath));
}

export function getUploadMaxRequestBytes() {
  const configured = Number(process.env.VELORA_UPLOAD_MAX_REQUEST_BYTES);
  return Number.isSafeInteger(configured) && configured > 0
    ? configured
    : DEFAULT_UPLOAD_MAX_REQUEST_BYTES;
}

export function validateKnownUploadLength(contentLength: string | null, maxBytes: number) {
  if (contentLength === null) {
    return { allowed: true as const, declaredBytes: null };
  }
  if (!/^\d+$/.test(contentLength)) {
    return { allowed: false as const, status: 400, detail: "Invalid Content-Length header." };
  }
  const declaredBytes = Number(contentLength);
  if (!Number.isSafeInteger(declaredBytes)) {
    return { allowed: false as const, status: 400, detail: "Invalid Content-Length header." };
  }
  if (declaredBytes > maxBytes) {
    return {
      allowed: false as const,
      status: 413,
      detail: `Upload request exceeds the ${maxBytes} byte limit.`
    };
  }
  return { allowed: true as const, declaredBytes };
}
