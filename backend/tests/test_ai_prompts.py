from __future__ import annotations

from app.ai.prompts import (
    build_listing_prompt,
    build_listing_fresh_quality_retry_prompt,
    build_listing_repair_prompt,
    build_listing_structure_retry_prompt,
)


def test_full_generation_prompt_requires_complete_listing_and_seo_output() -> None:
    prompt = build_listing_prompt({"design_description": "floral print"})

    assert "130-140 characters" in prompt
    assert "comma-separated buyer search keyword phrases" in prompt
    assert "letters, numbers, spaces, and commas" in prompt
    assert "comma is the only allowed punctuation" in prompt
    assert "exactly 13 unique, accurate, relevant tags" in prompt
    assert "genuinely different buyer intent" in prompt
    assert "description of at least 600 characters" in prompt
    assert "SEO title of 40-70 characters" in prompt
    assert "SEO description of 120-160 characters" in prompt
    assert "exactly 5 unique buyer search phrases" in prompt


def test_targeted_regeneration_prompt_names_only_requested_fields() -> None:
    prompt = build_listing_prompt({"design_description": "floral print"}, regenerate_fields=["title", "tags"])

    assert "Regenerate only these output fields: title, tags." in prompt
    assert "exactly 13 unique, accurate, relevant tags" in prompt
    assert "130-140 characters" in prompt
    assert "Do not repeat any content word" in prompt
    assert "near-duplicate phrase permutations" in prompt
    assert "at least 600 characters" not in prompt
    assert "SEO title" not in prompt
    assert "meaningfully different alternative" in prompt
    assert "only those requested fields and no others" in prompt
    assert "floral print" in prompt


def test_repair_prompt_only_contains_prior_output_and_validation_requirements() -> None:
    prompt = build_listing_repair_prompt(
        {"title": "Short", "description": "Too short", "tags": []},
        validation_error="tags must contain exactly 13 unique, diverse search phrases",
    )

    assert "<previous_output>" in prompt
    assert "exactly 13 unique, accurate" in prompt
    assert "tags must contain exactly 13" in prompt


def test_targeted_repair_prompt_requests_only_selected_fields() -> None:
    prompt = build_listing_repair_prompt(
        {"seo_title": "Repeated SEO title"},
        validation_error="regenerated fields must be meaningfully different",
        regenerate_fields=["seo_title"],
    )

    assert "only these requested fields and no others: seo_title" in prompt
    assert "complete JSON schema" not in prompt


def test_targeted_title_repair_requires_fresh_keyword_phrase_rewrite() -> None:
    prompt = build_listing_repair_prompt(
        {"title": "Keyword: phrase inventory"},
        validation_error="title must use commas as the only punctuation",
        regenerate_fields=["title"],
    )

    assert "Rewrite the prior title from scratch" in prompt
    assert "fresh comma-separated keyword phrases" in prompt
    assert "Use commas as the only punctuation" in prompt


def test_structure_retry_prompt_requests_fresh_json_without_prior_provider_content() -> None:
    prompt = build_listing_structure_retry_prompt(
        {"design_description": "floral print"}, regenerate_fields=["description"]
    )

    assert "Regenerate only these output fields: description." in prompt
    assert "previous attempt did not return a complete JSON object" in prompt
    assert "Return JSON only" in prompt
    assert "floral print" in prompt


def test_fresh_quality_retry_uses_clean_context_without_prior_output() -> None:
    prompt = build_listing_fresh_quality_retry_prompt(
        {
            "design_description": "floral print",
            "current_listing": {"title": "", "tags": []},
        },
        regenerate_fields=["title"],
    )

    assert "clean product facts only" in prompt
    assert "Do not reconstruct, paraphrase, or preserve" in prompt
    assert "previous_output" not in prompt
    assert "floral print" in prompt
