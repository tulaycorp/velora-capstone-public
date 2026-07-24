from __future__ import annotations

import hashlib
import mmap
import re
import struct
import tempfile
import zlib
from dataclasses import dataclass
from typing import Any, Awaitable, BinaryIO, Callable

from fastapi import HTTPException, UploadFile
from starlette.responses import JSONResponse

from app.core.config import settings


UPLOAD_CHUNK_BYTES = 64 * 1024
PRODUCT_MOCKUP_UPLOAD_PATH = re.compile(r"^/products/[^/]+/mockups$")


@dataclass
class ValidatedMediaUpload:
    file: BinaryIO
    file_name: str
    content_type: str
    canonical_extension: str
    size_bytes: int
    checksum: str

    def close(self) -> None:
        self.file.close()


class BoundedMediaUploadMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or not is_media_upload_path(
            str(scope.get("path") or ""), str(scope.get("method") or "")
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        try:
            enforce_known_request_size(
                content_length.decode("ascii", errors="replace") if content_length else None
            )
        except HTTPException as exc:
            await JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})(scope, receive, send)
            return

        spool = tempfile.SpooledTemporaryFile(
            max_size=settings.upload_spool_memory_bytes,
            mode="w+b",
        )
        received_bytes = 0
        try:
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    return
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > settings.upload_max_request_bytes:
                    await JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                f"Upload request exceeds the "
                                f"{settings.upload_max_request_bytes} byte limit."
                            )
                        },
                    )(scope, receive, send)
                    return
                spool.write(body)
                if not message.get("more_body", False):
                    break

            spool.seek(0)
            remaining_bytes = received_bytes

            async def replay_receive() -> dict[str, Any]:
                nonlocal remaining_bytes
                if remaining_bytes > 0:
                    chunk = spool.read(min(UPLOAD_CHUNK_BYTES, remaining_bytes))
                    remaining_bytes -= len(chunk)
                    return {
                        "type": "http.request",
                        "body": chunk,
                        "more_body": remaining_bytes > 0,
                    }
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, replay_receive, send)
        finally:
            spool.close()


def enforce_known_request_size(content_length: str | None) -> None:
    if not content_length:
        return
    if not content_length.isdigit():
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
    declared_bytes = int(content_length)
    if declared_bytes > settings.upload_max_request_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload request exceeds the {settings.upload_max_request_bytes} byte limit.",
        )


def is_media_upload_path(path: str, method: str) -> bool:
    return method.upper() == "POST" and (
        path == "/design-assets" or PRODUCT_MOCKUP_UPLOAD_PATH.fullmatch(path) is not None
    )


def _validate_png(data: mmap.mmap, size_bytes: int) -> bool:
    if size_bytes < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    offset = 8
    saw_header = False
    saw_end = False
    while offset + 12 <= size_bytes:
        chunk_length = struct.unpack_from(">I", data, offset)[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + chunk_length
        if chunk_end > size_bytes:
            return False
        chunk_data = memoryview(data)[offset + 8 : offset + 8 + chunk_length]
        expected_crc = struct.unpack_from(">I", data, offset + 8 + chunk_length)[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        chunk_data.release()
        if actual_crc != expected_crc:
            return False
        if not saw_header:
            if chunk_type != b"IHDR" or chunk_length != 13:
                return False
            width, height = struct.unpack_from(">II", data, offset + 8)
            if width < 1 or height < 1:
                return False
            saw_header = True
        if chunk_type == b"IEND":
            if chunk_length != 0 or chunk_end != size_bytes:
                return False
            saw_end = True
            break
        offset = chunk_end
    return saw_header and saw_end


def _validate_jpeg(data: mmap.mmap, size_bytes: int) -> bool:
    if size_bytes < 12 or data[:3] != b"\xff\xd8\xff" or data[-2:] != b"\xff\xd9":
        return False
    offset = 2
    saw_dimensions = False
    saw_scan = False
    standalone_markers = {0x01, *range(0xD0, 0xDA)}
    start_of_frame_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset < size_bytes - 2:
        if data[offset] != 0xFF:
            return False
        while offset < size_bytes and data[offset] == 0xFF:
            offset += 1
        if offset >= size_bytes:
            return False
        marker = data[offset]
        offset += 1
        if marker in standalone_markers:
            continue
        if marker == 0xD9:
            break
        if offset + 2 > size_bytes:
            return False
        segment_length = struct.unpack_from(">H", data, offset)[0]
        if segment_length < 2 or offset + segment_length > size_bytes:
            return False
        if marker in start_of_frame_markers:
            if segment_length < 8:
                return False
            height, width = struct.unpack_from(">HH", data, offset + 3)
            if width < 1 or height < 1:
                return False
            saw_dimensions = True
        if marker == 0xDA:
            saw_scan = True
            scan_start = offset + segment_length
            return saw_dimensions and scan_start < size_bytes - 2 and data.find(b"\xff\xd9", scan_start) == size_bytes - 2
        offset += segment_length
    return saw_dimensions and saw_scan


def _validate_webp(data: mmap.mmap, size_bytes: int) -> bool:
    if size_bytes < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    if struct.unpack_from("<I", data, 4)[0] != size_bytes - 8:
        return False
    chunk_type = data[12:16]
    chunk_length = struct.unpack_from("<I", data, 16)[0]
    if 20 + chunk_length > size_bytes:
        return False
    if chunk_type == b"VP8X" and chunk_length >= 10:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width > 0 and height > 0
    if chunk_type == b"VP8L" and chunk_length >= 5 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1 > 0 and ((bits >> 14) & 0x3FFF) + 1 > 0
    if chunk_type == b"VP8 " and chunk_length >= 10 and data[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack_from("<HH", data, 26)
        return (width & 0x3FFF) > 0 and (height & 0x3FFF) > 0
    return False


def _detect_valid_media_type(file: BinaryIO, size_bytes: int) -> tuple[str, str] | None:
    file.flush()
    with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if _validate_png(data, size_bytes):
            return "image/png", ".png"
        if _validate_jpeg(data, size_bytes):
            return "image/jpeg", ".jpg"
        if _validate_webp(data, size_bytes):
            return "image/webp", ".webp"
    return None


async def read_validated_media_upload(file: UploadFile) -> ValidatedMediaUpload:
    declared_content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    allowed_types = {"image/png", "image/jpeg", "image/webp"}
    if declared_content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail="Upload a PNG, JPEG, or WebP image. SVG and other file types are not accepted.",
        )

    spool = tempfile.SpooledTemporaryFile(
        max_size=settings.upload_spool_memory_bytes,
        mode="w+b",
    )
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            size_bytes += len(chunk)
            if size_bytes > settings.upload_max_file_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded image exceeds the {settings.upload_max_file_bytes} byte file limit.",
                )
            digest.update(chunk)
            spool.write(chunk)

        if size_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded image is empty.")

        detected = _detect_valid_media_type(spool, size_bytes)
        if detected is None:
            raise HTTPException(
                status_code=415,
                detail="Uploaded image is malformed or its file signature is not supported.",
            )
        detected_content_type, canonical_extension = detected
        if detected_content_type != declared_content_type:
            raise HTTPException(
                status_code=415,
                detail="Uploaded image content does not match its declared content type.",
            )
        spool.seek(0)
        return ValidatedMediaUpload(
            file=spool,
            file_name=file.filename or f"upload{canonical_extension}",
            content_type=detected_content_type,
            canonical_extension=canonical_extension,
            size_bytes=size_bytes,
            checksum=digest.hexdigest(),
        )
    except Exception:
        spool.close()
        raise
