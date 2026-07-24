import type { Blueprint } from "@/lib/backend-api";

const PRINT_PLACEHOLDER_COUNT_PATTERN = /(\d+)\s+print placeholders?/i;
const VARIANT_COUNT_PATTERN = /(\d+)\s+variants?/i;
const PLACEHOLDER_LIST_PATTERN = /placeholders?:\s*(.+)$/i;

function formatCount(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function normalizePlacementNames(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }

  const seen = new Set<string>();
  const normalizedNames: string[] = [];

  for (const candidate of value) {
    if (typeof candidate !== "string") {
      continue;
    }

    const normalized = candidate.trim();
    if (!normalized) {
      continue;
    }

    const key = normalized.toLowerCase();
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    normalizedNames.push(normalized);
  }

  return normalizedNames;
}

function titleCaseWords(value: string) {
  return value
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function humanizePlacementName(name: string) {
  const normalized = name
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const key = normalized.toLowerCase();

  if (key === "imagefront" || key === "image front" || key === "front") {
    return "Front";
  }
  if (key === "imageback" || key === "image back" || key === "back") {
    return "Back";
  }
  if (key === "sleeve left" || key === "left sleeve") {
    return "Left sleeve";
  }
  if (key === "sleeve right" || key === "right sleeve") {
    return "Right sleeve";
  }

  const cleaned = normalized
    .replace(/\bimage\b/gi, "")
    .replace(/\bprintable\b/gi, "")
    .replace(/\bmaterial\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();

  if (!cleaned) {
    return "Artwork area";
  }

  return titleCaseWords(cleaned);
}

function readVariantCount(blueprint: Blueprint) {
  if (blueprint.variant_count > 0) {
    return blueprint.variant_count;
  }

  const match = blueprint.configuration_summary?.match(VARIANT_COUNT_PATTERN);
  return match ? Number(match[1]) : 0;
}

function readArtworkPlacementNames(blueprint: Blueprint) {
  const configNames = normalizePlacementNames(
    blueprint.placement_config_json?.design_placeholder_names
  );
  if (configNames.length > 0) {
    return configNames;
  }

  const singleName = blueprint.placement_config_json?.design_placeholder_name;
  if (typeof singleName === "string" && singleName.trim()) {
    return [singleName.trim()];
  }

  const summaryMatch = blueprint.configuration_summary?.match(PLACEHOLDER_LIST_PATTERN);
  if (!summaryMatch?.[1]) {
    return [];
  }

  return normalizePlacementNames(summaryMatch[1].split(","));
}

function readArtworkPlacementCount(blueprint: Blueprint) {
  const names = readArtworkPlacementNames(blueprint);
  if (names.length > 0) {
    return names.length;
  }

  const match = blueprint.configuration_summary?.match(PRINT_PLACEHOLDER_COUNT_PATTERN);
  return match ? Number(match[1]) : 0;
}

export function getBlueprintCardTitle(blueprint: Blueprint) {
  const name = blueprint.name.trim();
  if (name) {
    return name;
  }

  const providerName = blueprint.provider_display_name?.trim();
  return providerName || "Selected blueprint";
}

export function getBlueprintCardSubtitle(blueprint: Blueprint) {
  const providerName = blueprint.provider_display_name?.trim();
  if (providerName && providerName !== blueprint.name.trim()) {
    return providerName;
  }

  const productType = blueprint.product_type?.trim();
  return productType || "Product setup";
}

export function formatBlueprintProductType(blueprint: Blueprint) {
  return blueprint.product_type?.trim() || blueprint.provider_display_name?.trim() || "Product setup";
}

export function formatBlueprintVariantSummary(blueprint: Blueprint) {
  const variantCount = readVariantCount(blueprint);
  return variantCount > 0 ? formatCount(variantCount, "variant") : "Ready";
}

export function formatBlueprintArtworkSummary(blueprint: Blueprint) {
  const names = readArtworkPlacementNames(blueprint);
  if (names.length === 1) {
    return humanizePlacementName(names[0]);
  }

  const placementCount = names.length || readArtworkPlacementCount(blueprint);
  if (placementCount > 0) {
    return formatCount(placementCount, "artwork area");
  }

  return "Ready";
}

export function getRawBlueprintArtworkSummary(blueprint: Blueprint) {
  const names = readArtworkPlacementNames(blueprint);
  if (names.length === 1) {
    return names[0];
  }

  const placementCount = names.length || readArtworkPlacementCount(blueprint);
  if (placementCount > 0) {
    return formatCount(placementCount, "artwork area");
  }

  return "Ready";
}
