from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    public_url: str | None
    checksum: str
    size_bytes: int


@dataclass(frozen=True)
class StorageObjectInfo:
    storage_key: str
    last_modified: datetime
    size_bytes: int


class S3StorageService:
    def __init__(self) -> None:
        self.endpoint_url = settings.storage_endpoint_url
        self.access_key_id = settings.storage_access_key_id
        self.secret_access_key = settings.storage_secret_access_key
        self.bucket_name = settings.storage_bucket_name
        self.region_name = settings.storage_region_name
        self._client_instance = None

    def is_configured(self) -> bool:
        return bool(self.bucket_name and self.access_key_id and self.secret_access_key)

    def _client(self):
        if not self.is_configured():
            raise RuntimeError("S3-compatible storage is not configured.")
        if self._client_instance is None:
            self._client_instance = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name=self.region_name,
            )
        return self._client_instance

    def build_public_url(self, storage_key: str) -> str | None:
        if not self.is_configured():
            return None
        client = self._client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": storage_key},
            ExpiresIn=settings.storage_presign_get_ttl_seconds,
        )

    def upload_file(
        self,
        *,
        storage_key: str,
        file: Any,
        size_bytes: int,
        checksum: str,
        content_type: str,
        file_name: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        client = self._client()
        safe_file_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file_name).name).strip("._") or "image"
        put_kwargs: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": storage_key,
            "Body": file,
            "ContentLength": size_bytes,
            "ContentType": content_type,
            "ContentDisposition": f'inline; filename="{safe_file_name}"',
            "CacheControl": "private, max-age=300, no-transform",
        }
        if metadata:
            put_kwargs["Metadata"] = metadata
        client.put_object(**put_kwargs)
        return StoredObject(
            storage_key=storage_key,
            public_url=self.build_public_url(storage_key),
            checksum=checksum,
            size_bytes=size_bytes,
        )

    def upload_bytes(
        self,
        *,
        storage_key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        from io import BytesIO

        return self.upload_file(
            storage_key=storage_key,
            file=BytesIO(content),
            size_bytes=len(content),
            checksum=hashlib.sha256(content).hexdigest(),
            content_type=content_type,
            file_name=storage_key.rsplit("/", 1)[-1],
            metadata=metadata,
        )

    def copy_object(self, source_key: str, target_key: str) -> None:
        client = self._client()
        client.copy_object(
            Bucket=self.bucket_name,
            CopySource={"Bucket": self.bucket_name, "Key": source_key},
            Key=target_key,
        )

    def object_exists(self, storage_key: str) -> bool:
        client = self._client()
        try:
            client.head_object(Bucket=self.bucket_name, Key=storage_key)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def delete_object(self, storage_key: str) -> None:
        client = self._client()
        client.delete_object(Bucket=self.bucket_name, Key=storage_key)

    def list_objects(self, prefix: str) -> list[StorageObjectInfo]:
        client = self._client()
        paginator = client.get_paginator("list_objects_v2")
        objects: list[StorageObjectInfo] = []
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            for item in page.get("Contents", []):
                storage_key = item.get("Key")
                last_modified = item.get("LastModified")
                if not isinstance(storage_key, str) or not isinstance(last_modified, datetime):
                    continue
                objects.append(
                    StorageObjectInfo(
                        storage_key=storage_key,
                        last_modified=last_modified,
                        size_bytes=int(item.get("Size") or 0),
                    )
                )
        return objects

    def read_bytes_limited(self, storage_key: str, *, max_bytes: int) -> bytes:
        client = self._client()
        response = client.get_object(Bucket=self.bucket_name, Key=storage_key)
        content_length = response.get("ContentLength")
        if isinstance(content_length, int) and content_length > max_bytes:
            raise ValueError("The design image exceeds the AI image-size limit.")
        body = response["Body"]
        content = body.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("The design image exceeds the AI image-size limit.")
        return content


storage_service = S3StorageService()


def get_storage_service() -> S3StorageService:
    return storage_service
