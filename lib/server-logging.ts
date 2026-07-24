const TRUTHY_VALUES = new Set(["1", "true", "yes", "on"]);
const SENSITIVE_KEY_PARTS = [
  "authorization",
  "api_key",
  "api-key",
  "api_token",
  "api-token",
  "token",
  "secret",
  "password",
  "cookie",
  "set-cookie"
];

export const REDACTED_VALUE = "[redacted]";

export type ServerLogLevel = "info" | "warn" | "error";
export type ServerLogFormat = "pretty" | "json";

type ServerLogFields = Record<string, unknown>;

function isSensitiveKey(key: string | null | undefined) {
  if (!key) {
    return false;
  }
  const normalized = key.trim().toLowerCase().replaceAll("_", "-");
  return SENSITIVE_KEY_PARTS.some((part) => normalized.includes(part));
}

export function sanitizeServerLogFields(value: unknown, key?: string): unknown {
  if (isSensitiveKey(key)) {
    return REDACTED_VALUE;
  }

  if (Array.isArray(value)) {
    return value.map((item) => sanitizeServerLogFields(item));
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([entryKey, entryValue]) => [
        entryKey,
        sanitizeServerLogFields(entryValue, entryKey)
      ])
    );
  }

  return value;
}

export function isVerboseServerLoggingEnabled(env: Record<string, string | undefined> = process.env) {
  const raw = env.VELORA_VERBOSE_LOGGING?.trim().toLowerCase();
  return raw ? TRUTHY_VALUES.has(raw) : false;
}

export function getServerLogFormat(env: Record<string, string | undefined> = process.env): ServerLogFormat {
  return env.VELORA_LOG_FORMAT?.trim().toLowerCase() === "json" ? "json" : "pretty";
}

export function getOrCreateRequestId(existingRequestId?: string | null) {
  const trimmed = existingRequestId?.trim();
  if (trimmed) {
    return trimmed;
  }
  return `req_${crypto.randomUUID().replaceAll("-", "")}`;
}

function formatFieldValue(value: unknown) {
  if (typeof value === "string") {
    return value.includes(" ") ? JSON.stringify(value) : value;
  }
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return String(value);
  }
  return JSON.stringify(value);
}

export function formatServerLogLine(format: ServerLogFormat, entry: ServerLogFields) {
  const sanitizedEntry = sanitizeServerLogFields(entry) as ServerLogFields;
  if (format === "json") {
    return JSON.stringify(sanitizedEntry);
  }

  const { ts, level, event, ...fields } = sanitizedEntry;
  const parts = [String(ts ?? new Date().toISOString()), String(level ?? "info").toUpperCase(), String(event ?? "server.log")];

  for (const [key, value] of Object.entries(fields).sort(([left], [right]) => left.localeCompare(right))) {
    parts.push(`${key}=${formatFieldValue(value)}`);
  }

  return parts.join(" ");
}

export function logServerEvent(
  level: ServerLogLevel,
  event: string,
  fields: ServerLogFields = {}
) {
  if (level !== "error" && !isVerboseServerLoggingEnabled()) {
    return;
  }

  const line = formatServerLogLine(getServerLogFormat(), {
    ts: new Date().toISOString(),
    level,
    event,
    ...fields
  });

  if (level === "error") {
    console.error(line);
    return;
  }
  if (level === "warn") {
    console.warn(line);
    return;
  }
  console.info(line);
}
