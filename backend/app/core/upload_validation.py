from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings


SUPPORTED_IMAGE_VERIFY_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}
SUPPORTED_IMAGE_VERIFY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
ZIP_CONTAINER_EXTENSIONS = {".zip", ".docx", ".xlsx", ".pptx"}
OLE_DOCUMENT_EXTENSIONS = {".doc", ".xls", ".ppt"}
MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".xlsx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".pptx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".ppt": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
    ".bmp": (b"BM",),
    ".rar": (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"),
    ".7z": (b"7z\xbc\xaf\x27\x1c",),
}


def detect_upload_size(upload: UploadFile) -> int:
    current = upload.file.tell()
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(current)
    return size


def validate_file_size(upload: UploadFile, *, max_size_bytes: int, too_large_detail: str) -> int:
    size = detect_upload_size(upload)
    if size > max_size_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=too_large_detail)
    return size


def _read_upload_bytes(upload: UploadFile, *, max_bytes: int | None = None) -> bytes:
    current = upload.file.tell()
    upload.file.seek(0)
    content = upload.file.read() if max_bytes is None else upload.file.read(max_bytes)
    upload.file.seek(current)
    return content


def _validate_known_magic(suffix: str, prefix: bytes, *, invalid_detail: str) -> None:
    expected_prefixes = MAGIC_PREFIXES.get(suffix)
    if not expected_prefixes:
        return
    if suffix == ".webp":
        if not (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)
        return
    if not any(prefix.startswith(expected) for expected in expected_prefixes):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)


def _validate_zip_container(upload: UploadFile, *, suffix: str, invalid_detail: str) -> None:
    if suffix not in ZIP_CONTAINER_EXTENSIONS:
        return
    content = _read_upload_bytes(upload)
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)
            total_uncompressed = 0
            for entry in entries:
                normalized_name = entry.filename.replace("\\", "/")
                parts = [part for part in normalized_name.split("/") if part]
                if normalized_name.startswith("/") or any(part == ".." for part in parts):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)
                total_uncompressed += int(entry.file_size or 0)
                if total_uncompressed > 200 * 1024 * 1024:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail)
    except HTTPException:
        raise
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_detail) from exc


def validate_material_upload(
    upload: UploadFile,
    *,
    max_size_bytes: int,
    missing_detail: str,
    invalid_type_detail: str,
    too_large_detail: str,
) -> int:
    filename = (upload.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=missing_detail)

    suffix = Path(filename).suffix.strip().lower()
    size = validate_file_size(upload, max_size_bytes=max_size_bytes, too_large_detail=too_large_detail)
    if not suffix:
        return size

    prefix = _read_upload_bytes(upload, max_bytes=16)
    _validate_known_magic(suffix, prefix, invalid_detail=invalid_type_detail)
    _validate_zip_container(upload, suffix=suffix, invalid_detail=invalid_type_detail)
    return size


def validate_image_upload(
    upload: UploadFile,
    *,
    settings: Settings,
    max_size_bytes: int,
    missing_detail: str,
    invalid_type_detail: str,
    too_large_detail: str,
) -> int:
    filename = (upload.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=missing_detail)

    content_type = (upload.content_type or "").strip().lower()
    suffix = Path(filename).suffix.strip().lower()

    allowed_mime_types = settings.resolved_safe_image_mime_types
    allowed_extensions = settings.resolved_safe_image_extensions

    if not content_type or content_type not in allowed_mime_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_type_detail)
    if not suffix or suffix not in allowed_extensions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_type_detail)

    size = validate_file_size(upload, max_size_bytes=max_size_bytes, too_large_detail=too_large_detail)
    if content_type in SUPPORTED_IMAGE_VERIFY_MIME_TYPES and suffix in SUPPORTED_IMAGE_VERIFY_EXTENSIONS:
        current = upload.file.tell()
        try:
            upload.file.seek(0)
            with Image.open(upload.file) as image:
                image.verify()
        except (SyntaxError, UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=invalid_type_detail) from exc
        finally:
            upload.file.seek(current)
    return size
