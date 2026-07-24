from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.ai.media import detect_image_content_type, image_data_url, prepare_ai_image


def _png_bytes(*, size: tuple[int, int], color: tuple[int, int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGBA", size, color).save(output, format="PNG")
    return output.getvalue()


def test_private_image_data_url_uses_valid_png_only() -> None:
    content = b"\x89PNG\r\n\x1a\nsmall-image"

    assert image_data_url(content, "image/png").startswith("data:image/png;base64,")


def test_private_image_rejects_spoofed_type() -> None:
    with pytest.raises(ValueError, match="does not match"):
        image_data_url(b"\x89PNG\r\n\x1a\nsmall-image", "image/jpeg")


def test_private_image_rejects_svg_and_malformed_content() -> None:
    with pytest.raises(ValueError, match="supports only"):
        detect_image_content_type(b"<svg></svg>")


def test_prepare_ai_image_resizes_flattens_and_compresses_without_touching_source() -> None:
    source = _png_bytes(size=(3200, 1600), color=(30, 120, 200, 128))

    prepared, content_type = prepare_ai_image(
        source,
        "image/png",
        max_bytes=100_000,
        max_dimension=2048,
        max_source_pixels=10_000_000,
        max_full_decode_pixels=10_000_000,
    )

    assert content_type == "image/jpeg"
    assert len(prepared) <= 100_000
    assert source.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(prepared)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (2048, 1024)


def test_prepare_ai_image_rejects_excessive_source_dimensions() -> None:
    source = _png_bytes(size=(100, 100), color=(255, 255, 255, 255))

    with pytest.raises(ValueError, match="dimensions exceed"):
        prepare_ai_image(
            source,
            "image/png",
            max_bytes=100_000,
            max_dimension=2048,
            max_source_pixels=9_999,
            max_full_decode_pixels=9_999,
        )


def test_prepare_ai_image_uses_jpeg_draft_decode_before_full_pixel_allocation() -> None:
    output = BytesIO()
    Image.new("RGB", (4096, 4096), "navy").save(output, format="JPEG", quality=95)

    prepared, content_type = prepare_ai_image(
        output.getvalue(),
        "image/jpeg",
        max_bytes=100_000,
        max_dimension=512,
        max_source_pixels=20_000_000,
        max_full_decode_pixels=1_000_000,
    )

    assert content_type == "image/jpeg"
    with Image.open(BytesIO(prepared)) as image:
        assert image.size == (512, 512)


def test_prepare_ai_image_keeps_full_decode_cap_for_large_pngs() -> None:
    source = _png_bytes(size=(1200, 1200), color=(255, 255, 255, 255))

    with pytest.raises(ValueError, match="too much memory"):
        prepare_ai_image(
            source,
            "image/png",
            max_bytes=100_000,
            max_dimension=512,
            max_source_pixels=2_000_000,
            max_full_decode_pixels=1_000_000,
        )
