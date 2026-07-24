const SUPPORTED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const SUPPORTED_IMAGE_EXTENSION = /\.(png|jpe?g|webp)$/i;

export type QueuedProductImage = {
  id: string;
  file: File;
};

export function truncateProductImageName(name: string, maxLength = 24) {
  if (name.length <= maxLength) return name;
  const extensionIndex = name.lastIndexOf(".");
  if (extensionIndex <= 0) return `${name.slice(0, maxLength - 3)}...`;
  const extension = name.slice(extensionIndex);
  const base = name.slice(0, extensionIndex);
  return `${base.slice(0, maxLength - 3 - extension.length)}..${extension}`;
}

export function isSupportedProductImage(file: Pick<File, "name" | "type">) {
  return SUPPORTED_IMAGE_TYPES.has(file.type.toLowerCase())
    || SUPPORTED_IMAGE_EXTENSION.test(file.name);
}

export function extractSupportedProductImages(fileList: FileList | null) {
  return Array.from(fileList ?? []).filter(isSupportedProductImage);
}

function createQueueId() {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `queued-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createQueuedProductImage(
  file: File,
  createId: () => string = createQueueId
): QueuedProductImage {
  return { id: createId(), file };
}
