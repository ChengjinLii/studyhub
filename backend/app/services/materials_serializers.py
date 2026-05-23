from __future__ import annotations

import json
from typing import Any

from app.models.materials import MaterialRecord
from app.services.read_support import serialize_datetime


def material_has_file(material: MaterialRecord) -> bool:
    return bool(
        material.file_storage_key
        or (material.delivery_method == "FILE" and (material.original_filename or material.file_type))
    )


def load_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    return value if isinstance(value, list) else []


def material_list_item(material: MaterialRecord) -> dict[str, Any]:
    return {
        "id": material.id,
        "uploaderId": material.uploader_id,
        "title": material.title,
        "description": material.description,
        "price": material.price / 100.0,
        "free": bool(material.is_free),
        "school": material.school,
        "college": material.college,
        "major": material.major,
        "generalEducation": bool(material.general_course),
        "hasFile": material_has_file(material),
        "hasNetdisk": bool(material.netdisk_url),
        "courseCategory": material.course_category,
        "gradeType": material.grade_type,
        "gradeValue": material.grade_value,
        "tags": load_json_list(material.tags_json),
        "previewWatermarkEnabled": material.preview_watermark_enabled,
        "previewSource": material.preview_source,
        "ratingAvg": material.rating_avg,
        "ratingCount": material.rating_count,
        "likeCount": material.like_count,
        "commentCount": material.comment_count,
        "viewCount": material.view_count,
        "downloadCount": material.download_count,
        "salesCount": material.sales_count,
        "createdAt": serialize_datetime(material.created_at),
        "uploaderUsername": material.uploader_username,
        "uploaderNickname": material.uploader_nickname,
        "copyrightOwner": material.copyright_owner,
    }


def admin_material_item(material: MaterialRecord) -> dict[str, Any]:
    return {
        "id": material.id,
        "title": material.title,
        "school": material.school,
        "college": material.college,
        "major": material.major,
        "gradeValue": material.grade_value,
        "gradeType": material.grade_type,
        "courseCategory": material.course_category,
        "tags": load_json_list(material.tags_json),
        "price": material.price / 100.0,
        "free": bool(material.is_free),
        "status": material.status,
        "reviewStatus": material.review_status,
        "uploaderId": material.uploader_id,
        "uploaderUsername": material.uploader_username,
        "uploaderNickname": material.uploader_nickname,
        "downloadCount": material.download_count,
        "salesCount": material.sales_count,
        "createdAt": serialize_datetime(material.created_at),
        "updatedAt": serialize_datetime(material.updated_at),
        "deletedAt": serialize_datetime(material.deleted_at),
    }
