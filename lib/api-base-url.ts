const DEFAULT_BACKEND_API_BASE_URL = "http://127.0.0.1:8000";

export function getBackendApiBaseUrl() {
  const baseUrl = (
    process.env.VELORA_API_BASE_URL ||
    process.env.NEXT_PUBLIC_VELORA_API_BASE_URL ||
    DEFAULT_BACKEND_API_BASE_URL
  ).replace(/\/$/, "");

  const environment = (process.env.VELORA_ENVIRONMENT || "development").toLowerCase();
  if (["staging", "production"].includes(environment) && !baseUrl.startsWith("https://")) {
    throw new Error("VELORA_API_BASE_URL must use HTTPS outside development and test.");
  }
  return baseUrl;
}
