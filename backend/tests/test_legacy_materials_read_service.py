from __future__ import annotations

from types import SimpleNamespace

from app.services.legacy_materials_read_service import LegacyMaterialsReadService


def _build_service() -> LegacyMaterialsReadService:
    fake_storage = SimpleNamespace(build_signed_object_url=lambda **kwargs: None)
    fake_asset_store = SimpleNamespace(
        storage_provider=fake_storage,
        build_public_custom_preview_url=lambda **kwargs: "/preview.png",
    )
    fake_settings = SimpleNamespace(
        resolved_material_asset_dir="/tmp/materials",
        material_signed_url_ttl_seconds=900,
    )
    return LegacyMaterialsReadService(fake_settings, fake_asset_store)


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
    monkeypatch.setattr(service, "_load_material_rows", lambda *args, **kwargs: rows)
    monkeypatch.setattr(service, "_load_user_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_sort_material_rows", lambda items, **kwargs: list(items))
    monkeypatch.setattr(service, "_load_tags_map", lambda *args, **kwargs: {})
    monkeypatch.setattr(service, "_load_comment_counts", lambda *args, **kwargs: {})

    data = service.get_recommendations(session=None, current_user_id=None, limit=0)

    assert [item["id"] for item in data] == [1, 2]
