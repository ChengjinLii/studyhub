from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import mimetypes
from pathlib import Path
import re
import secrets
import shutil
from typing import Any, Protocol
from urllib.parse import quote

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings


UPLOAD_STREAM_CHUNK_SIZE = 1024 * 1024


class _CountingReader:
    def __init__(self, raw_file: Any) -> None:
        self.raw_file = raw_file
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.raw_file.read(size)
        self.bytes_read += len(chunk)
        return chunk


class StorageProvider(Protocol):
    provider_name: str

    def save_upload(self, *, root: Path, relative_dir: Path, upload: UploadFile, fallback_name: str) -> tuple[str, int]: ...
    async def save_upload_async(self, *, root: Path, relative_dir: Path, upload: UploadFile, fallback_name: str) -> tuple[str, int]: ...

    def delete_key(self, *, root: Path, key: str | None) -> None: ...
    async def delete_key_async(self, *, root: Path, key: str | None) -> None: ...

    def resolve_path(self, *, root: Path, key: str, invalid_detail: str) -> Path: ...
    def read_bytes(self, *, root: Path, key: str, max_size_bytes: int) -> bytes: ...
    async def read_bytes_async(self, *, root: Path, key: str, max_size_bytes: int) -> bytes: ...

    def copy_to_path(self, *, root: Path, key: str, destination: Path, max_size_bytes: int) -> int: ...

    def guess_media_type(self, key: str | None, default: str = "application/octet-stream") -> str: ...

    def build_public_url(self, *, root: Path, key: str) -> str | None: ...
    async def build_public_url_async(self, *, root: Path, key: str) -> str | None: ...

    def build_signed_download_url(
        self,
        *,
        root: Path,
        key: str,
        filename: str | None,
        ttl_seconds: int,
        content_type: str | None = None,
    ) -> tuple[str, str | None] | None: ...
    async def build_signed_download_url_async(
        self,
        *,
        root: Path,
        key: str,
        filename: str | None,
        ttl_seconds: int,
        content_type: str | None = None,
    ) -> tuple[str, str | None] | None: ...

    def build_signed_object_url(
        self,
        *,
        root: Path,
        key: str,
        ttl_seconds: int,
        process: str | None = None,
    ) -> str | None: ...
    async def build_signed_object_url_async(
        self,
        *,
        root: Path,
        key: str,
        ttl_seconds: int,
        process: str | None = None,
    ) -> str | None: ...

    def probe(self, *, root: Path, deep: bool = False) -> dict[str, Any]: ...
    async def probe_async(self, *, root: Path, deep: bool = False) -> dict[str, Any]: ...


class LocalFileStorageProvider:
    provider_name = "local_fs"

    def save_upload(self, *, root: Path, relative_dir: Path, upload: UploadFile, fallback_name: str) -> tuple[str, int]:
        original_name = upload.filename or fallback_name
        safe_name = self._sanitize_filename(original_name, fallback_name=fallback_name)
        relative_key = relative_dir / f"{secrets.token_hex(8)}-{safe_name}"
        target = root / relative_key
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            with target.open("wb") as output:
                while True:
                    chunk = upload.file.read(UPLOAD_STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    size += len(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return relative_key.as_posix(), size

    async def save_upload_async(
        self,
        *,
        root: Path,
        relative_dir: Path,
        upload: UploadFile,
        fallback_name: str,
    ) -> tuple[str, int]:
        return await asyncio.to_thread(
            self.save_upload,
            root=root,
            relative_dir=relative_dir,
            upload=upload,
            fallback_name=fallback_name,
        )

    def delete_key(self, *, root: Path, key: str | None) -> None:
        if not key or key.startswith("http://") or key.startswith("https://"):
            return
        try:
            path = self.resolve_path(root=root, key=key, invalid_detail="无效的文件路径")
        except HTTPException:
            return
        if path.exists():
            path.unlink()
        parent = path.parent
        root_resolved = root.resolve()
        while parent != root_resolved and parent.exists():
            if any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent

    async def delete_key_async(self, *, root: Path, key: str | None) -> None:
        await asyncio.to_thread(self.delete_key, root=root, key=key)

    def resolve_path(self, *, root: Path, key: str, invalid_detail: str) -> Path:
        root_resolved = root.resolve()
        path = (root / key).resolve()
        if root_resolved not in path.parents and path != root_resolved:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)
        return path

    def read_bytes(self, *, root: Path, key: str, max_size_bytes: int) -> bytes:
        path = self.resolve_path(root=root, key=key, invalid_detail="无效的文件路径")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(key)
        if path.stat().st_size > max_size_bytes:
            raise ValueError("file exceeds max_size_bytes")
        return path.read_bytes()

    async def read_bytes_async(self, *, root: Path, key: str, max_size_bytes: int) -> bytes:
        return await asyncio.to_thread(self.read_bytes, root=root, key=key, max_size_bytes=max_size_bytes)

    def copy_to_path(self, *, root: Path, key: str, destination: Path, max_size_bytes: int) -> int:
        source = self.resolve_path(root=root, key=key, invalid_detail="无效的文件路径")
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(key)
        if source.stat().st_size > max_size_bytes:
            raise ValueError("file exceeds max_size_bytes")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as input_file, destination.open("wb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=UPLOAD_STREAM_CHUNK_SIZE)
        return destination.stat().st_size

    def guess_media_type(self, key: str | None, default: str = "application/octet-stream") -> str:
        if not key:
            return default
        media_type, _ = mimetypes.guess_type(key)
        return media_type or default

    def build_public_url(self, *, root: Path, key: str) -> str | None:
        return None

    async def build_public_url_async(self, *, root: Path, key: str) -> str | None:
        return await asyncio.to_thread(self.build_public_url, root=root, key=key)

    def build_signed_download_url(
        self,
        *,
        root: Path,
        key: str,
        filename: str | None,
        ttl_seconds: int,
        content_type: str | None = None,
    ) -> tuple[str, str | None] | None:
        return None

    async def build_signed_download_url_async(
        self,
        *,
        root: Path,
        key: str,
        filename: str | None,
        ttl_seconds: int,
        content_type: str | None = None,
    ) -> tuple[str, str | None] | None:
        return await asyncio.to_thread(
            self.build_signed_download_url,
            root=root,
            key=key,
            filename=filename,
            ttl_seconds=ttl_seconds,
            content_type=content_type,
        )

    def build_signed_object_url(
        self,
        *,
        root: Path,
        key: str,
        ttl_seconds: int,
        process: str | None = None,
    ) -> str | None:
        del root, key, ttl_seconds, process
        return None

    async def build_signed_object_url_async(
        self,
        *,
        root: Path,
        key: str,
        ttl_seconds: int,
        process: str | None = None,
    ) -> str | None:
        return await asyncio.to_thread(
            self.build_signed_object_url,
            root=root,
            key=key,
            ttl_seconds=ttl_seconds,
            process=process,
        )

    def probe(self, *, root: Path, deep: bool = False) -> dict[str, Any]:
        del deep
        return {
            "status": "ok",
            "provider": self.provider_name,
            "root": str(root),
            "exists": root.exists(),
        }

    async def probe_async(self, *, root: Path, deep: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(self.probe, root=root, deep=deep)

    def _sanitize_filename(self, value: str, *, fallback_name: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", value).strip("-")
        if "." not in normalized:
            fallback_suffix = Path(fallback_name).suffix or ".bin"
            normalized = f"{normalized or Path(fallback_name).stem or 'file'}{fallback_suffix}"
        return normalized


class AliyunOssStorageProvider:
    provider_name = "oss"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def save_upload(self, *, root: Path, relative_dir: Path, upload: UploadFile, fallback_name: str) -> tuple[str, int]:
        safe_name = self._sanitize_filename(upload.filename or fallback_name, fallback_name=fallback_name)
        relative_key = self._build_relative_key(root, relative_dir / f"{secrets.token_hex(8)}-{safe_name}")
        metadata_headers = {
            "Content-Type": upload.content_type or self.guess_media_type(safe_name),
        }
        if metadata_headers["Content-Type"].startswith("image/"):
            metadata_headers["Cache-Control"] = "public, max-age=2592000, immutable"
        metadata_headers["Content-Disposition"] = self._build_content_disposition(safe_name)
        content = _CountingReader(upload.file)
        self._bucket().put_object(relative_key, content, headers=metadata_headers)
        return relative_key, content.bytes_read

    async def save_upload_async(
        self,
        *,
        root: Path,
        relative_dir: Path,
        upload: UploadFile,
        fallback_name: str,
    ) -> tuple[str, int]:
        return await asyncio.to_thread(
            self.save_upload,
            root=root,
            relative_dir=relative_dir,
            upload=upload,
            fallback_name=fallback_name,
        )

    def delete_key(self, *, root: Path, key: str | None) -> None:
        normalized_key = self._normalize_key_from_any(key)
        if not normalized_key:
            return
        try:
            self._bucket().delete_object(normalized_key)
        except Exception:
            return

    async def delete_key_async(self, *, root: Path, key: str | None) -> None:
        await asyncio.to_thread(self.delete_key, root=root, key=key)

    def resolve_path(self, *, root: Path, key: str, invalid_detail: str) -> Path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)

    def read_bytes(self, *, root: Path, key: str, max_size_bytes: int) -> bytes:
        del root
        normalized_key = self._normalize_key_from_any(key)
        if not normalized_key:
            raise FileNotFoundError(key)
        result = self._bucket().get_object(normalized_key)
        content = result.read(max_size_bytes + 1)
        if len(content) > max_size_bytes:
            raise ValueError("file exceeds max_size_bytes")
        return content

    async def read_bytes_async(self, *, root: Path, key: str, max_size_bytes: int) -> bytes:
        return await asyncio.to_thread(self.read_bytes, root=root, key=key, max_size_bytes=max_size_bytes)

    def copy_to_path(self, *, root: Path, key: str, destination: Path, max_size_bytes: int) -> int:
        del root
        normalized_key = self._normalize_key_from_any(key)
        if not normalized_key:
            raise FileNotFoundError(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = self._bucket().get_object(normalized_key)
        size = 0
        try:
            with destination.open("wb") as output_file:
                while True:
                    chunk = result.read(UPLOAD_STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_size_bytes:
                        raise ValueError("file exceeds max_size_bytes")
                    output_file.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return size

    def guess_media_type(self, key: str | None, default: str = "application/octet-stream") -> str:
        if not key:
            return default
        media_type, _ = mimetypes.guess_type(key)
        return media_type or default

    def build_public_url(self, *, root: Path, key: str) -> str | None:
        normalized_key = self._normalize_key_from_any(key)
        if not normalized_key:
            return None
        if self.settings.oss_public_base_url:
            base = self.settings.oss_public_base_url.rstrip("/")
            return f"{base}/{normalized_key}"
        endpoint = self.settings.oss_endpoint or ""
        endpoint_no_scheme = endpoint.removeprefix("https://").removeprefix("http://")
        return f"https://{self.settings.oss_bucket}.{endpoint_no_scheme}/{normalized_key}"

    async def build_public_url_async(self, *, root: Path, key: str) -> str | None:
        return await asyncio.to_thread(self.build_public_url, root=root, key=key)

    def build_signed_download_url(
        self,
        *,
        root: Path,
        key: str,
        filename: str | None,
        ttl_seconds: int,
        content_type: str | None = None,
    ) -> tuple[str, str | None] | None:
        normalized_key = self._normalize_key_from_any(key)
        if not normalized_key:
            return None
        expires_at = datetime.now(UTC) + timedelta(seconds=max(60, ttl_seconds))
        params = {}
        final_filename = filename or Path(normalized_key).name
        params["response-content-disposition"] = self._build_content_disposition(final_filename)
        # Some Aliyun OSS buckets reject signed URLs that override Content-Type.
        # The object metadata already carries Content-Type from upload time; keep
        # signed download URLs limited to Content-Disposition.
        del content_type
        url = self._bucket().sign_url(
            "GET",
            normalized_key,
            max(60, ttl_seconds),
            slash_safe=True,
            headers=None,
            params=params,
        )
        return url, expires_at.isoformat()

    async def build_signed_download_url_async(
        self,
        *,
        root: Path,
        key: str,
        filename: str | None,
        ttl_seconds: int,
        content_type: str | None = None,
    ) -> tuple[str, str | None] | None:
        return await asyncio.to_thread(
            self.build_signed_download_url,
            root=root,
            key=key,
            filename=filename,
            ttl_seconds=ttl_seconds,
            content_type=content_type,
        )

    def build_signed_object_url(
        self,
        *,
        root: Path,
        key: str,
        ttl_seconds: int,
        process: str | None = None,
    ) -> str | None:
        del root
        normalized_key = self._normalize_key_from_any(key)
        if not normalized_key:
            return None
        params = {"x-oss-process": process} if process else None
        return self._bucket().sign_url(
            "GET",
            normalized_key,
            max(60, ttl_seconds),
            slash_safe=True,
            headers=None,
            params=params,
        )

    async def build_signed_object_url_async(
        self,
        *,
        root: Path,
        key: str,
        ttl_seconds: int,
        process: str | None = None,
    ) -> str | None:
        return await asyncio.to_thread(
            self.build_signed_object_url,
            root=root,
            key=key,
            ttl_seconds=ttl_seconds,
            process=process,
        )

    def probe(self, *, root: Path, deep: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "provider": self.provider_name,
            "bucket": self.settings.oss_bucket,
            "endpoint": self.settings.oss_endpoint,
            "namespace": root.name,
        }
        if not deep:
            payload["mode"] = "configured"
            return payload
        bucket = self._bucket()
        info = bucket.get_bucket_info()
        payload["bucketRegion"] = getattr(getattr(info, "bucket", None), "location", None)
        return payload

    async def probe_async(self, *, root: Path, deep: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(self.probe, root=root, deep=deep)

    def _bucket(self):
        auth_module = self._import_oss2()
        auth = auth_module.Auth(self.settings.oss_access_key_id, self.settings.oss_access_key_secret)
        return auth_module.Bucket(auth, self.settings.oss_endpoint, self.settings.oss_bucket)

    def _build_relative_key(self, root: Path, relative_key: Path) -> str:
        namespace = root.name.strip("/").strip() or "assets"
        key_prefix = self.settings.oss_key_prefix.strip("/").strip()
        parts = [part for part in [key_prefix, namespace, relative_key.as_posix().strip("/")] if part]
        return "/".join(parts)

    def _normalize_key_from_any(self, key: str | None) -> str | None:
        if not key:
            return None
        value = key.strip()
        if value.startswith("http://") or value.startswith("https://"):
            public_base = (self.settings.oss_public_base_url or "").rstrip("/")
            if public_base and value.startswith(public_base + "/"):
                return value.removeprefix(public_base + "/")
            endpoint = (self.settings.oss_endpoint or "").removeprefix("https://").removeprefix("http://")
            host_prefix = f"https://{self.settings.oss_bucket}.{endpoint}/"
            if endpoint and value.startswith(host_prefix):
                return value.removeprefix(host_prefix)
        return value.lstrip("/").replace("\\", "/")

    def _sanitize_filename(self, value: str, *, fallback_name: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", value).strip("-")
        if "." not in normalized:
            fallback_suffix = Path(fallback_name).suffix or ".bin"
            normalized = f"{normalized or Path(fallback_name).stem or 'file'}{fallback_suffix}"
        return normalized

    def _build_content_disposition(self, filename: str) -> str:
        fallback = self._ascii_content_disposition_filename(filename)
        quoted = quote(filename, safe="")
        return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quoted}"

    def _ascii_content_disposition_filename(self, filename: str) -> str:
        candidate = Path(filename or "download").name.replace("\\", "_").replace('"', "_")
        suffix = Path(candidate).suffix if Path(candidate).suffix.isascii() else ""
        stem = Path(candidate).stem or candidate
        ascii_stem = stem.encode("ascii", "ignore").decode("ascii")
        ascii_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_stem).strip("_-")
        if not ascii_stem:
            ascii_stem = "download"
        return f"{ascii_stem}{suffix}" if suffix else ascii_stem

    def _import_oss2(self):
        try:
            import oss2  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Aliyun OSS provider 依赖缺失，请安装 oss2。") from exc
        return oss2
