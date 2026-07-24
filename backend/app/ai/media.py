from __future__ import annotations

import base64
from io import BytesIO
from threading import Lock
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


IMAGE_SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"RIFF", "image/webp"))
_IMAGE_OPEN_LOCK = Lock()


def _open_image_with_source_limit(content: bytes, max_source_pixels: int) -> Image.Image:
    # Pillow checks dimensions while opening, before JPEG draft decoding can reduce
    # memory. Temporarily align its process-global guard with our explicit source
    # ceiling, then restore it before any pixel data is decoded.
    with _IMAGE_OPEN_LOCK:
        previous_limit = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = max_source_pixels
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                return Image.open(BytesIO(content))
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit


def detect_image_content_type(content: bytes) -> str:
    for signature, content_type in IMAGE_SIGNATURES:
        if content.startswith(signature):
            if content_type != "image/webp" or content[8:12] == b"WEBP":
                return content_type
    raise ValueError("AI listing generation supports only valid PNG, JPEG, or WebP design images.")


def image_data_url(content: bytes, content_type: str) -> str:
    detected = detect_image_content_type(content)
    if detected != content_type:
        raise ValueError("The design image type does not match its stored content type.")
    return f"data:{detected};base64,{base64.b64encode(content).decode('ascii')}"


def prepare_ai_image(
    content: bytes,
    content_type: str,
    *,
    max_bytes: int,
    max_dimension: int,
    max_source_pixels: int,
    max_full_decode_pixels: int,
) -> tuple[bytes, str]:
    """Create a bounded JPEG derivative for model input without changing storage."""
    detected = detect_image_content_type(content)
    if detected != content_type:
        raise ValueError("The design image type does not match its stored content type.")
    if (
        max_bytes < 1
        or max_dimension < 1
        or max_source_pixels < 1
        or max_full_decode_pixels < 1
    ):
        raise ValueError("AI image limits must be positive.")

    try:
        with _open_image_with_source_limit(content, max_source_pixels) as source:
            width, height = source.size
            source_pixels = width * height
            if width < 1 or height < 1 or source_pixels > max_source_pixels:
                raise ValueError("The design image dimensions exceed the AI safety limit.")
            if detected == "image/jpeg":
                source.draft("RGB", (max_dimension, max_dimension))
            elif source_pixels > max_full_decode_pixels:
                raise ValueError(
                    "The design image requires too much memory to prepare for AI generation."
                )
            source.load()
            oriented = ImageOps.exif_transpose(source)
            oriented.thumbnail(
                (max_dimension, max_dimension),
                Image.Resampling.LANCZOS,
            )
            if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                prepared = Image.new("RGB", rgba.size, "white")
                prepared.paste(rgba, mask=rgba.getchannel("A"))
            else:
                prepared = oriented.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise ValueError("The design image dimensions exceed the AI safety limit.") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The saved design image could not be decoded for AI generation.") from exc

    candidate = prepared
    for scale_attempt in range(5):
        for quality in (88, 80, 72, 64, 56, 48):
            output = BytesIO()
            candidate.save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            encoded = output.getvalue()
            if len(encoded) <= max_bytes:
                return encoded, "image/jpeg"

        if scale_attempt == 4 or min(candidate.size) <= 512:
            break
        next_size = (
            max(512, int(candidate.width * 0.8)),
            max(512, int(candidate.height * 0.8)),
        )
        resized = candidate.copy()
        resized.thumbnail(next_size, Image.Resampling.LANCZOS)
        candidate = resized

    raise ValueError("The design image could not be compressed within the AI image-size limit.")


def prepare_ai_image_data_url(
    content: bytes,
    content_type: str,
    *,
    max_bytes: int,
    max_dimension: int,
    max_source_pixels: int,
    max_full_decode_pixels: int,
) -> str:
    prepared, prepared_content_type = prepare_ai_image(
        content,
        content_type,
        max_bytes=max_bytes,
        max_dimension=max_dimension,
        max_source_pixels=max_source_pixels,
        max_full_decode_pixels=max_full_decode_pixels,
    )
    return image_data_url(prepared, prepared_content_type)
