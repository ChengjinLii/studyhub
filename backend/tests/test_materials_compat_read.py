from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.repos.material_repo import MaterialRepository
from app.services.materials_service import MaterialsService


class _MappingResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def mappings(self):
        return self

    def first(self) -> dict[str, Any]:
        return self.row


class _RowsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar(self) -> int:
        return self.value


class _StatsSession:
    def __init__(self) -> None:
        self.material_queries = 0
        self.user_queries = 0

    def execute(self, statement, params=None):
        del params
        sql = " ".join(str(statement).lower().split())
        if "from materials" in sql:
            self.material_queries += 1
            return _MappingResult({"total_materials": 4, "free_materials": 2, "total_downloads": 17})
        if "from users" in sql:
            self.user_queries += 1
            return _ScalarResult(3)
        raise AssertionError(f"unexpected SQL: {statement}")


class _AsyncStatsSession(_StatsSession):
    async def execute(self, statement, params=None):
        return super().execute(statement, params)


class _TagsSession:
    def __init__(self) -> None:
        self.tag_queries = 0

    def execute(self, statement, params=None):
        assert params == {"limit": 30}
        sql = " ".join(str(statement).lower().split())
        if "from material_tags" in sql:
            self.tag_queries += 1
            return _RowsResult([{"tag": "真题"}, {"tag": "解析"}])
        raise AssertionError(f"unexpected SQL: {statement}")


def _build_service() -> MaterialsService:
    fake_storage = SimpleNamespace(build_signed_object_url=lambda **kwargs: None)
    fake_asset_store = SimpleNamespace(
        storage_provider=fake_storage,
        build_public_custom_preview_url=lambda **kwargs: "/preview.png",
        build_preview_url=lambda **kwargs: (
            f"/preview/{kwargs['material_id']}/{kwargs['index']}/"
            f"{'placeholder' if kwargs.get('placeholder') else 'image'}/{kwargs.get('key') or 'none'}"
        ),
        build_download_url=lambda **kwargs: (f"/download/{kwargs['material_id']}/{kwargs['key']}", "expires"),
    )
    fake_settings = SimpleNamespace(
        requires_private_env_file=True,
        async_read_db_enabled=True,
        resolved_material_asset_dir="/tmp/materials",
        material_signed_url_ttl_seconds=900,
        material_preview_pages_large=5,
        material_preview_pages_small=3,
        oss_public_base_url=None,
        oss_endpoint=None,
        oss_bucket=None,
    )
    return MaterialsService(fake_settings, read_repo=None, auth_repo=None, material_repo=MaterialRepository(), asset_store=fake_asset_store)


def test_legacy_material_stats_uses_single_materials_aggregate_query() -> None:
    service = _build_service()
    session = _StatsSession()

    data = service._compat_load_material_stats(session)  # type: ignore[arg-type]

    assert data == {"totalMaterials": 4, "freeMaterials": 2, "totalDownloads": 17, "userCount": 3}
    assert session.material_queries == 1
    assert session.user_queries == 1


def test_compat_preview_uses_legacy_file_key_without_new_material_columns() -> None:
    service = _build_service()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    uploader_id INTEGER NULL,
                    title VARCHAR(80) NOT NULL,
                    file_type VARCHAR(32) NULL,
                    file_key VARCHAR(512) NULL,
                    preview_source VARCHAR(16) NOT NULL DEFAULT 'AUTO',
                    preview_manifest TEXT NULL,
                    custom_preview_images TEXT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'VISIBLE'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO materials (
                    id, uploader_id, title, file_type, file_key, preview_source,
                    preview_manifest, custom_preview_images, status
                )
                VALUES (
                    41, 7, 'Legacy PDF', 'pdf', 'files/legacy.pdf', 'AUTO',
                    :manifest, '[]', 'VISIBLE'
                )
                """
            ),
            {
                "manifest": json.dumps(
                    {
                        "pageCount": 5,
                        "previewPages": 3,
                        "pages": [
                            {"key": "materials/41/preview/p001.jpg", "index": 1, "width": 900, "height": 506},
                            {"key": "materials/41/preview/p002.jpg", "index": 2, "width": 900, "height": 506},
                            {"key": "materials/41/preview/p003.jpg", "index": 3, "width": 900, "height": 506},
                        ],
                    },
                    ensure_ascii=False,
                )
            },
        )

    with Session(engine) as session:
        preview = service.get_preview(session, 41, user_id=1, can_manage_all=False)

    assert preview["status"] == "done"
    assert preview["pageCount"] == 5
    assert preview["previewPages"] == 3
    assert [image["img"]["src"] for image in preview["images"]] == [
        "/preview/41/1/image/materials/41/preview/p001.jpg",
        "/preview/41/2/image/materials/41/preview/p002.jpg",
        "/preview/41/3/image/materials/41/preview/p003.jpg",
    ]
    assert preview["images"][0]["width"] == 900
    assert preview["images"][0]["height"] == 506


def test_compat_download_uses_legacy_file_key_and_download_columns() -> None:
    service = _build_service()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    uploader_id INTEGER NULL,
                    title VARCHAR(80) NOT NULL,
                    original_filename VARCHAR(255) NULL,
                    file_type VARCHAR(32) NULL,
                    file_size INTEGER NULL,
                    file_key VARCHAR(512) NULL,
                    is_free INTEGER NOT NULL DEFAULT 1,
                    netdisk_url TEXT NULL,
                    netdisk_password VARCHAR(64) NULL,
                    netdisk_expired_at DATE NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'VISIBLE',
                    download_count INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    role_mask INTEGER NOT NULL DEFAULT 1,
                    free_download_quota INTEGER NOT NULL DEFAULT 200,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE material_downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    material_id INTEGER NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO materials (
                    id, uploader_id, title, original_filename, file_type, file_size, file_key,
                    is_free, netdisk_url, netdisk_password, netdisk_expired_at, status, download_count
                )
                VALUES (41, 7, 'Legacy PDF', 'legacy.pdf', 'pdf', 1024, 'materials/41/file.pdf', 1, NULL, NULL, NULL, 'VISIBLE', 0)
                """
            )
        )
        connection.execute(text("INSERT INTO users (id, role_mask, free_download_quota) VALUES (1, 1, 200)"))

    with Session(engine) as session:
        payload = service.generate_download(session, 41, user_id=1, role_mask=1)

    assert payload == {"url": "/download/41/materials/41/file.pdf", "expiresAt": "expires"}
    with engine.connect() as connection:
        downloads = connection.execute(text("SELECT COUNT(*) FROM material_downloads")).scalar_one()
        download_count = connection.execute(text("SELECT download_count FROM materials WHERE id = 41")).scalar_one()
        quota = connection.execute(text("SELECT free_download_quota FROM users WHERE id = 1")).scalar_one()
    assert downloads == 1
    assert download_count == 1
    assert quota == 199


def test_compat_download_quota_update_does_not_overdraw() -> None:
    service = _build_service()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    uploader_id INTEGER NULL,
                    title VARCHAR(80) NOT NULL,
                    original_filename VARCHAR(255) NULL,
                    file_type VARCHAR(20) NULL,
                    file_size INTEGER NULL,
                    file_key VARCHAR(255) NULL,
                    is_free BOOLEAN NOT NULL DEFAULT 1,
                    netdisk_url VARCHAR(500) NULL,
                    netdisk_password VARCHAR(50) NULL,
                    netdisk_expired_at DATE NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'PUBLISHED',
                    download_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    role_mask INTEGER NOT NULL DEFAULT 1,
                    free_download_quota INTEGER NOT NULL DEFAULT 200,
                    updated_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE material_downloads (
                    id INTEGER PRIMARY KEY,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO materials (
                    id, uploader_id, title, original_filename, file_type, file_size, file_key,
                    is_free, netdisk_url, netdisk_password, netdisk_expired_at, status, download_count
                )
                VALUES (41, 7, 'Legacy PDF', 'legacy.pdf', 'pdf', 1024, 'materials/41/file.pdf', 1, NULL, NULL, NULL, 'VISIBLE', 0)
                """
            )
        )
        connection.execute(text("INSERT INTO users (id, role_mask, free_download_quota) VALUES (1, 1, 0)"))

    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc:
            service.generate_download(session, 41, user_id=1, role_mask=1)
        assert exc.value.status_code == 403
        assert exc.value.detail == "DOWNLOAD_QUOTA_EXHAUSTED"

    with engine.connect() as connection:
        downloads = connection.execute(text("SELECT COUNT(*) FROM material_downloads")).scalar_one()
        download_count = connection.execute(text("SELECT download_count FROM materials WHERE id = 41")).scalar_one()
        quota = connection.execute(text("SELECT free_download_quota FROM users WHERE id = 1")).scalar_one()
    assert downloads == 0
    assert download_count == 0
    assert quota == 0


def test_compat_record_view_accepts_legacy_visible_material_status() -> None:
    service = _build_service()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE materials (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(80) NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'PUBLISHED',
                    view_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE material_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    user_id INTEGER NULL,
                    viewer_token_hash VARCHAR(128) NULL,
                    viewed_at DATETIME NULL
                )
                """
            )
        )
        connection.execute(text("INSERT INTO materials (id, title, status, view_count) VALUES (41, 'Legacy PDF', 'PUBLISHED', 5)"))

    with Session(engine) as session:
        viewer_context = {"client": "203.0.113.10", "userAgent": "StudyHub Test Browser"}
        first = service.record_view(session, 41, user_id=None, can_manage_all=False, viewer_token="viewer-a", viewer_context=viewer_context)
        second = service.record_view(session, 41, user_id=None, can_manage_all=False, viewer_token="viewer-b", viewer_context=viewer_context)

    with engine.connect() as connection:
        view_count = connection.execute(text("SELECT view_count FROM materials WHERE id = 41")).scalar_one()
        records = connection.execute(text("SELECT COUNT(*) FROM material_views WHERE material_id = 41")).scalar_one()

    assert first == 6
    assert second == 6
    assert view_count == 6
    assert records == 1


def test_legacy_material_summary_cache_reuses_stats_until_invalidated() -> None:
    service = _build_service()
    session = _StatsSession()

    first = service._compat_load_material_stats(session)  # type: ignore[arg-type]
    first["totalMaterials"] = 999
    second = service._compat_load_material_stats(session)  # type: ignore[arg-type]

    assert second == {"totalMaterials": 4, "freeMaterials": 2, "totalDownloads": 17, "userCount": 3}
    assert session.material_queries == 1
    assert session.user_queries == 1

    service.invalidate_material_summary_cache()
    refreshed = service._compat_load_material_stats(session)  # type: ignore[arg-type]

    assert refreshed["totalMaterials"] == 4
    assert session.material_queries == 2
    assert session.user_queries == 2


def test_legacy_material_summary_cache_reuses_available_tags_until_invalidated() -> None:
    service = _build_service()
    session = _TagsSession()

    first = service._compat_load_available_tags(session)  # type: ignore[arg-type]
    first.append("污染")
    second = service._compat_load_available_tags(session)  # type: ignore[arg-type]

    assert second == ["真题", "解析"]
    assert session.tag_queries == 1

    service.invalidate_material_summary_cache()
    assert service._compat_load_available_tags(session) == ["真题", "解析"]  # type: ignore[arg-type]
    assert session.tag_queries == 2


def test_async_legacy_material_stats_uses_single_materials_aggregate_query() -> None:
    service = _build_service()
    session = _AsyncStatsSession()

    data = asyncio.run(service._compat_load_material_stats_async(session))

    assert data == {"totalMaterials": 4, "freeMaterials": 2, "totalDownloads": 17, "userCount": 3}
    assert session.material_queries == 1
    assert session.user_queries == 1


def test_async_legacy_material_stats_reuses_summary_cache() -> None:
    service = _build_service()
    session = _AsyncStatsSession()

    first = asyncio.run(service._compat_load_material_stats_async(session))
    second = asyncio.run(service._compat_load_material_stats_async(session))

    assert first == second
    assert session.material_queries == 1
    assert session.user_queries == 1


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


def test_async_legacy_material_list_keeps_page_stats_and_item_shape(monkeypatch) -> None:
    service = _build_service()
    row = {
        "id": 5,
        "uploader_id": 2,
        "title": "数字信号处理真题",
        "description": "近三年",
        "price": 0,
        "is_free": 1,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "is_general_education": 0,
        "file_key": "materials/dsp.pdf",
        "netdisk_url": None,
        "course_category": "MAJOR",
        "grade_type": "UG",
        "grade_value": "大三",
        "rating_avg": 4.8,
        "rating_count": 12,
        "like_count": 7,
        "view_count": 80,
        "download_count": 21,
        "sales_count": 0,
        "created_at": "2026-01-02T03:04:05Z",
        "uploader_username": "baishan",
        "uploader_nickname": "白山",
        "keywords": "版权方",
    }
    stats = {"totalMaterials": 23, "freeMaterials": 9, "totalDownloads": 120, "userCount": 8}

    async def fake_call(loader, *args, **kwargs):
        del args
        name = loader.__name__
        if name == "_compat_load_user_profile_async":
            return {"school": "电子科技大学", "major": "通信"}
        if name == "_compat_count_material_rows_async":
            return 23
        if name == "_compat_load_material_stats_async":
            return stats
        if name == "_compat_load_available_tags_async":
            return ["DSP", "真题"]
        if name == "_compat_load_material_rows_async":
            assert kwargs["profile"] == {"school": "电子科技大学", "major": "通信"}
            assert kwargs["limit"] == 10
            assert kwargs["offset"] == 10
            return [row]
        if name == "_compat_load_tags_map_async":
            return {5: ["DSP", "真题"]}
        if name == "_compat_load_comment_counts_async":
            return {5: 3}
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(
        service.list_materials_async(
            session=None,
            current_user_id=12,
            keyword="真题",
            school=None,
            college=None,
            major=None,
            tag=None,
            grade_value=None,
            course_category=None,
            price=None,
            sort="latest",
            page=2,
            size=10,
        )
    )

    assert data["meta"] == {"page": 2, "size": 10, "total": 23}
    assert data["stats"] == stats
    assert data["availableTags"] == ["DSP", "真题"]
    assert data["items"][0]["id"] == 5
    assert data["items"][0]["tags"] == ["DSP", "真题"]
    assert data["items"][0]["commentCount"] == 3
    assert data["items"][0]["uploaderNickname"] == "白山"


def test_async_legacy_material_list_skips_profile_lookup_for_anonymous_reads(monkeypatch) -> None:
    service = _build_service()
    row = {
        "id": 6,
        "uploader_id": 2,
        "title": "匿名资料列表",
        "description": "无需画像",
        "price": 0,
        "is_free": 1,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "is_general_education": 0,
        "file_key": None,
        "netdisk_url": None,
        "course_category": "MAJOR",
        "grade_type": "UG",
        "grade_value": "大三",
        "rating_avg": 4.0,
        "rating_count": 1,
        "like_count": 2,
        "view_count": 3,
        "download_count": 4,
        "sales_count": 0,
        "created_at": "2026-01-02T03:04:05Z",
        "uploader_username": "baishan",
        "uploader_nickname": "白山",
        "keywords": None,
    }
    stats = {"totalMaterials": 1, "freeMaterials": 1, "totalDownloads": 4, "userCount": 8}
    call_names: list[str] = []

    async def fake_call(loader, *args, **kwargs):
        del args
        name = loader.__name__
        call_names.append(name)
        if name == "_compat_load_user_profile_async":
            raise AssertionError("anonymous material list should not load a user profile")
        if name == "_compat_count_material_rows_async":
            return 1
        if name == "_compat_load_material_stats_async":
            return stats
        if name == "_compat_load_available_tags_async":
            return ["匿名"]
        if name == "_compat_load_material_rows_async":
            assert kwargs["profile"] is None
            assert kwargs["limit"] == 20
            assert kwargs["offset"] == 0
            return [row]
        if name == "_compat_load_tags_map_async":
            return {6: ["匿名"]}
        if name == "_compat_load_comment_counts_async":
            return {6: 0}
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(
        service.list_materials_async(
            session=None,
            current_user_id=None,
            keyword=None,
            school=None,
            college=None,
            major=None,
            tag=None,
            grade_value=None,
            course_category=None,
            price=None,
            sort="latest",
            page=1,
            size=20,
        )
    )

    assert "_compat_load_user_profile_async" not in call_names
    assert data["meta"] == {"page": 1, "size": 20, "total": 1}
    assert data["stats"] == stats
    assert data["availableTags"] == ["匿名"]
    assert data["items"][0]["id"] == 6
    assert data["items"][0]["tags"] == ["匿名"]


def test_async_legacy_recommendations_skips_profile_lookup_for_anonymous_reads(monkeypatch) -> None:
    service = _build_service()
    row = {
        "id": 7,
        "uploader_id": 2,
        "title": "匿名推荐资料",
        "description": "无需画像",
        "price": 0,
        "is_free": 1,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "is_general_education": 0,
        "file_key": None,
        "netdisk_url": None,
        "course_category": "MAJOR",
        "grade_type": "UG",
        "grade_value": "大三",
        "rating_avg": 4.0,
        "rating_count": 1,
        "like_count": 2,
        "view_count": 3,
        "download_count": 4,
        "sales_count": 0,
        "created_at": "2026-01-02T03:04:05Z",
        "uploader_username": "baishan",
        "uploader_nickname": "白山",
        "keywords": None,
    }

    async def fake_call(loader, *args, **kwargs):
        del args
        name = loader.__name__
        if name == "_compat_load_user_profile_async":
            raise AssertionError("anonymous recommendations should not load a user profile")
        if name == "_compat_load_material_rows_async":
            assert kwargs["profile"] is None
            assert kwargs["limit"] == 6
            assert kwargs["offset"] == 0
            return [row]
        if name == "_compat_load_tags_map_async":
            return {7: ["匿名推荐"]}
        if name == "_compat_load_comment_counts_async":
            return {7: 0}
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.get_recommendations_async(session=None, current_user_id=None, limit=6))

    assert [item["id"] for item in data] == [7]
    assert data[0]["tags"] == ["匿名推荐"]


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
