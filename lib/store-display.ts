const STORE_RELATIONSHIP_SEPARATOR = /\s*(?:->|→)\s*/;

export function splitStoreDisplayLabel(label: string | null | undefined) {
  const normalized = label?.trim() ?? "";
  const [name = "", relationship = ""] = normalized.split(
    STORE_RELATIONSHIP_SEPARATOR,
    2
  );

  return {
    name: name.trim(),
    relationship: relationship.trim(),
  };
}

export function cleanStoreDisplayName(
  label: string | null | undefined,
  fallback = "Unknown store"
) {
  const { name } = splitStoreDisplayLabel(label);
  return name || label?.trim() || fallback;
}
