from __future__ import annotations

import pytest

from app.ai.compliance import EtsyComplianceError, normalize_generated_output, validate_etsy_output
from app.ai.schemas import ListingOutput


DIVERSE_TAGS = [
    "botanical wall art",
    "colorful garden",
    "nature print",
    "modern floral decor",
    "living room accent",
    "gallery wall piece",
    "plant lover present",
    "housewarming idea",
    "office artwork",
    "abstract leaves",
    "organic shapes",
    "calm home style",
    "contemporary poster",
]


def _generation_output(**overrides: object) -> ListingOutput:
    values: dict[str, object] = {
        "title": "Colorful Botanical Matte Art Print with Teal Leaves and Coral Blooms for Contemporary Living Rooms, Creative Studios, or Home Offices",
        "description": "A vibrant botanical art print brings a considered garden-inspired focal point to a living room, bedroom, office, or creative studio.\n\nThe illustrated composition layers expressive color, organic shapes, and a calm contemporary mood for buyers who want nature-led decor without overwhelming a space.\n\nIt works beautifully in a gallery wall, above a desk, or as a thoughtful gift for an art lover, housewarming, birthday, or creative friend.\n\nReview the product details and selected options before ordering so the final listing accurately reflects the available format, size, and fulfillment choices.\n\nThis design is described from the supplied product context only, with no claims about materials, certifications, licensing, or dimensions beyond what the seller has verified.",
        "tags": DIVERSE_TAGS,
        "seo_title": "Botanical Wall Art Print for Modern Nature-Inspired Decor",
        "seo_description": "Shop a colorful botanical wall art print with expressive garden details, designed to bring a calm nature-inspired accent to modern rooms.",
        "seo_keywords": [
            "botanical wall art",
            "colorful garden print",
            "nature inspired decor",
            "modern floral poster",
            "living room wall art",
        ],
    }
    values.update(overrides)
    return ListingOutput(**values)


def test_etsy_validation_normalizes_tags_and_adds_risky_claim_warning() -> None:
    output = validate_etsy_output(_generation_output(
        title="Official Botanical Matte Art Print with Teal Leaves and Coral Blooms for Contemporary Living Rooms, Creative Studios, or Home Offices",
    ))

    assert len(output.tags) == 13
    assert any("official" in warning.casefold() for warning in output.warnings)


def test_etsy_generation_requires_full_length_title_without_repeated_words() -> None:
    with pytest.raises(EtsyComplianceError, match="130-140 characters"):
        validate_etsy_output(
            _generation_output(title="Colorful Botanical Matte Art Print")
        )

    with pytest.raises(EtsyComplianceError, match="should not repeat words"):
        validate_etsy_output(
            _generation_output(
                title="Botanical Wall Art Print with Colorful Botanical Leaves for Contemporary Living Rooms, Creative Studios, Offices, and Bedrooms"
            )
        )


def test_etsy_generation_accepts_comma_separated_keyword_phrases() -> None:
    output = validate_etsy_output(
        _generation_output(
            title="John Cena Championship Poster, Matte Paper Print, Signature Belt Artwork, Wrestling Fan Decor, Sports Wall Accent, Game Room Display"
        )
    )

    assert output.title.count(",") == 5


def test_etsy_generation_rejects_title_punctuation_other_than_commas() -> None:
    with pytest.raises(EtsyComplianceError, match="only letters, numbers, spaces, and commas"):
        validate_etsy_output(
            _generation_output(
                title="John Cena Championship Poster: Matte Paper Print, Signature Belt Artwork, Wrestling Fan Decor, Sports Wall Accent, Game Room Display"
            )
        )


def test_etsy_generation_requires_comma_separated_title_phrases() -> None:
    with pytest.raises(EtsyComplianceError, match="comma-separated keyword phrases"):
        validate_etsy_output(
            _generation_output(
                title="Colorful Botanical Matte Art Print with Teal Leaves and Coral Blooms for Contemporary Living Rooms Creative Studios or Home Offices"
            )
        )


def test_etsy_generation_rejects_incomplete_title_fragment() -> None:
    with pytest.raises(EtsyComplianceError, match="incomplete word"):
        validate_etsy_output(
            _generation_output(
                title="John Cena Championship Matte Poster Featuring His Title Belt and Signature Wrestling Pose for Fans, Game Rooms, Studios, Gyms, WW"
            )
        )


def test_etsy_generation_requires_exactly_thirteen_diverse_tags() -> None:
    with pytest.raises(EtsyComplianceError, match="exactly 13"):
        validate_etsy_output(_generation_output(tags=DIVERSE_TAGS[:8]))


def test_etsy_generation_rejects_repetitive_near_duplicate_tags() -> None:
    repetitive_tags = [
        "john cena poster",
        "john cena wall art",
        "john cena gift",
        "john cena wrestling",
        "wwe championship",
        "wwe championship art",
        "wwe wall decor",
        "wwe fan art",
        "wrestling poster",
        "wrestling decor",
        "matte paper",
    ]

    with pytest.raises(EtsyComplianceError, match="diverse array|near-duplicate"):
        validate_etsy_output(_generation_output(tags=repetitive_tags))


def test_generated_output_discards_repetitive_tags_and_keeps_diverse_subset() -> None:
    repetitive_tags = [
        "john cena poster",
        "wwe championship",
        "attitude adjustment",
        "matte paper",
        "wrestling decor",
        "wwe fan art",
        "john cena wall art",
        "wrestling poster",
        "wwe championship art",
        "john cena gift",
        "wwe wall decor",
        "wrestling fan gift",
        "john cena wrestling",
    ]

    output = normalize_generated_output(_generation_output(tags=repetitive_tags))

    assert 1 <= len(output.tags) < len(repetitive_tags)
    assert "wwe championship" in output.tags
    assert "wwe championship art" not in output.tags
    assert "john cena wrestling" not in output.tags
    with pytest.raises(EtsyComplianceError, match="exactly 13"):
        validate_etsy_output(output)


def test_etsy_validation_rejects_overlong_tags() -> None:
    with pytest.raises(EtsyComplianceError, match="20 characters"):
        validate_etsy_output(_generation_output(tags=["x" * 21, *DIVERSE_TAGS[1:]]))


def test_etsy_generation_requires_scannable_description_paragraphs() -> None:
    dense_description = _generation_output().description.replace("\n\n", " ")

    with pytest.raises(EtsyComplianceError, match="4-6 concise paragraphs"):
        validate_etsy_output(_generation_output(description=dense_description))


def test_etsy_generation_requires_complete_seo_fields() -> None:
    with pytest.raises(EtsyComplianceError, match="SEO title"):
        validate_etsy_output(
            _generation_output(
                seo_title="",
                seo_description="",
                seo_keywords=[],
            )
        )


def test_generated_output_safely_normalizes_model_limit_overshoot() -> None:
    output = _generation_output(
        title=(
            "John Cena Championship Poster, Matte Paper Wall Art, Signature Belt Pose, Wrestling Fan "
            "Decor, Sports Gift, Game Room Display, Home Gym Print"
        ),
        tags=["botanical wall artwork", *DIVERSE_TAGS[1:], "extra decor phrase"],
    )

    normalized = normalize_generated_output(output)

    assert len(normalized.title) <= 140
    assert not normalized.title.endswith(",")
    assert len(normalized.tags) == 13
    assert all(len(tag) <= 20 for tag in normalized.tags)
    assert validate_etsy_output(normalized) is normalized


def test_generated_output_restores_blank_lines_between_model_paragraphs() -> None:
    paragraphs = _generation_output().description.split("\n\n")
    output = normalize_generated_output(
        _generation_output(description="\n".join(paragraphs))
    )

    assert output.description.count("\n\n") == len(paragraphs) - 1
    assert validate_etsy_output(output) is output


def test_generated_output_losslessly_reflows_dense_description() -> None:
    dense_description = _generation_output().description.replace("\n\n", " ")
    output = normalize_generated_output(
        _generation_output(description=dense_description)
    )

    paragraphs = output.description.split("\n\n")
    assert 4 <= len(paragraphs) <= 6
    assert output.description.replace("\n\n", " ") == dense_description
    assert validate_etsy_output(output) is output


def test_selective_apply_does_not_require_generated_tag_or_description_targets() -> None:
    output = validate_etsy_output(
        ListingOutput(title="Edited title", description="Edited description", tags=["edited tag"]),
        require_generation_quality=False,
    )

    assert output.tags == ["edited tag"]
