from __future__ import annotations

import re

from app.ai.schemas import ListingOutput


ETSY_TITLE_MAX_LENGTH = 140
ETSY_TITLE_MIN_LENGTH = 130
ETSY_TITLE_PATTERN = (
    r"^[A-Za-z0-9]+(?: [A-Za-z0-9]+)*(?:, [A-Za-z0-9]+(?: [A-Za-z0-9]+)*)+$"
)
ETSY_TAG_COUNT = 13
ETSY_TAG_MAX_LENGTH = 20
ETSY_TAG_REPEATED_TOKEN_LIMIT = 3
ETSY_DESCRIPTION_MIN_LENGTH = 600
ETSY_DESCRIPTION_MIN_PARAGRAPHS = 4
ETSY_DESCRIPTION_MAX_PARAGRAPHS = 6
SEO_TITLE_MIN_LENGTH = 40
SEO_TITLE_MAX_LENGTH = 70
SEO_DESCRIPTION_MIN_LENGTH = 120
SEO_DESCRIPTION_MAX_LENGTH = 160
SEO_KEYWORD_COUNT = 5
SEO_KEYWORD_MAX_LENGTH = 40


class EtsyComplianceError(ValueError):
    """A model response failed deterministic Etsy listing requirements."""


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['’-][a-z0-9]+)*", re.IGNORECASE)
_TITLE_FORMAT_RE = re.compile(ETSY_TITLE_PATTERN)
_TITLE_STOP_WORDS = frozenset({"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"})
_TAG_STOP_WORDS = frozenset({"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"})
_ALLOWED_SHORT_TITLE_ENDINGS = frozenset({"s", "m", "l", "xl", "xs", "xxl", "3d"})


def _normalized_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in tags:
        tag = re.sub(r"\s+", " ", str(value).strip())
        if not tag:
            continue
        key = tag.casefold()
        if key not in seen:
            result.append(tag)
            seen.add(key)
    return result


def _trim_at_word_boundary(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    clipped = normalized[:limit].rstrip(" ,;:-")
    word_boundary = clipped.rsplit(" ", 1)[0] if " " in clipped else clipped
    if len(word_boundary) >= limit - 20:
        clipped = word_boundary
    return clipped.rstrip(" ,;:-")


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value)]


def _repeated_title_tokens(title: str) -> list[str]:
    counts: dict[str, int] = {}
    for token in _tokens(title):
        if token in _TITLE_STOP_WORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    return sorted(token for token, count in counts.items() if count > 1)


def _tag_diversity_violations(tags: list[str]) -> list[str]:
    token_sets = [set(_tokens(tag)) - _TAG_STOP_WORDS for tag in tags]
    repeated_tokens: dict[str, int] = {}
    for tokens in token_sets:
        for token in tokens:
            repeated_tokens[token] = repeated_tokens.get(token, 0) + 1

    overused = sorted(
        token
        for token, count in repeated_tokens.items()
        if count > ETSY_TAG_REPEATED_TOKEN_LIMIT
    )
    violations: list[str] = []
    if overused:
        violations.append(
            "tags must use a diverse array of search intents; repeated words appear in too many tags: "
            + ", ".join(overused)
        )

    near_duplicates: list[str] = []
    for index, left in enumerate(token_sets):
        if not left:
            continue
        for other_index in range(index + 1, len(token_sets)):
            right = token_sets[other_index]
            if not right:
                continue
            overlap = len(left & right) / len(left | right)
            if overlap >= 0.6:
                near_duplicates.append(f"{tags[index]} / {tags[other_index]}")
    if near_duplicates:
        violations.append(
            "tags must not be near-duplicate phrase variations: "
            + "; ".join(near_duplicates[:3])
        )
    return violations


def _diverse_tag_subset(tags: list[str]) -> list[str]:
    """Keep the model's strongest ordered tags without repeated-intent padding."""
    result: list[str] = []
    token_sets: list[set[str]] = []
    token_counts: dict[str, int] = {}
    for tag in tags:
        tokens = set(_tokens(tag)) - _TAG_STOP_WORDS
        if any(
            token_counts.get(token, 0) >= ETSY_TAG_REPEATED_TOKEN_LIMIT
            for token in tokens
        ):
            continue
        if any(
            len(tokens & existing) / len(tokens | existing) >= 0.6
            for existing in token_sets
            if tokens and existing
        ):
            continue
        result.append(tag)
        token_sets.append(tokens)
        for token in tokens:
            token_counts[token] = token_counts.get(token, 0) + 1
    return result


def _four_balanced_groups(parts: list[str]) -> list[str]:
    group_count = ETSY_DESCRIPTION_MIN_PARAGRAPHS
    base_size, larger_groups = divmod(len(parts), group_count)
    groups: list[str] = []
    start = 0
    for index in range(group_count):
        size = base_size + (1 if index < larger_groups else 0)
        groups.append(" ".join(parts[start:start + size]))
        start += size
    return groups


def _formatted_description(value: str) -> str:
    description = value.replace("\r\n", "\n").strip()
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", description)
        if paragraph.strip()
    ]
    if ETSY_DESCRIPTION_MIN_PARAGRAPHS <= len(paragraphs) <= ETSY_DESCRIPTION_MAX_PARAGRAPHS:
        return "\n\n".join(paragraphs)

    lines = [re.sub(r"\s+", " ", line).strip() for line in description.splitlines() if line.strip()]
    if ETSY_DESCRIPTION_MIN_PARAGRAPHS <= len(lines) <= ETSY_DESCRIPTION_MAX_PARAGRAPHS:
        return "\n\n".join(lines)

    dense = re.sub(r"\s+", " ", description).strip()
    if len(dense) < ETSY_DESCRIPTION_MIN_LENGTH:
        return dense
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", dense) if part.strip()]
    parts = sentences if len(sentences) >= ETSY_DESCRIPTION_MIN_PARAGRAPHS else dense.split()
    return "\n\n".join(_four_balanced_groups(parts))


def normalize_generated_output(
    output: ListingOutput,
    *,
    generation_fields: set[str] | None = None,
) -> ListingOutput:
    """Apply safe marketplace limits before rejecting generated content."""
    fields = generation_fields or {
        "title", "description", "tags", "seo_title", "seo_description", "seo_keywords"
    }
    if "title" in fields:
        output.title = _trim_at_word_boundary(output.title, ETSY_TITLE_MAX_LENGTH)
    if "tags" in fields:
        normalized_tags: list[str] = []
        seen: set[str] = set()
        for value in _normalized_tags(output.tags):
            tag = _trim_at_word_boundary(value, ETSY_TAG_MAX_LENGTH)
            if not tag:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            normalized_tags.append(tag)
            seen.add(key)
            if len(normalized_tags) == ETSY_TAG_COUNT:
                break
        output.tags = _diverse_tag_subset(normalized_tags)
    if "seo_title" in fields:
        output.seo_title = _trim_at_word_boundary(output.seo_title, SEO_TITLE_MAX_LENGTH)
    if "seo_description" in fields:
        output.seo_description = _trim_at_word_boundary(output.seo_description, SEO_DESCRIPTION_MAX_LENGTH)
    if "seo_keywords" in fields:
        normalized_keywords: list[str] = []
        seen_keywords: set[str] = set()
        for value in _normalized_tags(output.seo_keywords):
            keyword = _trim_at_word_boundary(value, SEO_KEYWORD_MAX_LENGTH)
            if not keyword:
                continue
            key = keyword.casefold()
            if key in seen_keywords:
                continue
            normalized_keywords.append(keyword)
            seen_keywords.add(key)
            if len(normalized_keywords) == SEO_KEYWORD_COUNT:
                break
        output.seo_keywords = normalized_keywords

    if "description" in fields:
        output.description = _formatted_description(output.description)
    return output


def validate_etsy_output(
    output: ListingOutput,
    *,
    require_generation_quality: bool = True,
    generation_fields: set[str] | None = None,
) -> ListingOutput:
    fields = generation_fields or {
        "title", "description", "tags", "seo_title", "seo_description", "seo_keywords"
    }
    raw_tag_count = len(output.tags)
    raw_seo_keyword_count = len(output.seo_keywords)
    output.title = output.title.strip()
    output.description = output.description.strip()
    output.tags = _normalized_tags(output.tags)
    output.seo_title = output.seo_title.strip()
    output.seo_description = output.seo_description.strip()
    output.seo_keywords = _normalized_tags(output.seo_keywords)
    violations: list[str] = []
    if "title" in fields and not output.title:
        violations.append("title must not be empty")
    if "description" in fields and not output.description:
        violations.append("description must not be empty")
    if "title" in fields and len(output.title) > ETSY_TITLE_MAX_LENGTH:
        violations.append(f"title must be at most {ETSY_TITLE_MAX_LENGTH} characters (received {len(output.title)})")
    if "tags" in fields and len(output.tags) > ETSY_TAG_COUNT:
        violations.append(f"tags must contain at most {ETSY_TAG_COUNT} unique values (received {len(output.tags)})")
    if "tags" in fields and any(len(tag) > ETSY_TAG_MAX_LENGTH for tag in output.tags):
        violations.append(f"each tag must be at most {ETSY_TAG_MAX_LENGTH} characters")
    if (
        ("seo_title" in fields and len(output.seo_title) > ETSY_TITLE_MAX_LENGTH)
        or ("seo_description" in fields and len(output.seo_description) > 320)
    ):
        violations.append("SEO content exceeds configured limits")
    if require_generation_quality:
        title_tokens = _tokens(output.title)
        if "title" in fields and len(output.title) < ETSY_TITLE_MIN_LENGTH:
            violations.append(
                f"title must be {ETSY_TITLE_MIN_LENGTH}-{ETSY_TITLE_MAX_LENGTH} characters (received {len(output.title)})"
            )
        repeated_title_tokens = _repeated_title_tokens(output.title)
        if "title" in fields and repeated_title_tokens:
            violations.append(
                "title should not repeat words: " + ", ".join(repeated_title_tokens)
            )
        if "title" in fields and not _TITLE_FORMAT_RE.fullmatch(output.title):
            violations.append(
                "title must use comma-separated keyword phrases with only letters, numbers, spaces, and commas"
            )
        if "title" in fields and title_tokens:
            ending = title_tokens[-1]
            if len(ending) <= 2 and ending not in _ALLOWED_SHORT_TITLE_ENDINGS:
                violations.append("title must not end with an incomplete word or fragment")
        if "description" in fields and len(output.description) < ETSY_DESCRIPTION_MIN_LENGTH:
            violations.append(f"description must be at least {ETSY_DESCRIPTION_MIN_LENGTH} characters (received {len(output.description)})")
        description_paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", output.description)
            if paragraph.strip()
        ]
        if "description" in fields and not ETSY_DESCRIPTION_MIN_PARAGRAPHS <= len(description_paragraphs) <= ETSY_DESCRIPTION_MAX_PARAGRAPHS:
            violations.append(
                f"description must use 4-6 concise paragraphs separated by blank lines (received {len(description_paragraphs)})"
            )
        if "tags" in fields and (
            raw_tag_count != ETSY_TAG_COUNT or len(output.tags) != ETSY_TAG_COUNT
        ):
            violations.append(
                f"tags must contain exactly {ETSY_TAG_COUNT} unique, diverse search phrases "
                f"(received {len(output.tags)})"
            )
        if "tags" in fields:
            violations.extend(_tag_diversity_violations(output.tags))
        if "seo_title" in fields and not SEO_TITLE_MIN_LENGTH <= len(output.seo_title) <= SEO_TITLE_MAX_LENGTH:
            violations.append(
                f"SEO title must be {SEO_TITLE_MIN_LENGTH}-{SEO_TITLE_MAX_LENGTH} characters (received {len(output.seo_title)})"
            )
        if "seo_description" in fields and not SEO_DESCRIPTION_MIN_LENGTH <= len(output.seo_description) <= SEO_DESCRIPTION_MAX_LENGTH:
            violations.append(
                f"SEO description must be {SEO_DESCRIPTION_MIN_LENGTH}-{SEO_DESCRIPTION_MAX_LENGTH} characters (received {len(output.seo_description)})"
            )
        if "seo_keywords" in fields and (raw_seo_keyword_count != SEO_KEYWORD_COUNT or len(output.seo_keywords) != SEO_KEYWORD_COUNT):
            violations.append(
                f"SEO keywords must contain exactly {SEO_KEYWORD_COUNT} unique non-empty values (received {len(output.seo_keywords)})"
            )
        if "seo_keywords" in fields and any(len(keyword) > SEO_KEYWORD_MAX_LENGTH for keyword in output.seo_keywords):
            violations.append(
                f"each SEO keyword must be at most {SEO_KEYWORD_MAX_LENGTH} characters"
            )
    if violations:
        raise EtsyComplianceError("; ".join(violations))
    risky = ("trademark", "copyright", "licensed", "official", "medical", "certified", "eco", "sustainable")
    candidate = " ".join((output.title, output.description, *output.tags)).casefold()
    for term in risky:
        if term in candidate and not any(term in warning.casefold() for warning in output.warnings):
            output.warnings.append(f"Review the listing's {term} claim before publishing.")
    return output
