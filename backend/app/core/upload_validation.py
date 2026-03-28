from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings


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

    return validate_file_size(upload, max_size_bytes=max_size_bytes, too_large_detail=too_large_detail)
