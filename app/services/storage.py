"""Cloud-agnostic object storage.

Backends:
    local        — writes to LOCAL_STORAGE_DIR (dev only)
    s3           — AWS S3 via boto3 (default for AWS deployment)
    azure_blob   — Azure Blob Storage (stub; enable by installing azure-storage-blob)

Any callsite talks to ``StorageService`` — swapping clouds is a config change.
"""
from __future__ import annotations

import io
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

from flask import current_app


@dataclass
class StoredObject:
    backend: str
    key: str
    size_bytes: int
    content_type: str | None
    bucket: str | None = None


class _Backend(ABC):
    backend_name: str = ""

    @abstractmethod
    def put(self, key: str, fileobj: BinaryIO, content_type: str | None) -> StoredObject: ...

    @abstractmethod
    def get_url(self, key: str, ttl_seconds: int | None = None) -> str: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class LocalBackend(_Backend):
    backend_name = "local"

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _abs(self, key: str) -> str:
        # Prevent path traversal
        safe = os.path.normpath(key).lstrip(os.sep).replace("..", "_")
        return os.path.join(self.root, safe)

    def put(self, key: str, fileobj: BinaryIO, content_type: str | None) -> StoredObject:
        path = self._abs(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            data = fileobj.read()
            f.write(data)
        return StoredObject("local", key, len(data), content_type)

    def get_url(self, key: str, ttl_seconds: int | None = None) -> str:
        return f"/downloads/{key}"

    def delete(self, key: str) -> None:
        path = self._abs(key)
        if os.path.exists(path):
            os.remove(path)


class S3Backend(_Backend):
    backend_name = "s3"

    def __init__(self, bucket: str, region: str, prefix: str, url_ttl: int) -> None:
        import boto3  # local import to keep boto3 optional at runtime
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/"
        self.url_ttl = url_ttl
        self.client = boto3.client("s3", region_name=region)

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}{key.lstrip('/')}"

    def put(self, key: str, fileobj: BinaryIO, content_type: str | None) -> StoredObject:
        full = self._full_key(key)
        data = fileobj.read()
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=full, Body=data, **extra)
        return StoredObject("s3", full, len(data), content_type, self.bucket)

    def get_url(self, key: str, ttl_seconds: int | None = None) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_seconds or self.url_ttl,
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


class AzureBlobBackend(_Backend):
    """Stub — install azure-storage-blob to enable."""
    backend_name = "azure_blob"

    def __init__(self, connection_string: str, container: str) -> None:
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "azure-storage-blob is not installed. `pip install azure-storage-blob`"
            ) from e
        self.container = container
        self.client = BlobServiceClient.from_connection_string(connection_string)
        self.container_client = self.client.get_container_client(container)

    def put(self, key: str, fileobj: BinaryIO, content_type: str | None) -> StoredObject:
        from azure.storage.blob import ContentSettings  # type: ignore
        data = fileobj.read()
        self.container_client.upload_blob(
            name=key,
            data=data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type) if content_type else None,
        )
        return StoredObject("azure_blob", key, len(data), content_type, self.container)

    def get_url(self, key: str, ttl_seconds: int | None = None) -> str:
        # For real deployment, generate a SAS token. Placeholder here:
        return self.container_client.get_blob_client(key).url

    def delete(self, key: str) -> None:
        self.container_client.delete_blob(key)


class StorageService:
    """Facade used by the rest of the app. One instance per app."""

    def __init__(self, app=None) -> None:
        self._backend: _Backend | None = None
        self._backends: dict[str, _Backend] = {}
        if app is not None:
            self.init(app)

    def init(self, app) -> None:
        cfg = app.config
        backend = cfg["STORAGE_BACKEND"]
        if backend == "s3":
            fallback_bucket = cfg["AWS_S3_BUCKET"]
            platform_bucket = cfg["AWS_S3_PLATFORM_BUCKET"] or fallback_bucket
            operator_bucket = cfg["AWS_S3_OPERATOR_BUCKET"] or fallback_bucket
            common = dict(
                region=cfg["AWS_REGION"],
                prefix=cfg["AWS_S3_PREFIX"],
                url_ttl=cfg["AWS_S3_URL_TTL"],
            )
            self._backends = {
                "platform": S3Backend(bucket=platform_bucket, **common),
                "operator": S3Backend(bucket=operator_bucket, **common),
            }
            self._backend = self._backends["operator"]
        elif backend == "azure_blob":
            self._backend = AzureBlobBackend(
                connection_string=cfg["AZURE_STORAGE_CONNECTION_STRING"],
                container=cfg["AZURE_STORAGE_CONTAINER"],
            )
            self._backends = {"platform": self._backend, "operator": self._backend}
        else:
            self._backend = LocalBackend(root=cfg["LOCAL_STORAGE_DIR"])
            self._backends = {"platform": self._backend, "operator": self._backend}

    @property
    def backend(self) -> _Backend:
        if self._backend is None:
            self.init(current_app)
        assert self._backend is not None
        return self._backend

    @staticmethod
    def make_key(namespace: str, filename: str) -> str:
        ts = datetime.utcnow().strftime("%Y/%m/%d")
        rand = uuid.uuid4().hex[:12]
        safe_name = filename.replace("/", "_").replace("\\", "_")
        return f"{namespace.strip('/')}/{ts}/{rand}-{safe_name}"

    # -- public API --
    def upload(self, namespace: str, filename: str, stream: BinaryIO,
               content_type: str | None = None, scope: str = "operator") -> StoredObject:
        key = self.make_key(namespace, filename)
        backend = self._backends.get(scope) or self.backend
        return backend.put(key, stream, content_type)

    def signed_url(self, key: str, ttl_seconds: int | None = None,
                   scope: str = "operator", bucket: str | None = None) -> str:
        backend = self._backends.get(scope) or self.backend
        if bucket and isinstance(backend, S3Backend):
            backend = S3Backend(bucket=bucket,
                                region=current_app.config["AWS_REGION"],
                                prefix=current_app.config["AWS_S3_PREFIX"],
                                url_ttl=current_app.config["AWS_S3_URL_TTL"])
        return backend.get_url(key, ttl_seconds)

    def delete(self, key: str, scope: str = "operator") -> None:
        backend = self._backends.get(scope) or self.backend
        backend.delete(key)


# Module-level singleton — imported by blueprints
storage_service = StorageService()


def init_storage(app) -> None:
    storage_service.init(app)
