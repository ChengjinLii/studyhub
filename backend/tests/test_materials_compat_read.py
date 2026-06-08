from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services.materials_service import MaterialsService


def _build_service() -> MaterialsService:
    fake_storage = SimpleNamespace(build_signed_object_url=lambda **kwargs: None)
    fake_asset_store = SimpleNamespace(
        storage_provider=fake_storage,
        build_public_custom_preview_url=lambda **kwargs: "/preview.png",
    )
    fake_settings = SimpleNamespace(
        requires_private_env_file=True,
        async_read_db_enabled=True,
        resolved_material_asset_dir="/tmp/materials",
        material_signed_url_ttl_seconds=900,
        oss_public_base_url=None,
        oss_endpoint=None,
        oss_bucket=None,
    )
    return MaterialsService(fake_settings, read_repo=None, auth_repo=None, material_repo=None, asset_store=fake_asset_store)


def test_legacy_recommendations_limit_zero_keeps_all(monkeypatch) -> None:
    service = _build_service()
    rows = [
        {
            "id": 1,
            "uploader_id": 1,
            "title": "A",
            "description": "",
            "price": 0,
            "is_free": 1,
            "school": "电子科技大学",
            "college": None,
            "major": None,
            "is_general_education": 0,
            "file_key": None,
            "netdisk_url": None,
            "course_category": "MAJOR",
            "grade_type": "UG",
            "grade_value": "大二",
            "rating_avg": 0,
            "rating_count": 0,
            "like_count": 0,
            "view_count": 0,
            "download_count": 1,
            "sales_count": 0,
            "created_at": "2025-01-01T00:00:00Z",
            "uploader_username": "u1",
            "uploader_nickname": "n1",
            "keywords": None,
        },
        {
            "id": 2,
            "uploader_id": 2,
            "title": "B",
            "description": "",
            "price": 0,
            "is_free": 1,
            "school": "电子科技大学",
            "college": None,
            "major": None,
            "is_general_education": 0,
            "file_key": None,
            "netdisk_url": None,
            "course_category": "MAJOR",
            "grade_type": "UG",
            "grade_value": "大二",
            "rating_avg": 0,
            "rating_count": 0,
            "like_count": 0,
            "view_count": 0,
            "download_count": 2,
            "sales_count": 0,
            "created_at": "2025-01-02T00:00:00Z",
            "uploader_username": "u2",
            "uploader_nickname": "n2",
            "keywords": None,
        },
    ]
    monkeypatch.setattr(service, "_compat_load_material_rows", lambda *args, **kwargs: rows)
    monkeypatch.setattr(service, "_compat_load_user_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_compat_sort_material_rows", lambda items, **kwargs: list(items))
    monkeypatch.setattr(service, "_compat_load_tags_map", lambda *args, **kwargs: {})
    monkeypatch.setattr(service, "_compat_load_comment_counts", lambda *args, **kwargs: {})

    data = service.get_recommendations(session=None, current_user_id=None, limit=0)

    assert [item["id"] for item in data] == [1, 2]


def test_async_legacy_material_detail_keeps_user_state(monkeypatch) -> None:
    service = _build_service()
    row = {
        "id": 77,
        "uploader_id": 8,
        "uploader_username": "owner",
        "uploader_nickname": "Owner",
        "title": "通信原理真题",
        "description": "期末复习",
        "original_filename": "exam.pdf",
        "file_type": "pdf",
        "file_size": 4096,
        "price": 990,
        "is_free": 0,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "is_general_education": 0,
        "netdisk_url": "https://pan.example/file",
        "netdisk_password": "abcd",
        "netdisk_expired_at": None,
        "netdisk_reminder_at": None,
        "course_category": "MAJOR",
        "grade_type": "UG",
        "grade_value": "大二",
        "preview_watermark_enabled": 1,
        "preview_source": "MANUAL",
        "preview_manifest": None,
        "custom_preview_text": "preview",
        "custom_preview_images": "[\"custom-1.png\"]",
        "rating_avg": 4.5,
        "rating_count": 2,
        "like_count": 3,
        "view_count": 4,
        "download_count": 5,
        "sales_count": 6,
        "file_key": "materials/exam.pdf",
        "keywords": "版权方",
        "status": "VISIBLE",
    }

    async def fake_call(loader, *args, **kwargs):
        del kwargs
        name = loader.__name__
        if name == "_compat_load_material_detail_row_async":
            return row
        if name == "_compat_load_tags_map_async":
            return {77: ["真题", "期末"]}
        if name == "_compat_load_comment_counts_async":
            return {77: 11}
        if name == "_compat_load_versions_async":
            return [{"id": 1, "versionLabel": "v1"}]
        if name == "_compat_load_reviews_async":
            return [{"id": 2, "rating": 5}]
        if name == "_compat_material_relation_exists_async":
            sql = str(args[0])
            return "favorites" in sql
        if name == "_compat_load_my_rating_async":
            return 5
        if name == "_compat_has_paid_access_async":
            return True
        raise AssertionError(f"unexpected loader: {name}")

    async def fake_preview_urls(material_id, keys):
        return [f"/api/materials/{material_id}/assets/custom/{index + 1}" for index, _ in enumerate(keys)]

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)
    monkeypatch.setattr(service, "_compat_build_custom_preview_urls_async", fake_preview_urls)

    data = asyncio.run(service.get_detail_async(session=None, current_user_id=12, material_id=77, can_manage_all=False))

    assert data["id"] == 77
    assert data["tags"] == ["真题", "期末"]
    assert data["commentCount"] == 11
    assert data["favorited"] is True
    assert data["liked"] is False
    assert data["myRating"] == 5
    assert data["purchased"] is True
    assert data["netdiskAccessible"] is True
    assert data["customPreviewImages"] == ["/api/materials/77/assets/custom/1"]
    assert data["versions"] == [{"id": 1, "versionLabel": "v1"}]
    assert data["reviews"] == [{"id": 2, "rating": 5}]
