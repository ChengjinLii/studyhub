from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import quote
import zipfile

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    get_leaderboard_read_service,
    get_materials_column_service,
    get_public_read_cache,
    get_materials_service,
    get_optional_auth_context,
    get_requests_service,
    require_auth_context,
)
from app.core.db import get_db_session
from app.core.public_read_cache import PublicReadCache, cache_if_anonymous_async, invalidate_prefixes
from app.core.rate_limit import client_key_for_request
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.materials import (
    BatchDownloadPayload,
    MaterialCreatePayload,
    MaterialUpdatePayload,
    MaterialViewPayload,
    RatingPayload,
    ReviewPayload,
    parse_payload_json,
)
from app.services.materials_column_service import MaterialsColumnService
from app.services.materials_service import MaterialsService
from app.services.requests_service import RequestsService


router = APIRouter(tags=["materials"])


def _call_service_method(service, async_name: str, sync_name: str, *args, **kwargs):
    method = getattr(service, async_name, None)
    if method is not None:
        return method(*args, **kwargs)
    return getattr(service, sync_name)(*args, **kwargs)


@router.get("/api/materials")
async def list_materials(
    keyword: str | None = None,
    school: str | None = None,
    college: str | None = None,
    major: str | None = None,
    tag: str | None = None,
    gradeValue: str | None = None,
    courseCategory: str | None = None,
    price: str | None = None,
    sort: str = "latest",
    page: int = 1,
    size: int = 20,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = await cache_if_anonymous_async(
        cache,
        current_user_id=current_user_id,
        namespace="materials:list",
        key=(keyword, school, college, major, tag, gradeValue, courseCategory, price, sort, page, size),
        factory=lambda: _call_service_method(
            service,
            "list_materials_async",
            "list_materials",
            session,
            current_user_id,
            keyword=keyword,
            school=school,
            college=college,
            major=major,
            tag=tag,
            grade_value=gradeValue,
            course_category=courseCategory,
            price=price,
            sort=sort,
            page=page,
            size=size,
        ),
    )
    return api_ok(data)


@router.get("/api/materials/column")
def materials_column(
    request: Request,
    topic: str | None = None,
    page: int = 1,
    size: int | None = None,
    service: MaterialsColumnService = Depends(get_materials_column_service),
) -> Response:
    payload, etag, cache_control = service.get_column(topic=topic, page=page, size=size)
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=api_ok(payload), headers=headers)


@router.get("/api/materials/recommendations")
async def material_recommendations(
    limit: int | None = None,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = await cache_if_anonymous_async(
        cache,
        current_user_id=current_user_id,
        namespace="materials:recommendations",
        key=(limit,),
        factory=lambda: _call_service_method(
            service,
            "get_recommendations_async",
            "get_recommendations",
            session,
            current_user_id,
            limit,
        ),
    )
    return api_ok(data)


@router.get("/api/materials/{id}")
async def material_detail(
    id: int,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    can_manage_all = bool(auth and auth.role_mask and auth.role_mask & 24)
    data = await cache_if_anonymous_async(
        cache,
        current_user_id=current_user_id,
        namespace="materials:detail",
        key=(id,),
        factory=lambda: _call_service_method(
            service,
            "get_detail_async",
            "get_detail",
            session,
            current_user_id,
            id,
            can_manage_all,
        ),
    )
    return api_ok(data)


@router.post("/api/materials/{id}/views")
@router.post("/api/materials/{id}/view")
async def record_view(
    id: int,
    request: Request,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    payload_dict = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    payload = MaterialViewPayload.model_validate(payload_dict or {})
    viewer_context = {
        "client": client_key_for_request(service.settings, request),
        "userAgent": request.headers.get("user-agent", ""),
    }
    view_count = service.record_view(
        session,
        id,
        auth.user_id if auth else None,
        bool(auth and auth.role_mask and auth.role_mask & 24),
        payload.viewerToken,
        viewer_context=viewer_context,
    )
    _invalidate_material_detail_caches()
    return api_ok({"viewCount": view_count})


@router.get("/api/materials/{id}/preview")
def preview(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    return api_ok(service.get_preview(session, id, auth.user_id or 0, bool(auth.role_mask and auth.role_mask & 24)))


@router.post("/api/materials")
async def create_material(
    request: Request,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
    requests_service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    form = await request.form()
    payload = parse_payload_json(form.get("payload"), MaterialCreatePayload)
    zip_file = form.get("zip")
    markdown_file = form.get("markdown")
    previews = _coerce_upload_list(form.getlist("previews"))
    custom_previews = _coerce_upload_list(form.getlist("customPreviews"))
    def create_and_attach() -> dict[str, object]:
        detail = service.create_material(
            session,
            payload=payload,
            uploader_id=auth.user_id or 0,
            zip_file=zip_file if hasattr(zip_file, "filename") else None,
            markdown_file=markdown_file if hasattr(markdown_file, "filename") else None,
            previews=previews,
            custom_previews=custom_previews,
        )
        if payload.requestId is not None:
            requests_service.attach_material_to_request(
                session,
                payload.requestId,
                auth.user_id or 0,
                int(detail["id"]),
            )
        return detail

    detail = await run_in_threadpool(create_and_attach)
    _invalidate_material_read_caches()
    return api_ok(detail)


@router.put("/api/materials/{id}")
async def update_material(
    id: int,
    request: Request,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    form = await request.form()
    payload = parse_payload_json(form.get("payload"), MaterialUpdatePayload)
    zip_file = form.get("zip")
    markdown_file = form.get("markdown")
    previews = _coerce_upload_list(form.getlist("previews"))
    custom_previews = _coerce_upload_list(form.getlist("customPreviews"))
    detail = await run_in_threadpool(
        service.update_material,
        session,
        material_id=id,
        payload=payload,
        operator_id=auth.user_id or 0,
        can_manage_all=bool(auth.role_mask and auth.role_mask & 24),
        zip_file=zip_file if hasattr(zip_file, "filename") else None,
        markdown_file=markdown_file if hasattr(markdown_file, "filename") else None,
        previews=previews,
        custom_previews=custom_previews,
    )
    _invalidate_material_read_caches()
    return api_ok(detail)


@router.delete("/api/materials/{id}")
def delete_material(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.delete_material(session, id, operator_id=auth.user_id or 0, can_manage_all=bool(auth.role_mask and auth.role_mask & 24))
    _invalidate_material_read_caches()
    return api_ok()


@router.put("/api/materials/{id}/rating")
def rate_material(
    id: int,
    payload: RatingPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.rate_material(session, id, auth.user_id or 0, payload.rating)
    _invalidate_material_read_caches()
    return api_ok(data)


@router.post("/api/materials/{id}/reviews")
@router.post("/api/materials/{id}/review")
def review_material(
    id: int,
    payload: ReviewPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.add_review(session, id, auth.user_id or 0, payload)
    _invalidate_material_read_caches()
    return api_ok()


@router.put("/api/materials/{id}/favorite")
@router.post("/api/materials/{id}/favorite")
def favorite_material(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.add_favorite(session, id, auth.user_id or 0)
    return api_ok()


@router.delete("/api/materials/{id}/favorite")
def unfavorite_material(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.remove_favorite(session, id, auth.user_id or 0)
    return api_ok()


@router.put("/api/materials/{id}/like")
@router.post("/api/materials/{id}/like")
def like_material(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.like(session, id, auth.user_id or 0)
    _invalidate_material_read_caches()
    return api_ok(data)


@router.delete("/api/materials/{id}/like")
def unlike_material(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.unlike(session, id, auth.user_id or 0)
    _invalidate_material_read_caches()
    return api_ok(data)


@router.post("/api/materials/{id}/downloads")
@router.get("/api/materials/{id}/download")
def download_material(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.generate_download(session, id, user_id=auth.user_id or 0, role_mask=auth.role_mask)
    _invalidate_material_download_caches()
    return api_ok(data)


@router.post("/api/material-downloads")
@router.post("/api/materials/downloads/batch")
def batch_download(
    payload: BatchDownloadPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.generate_batch_downloads(session, payload.materialIds, user_id=auth.user_id or 0, role_mask=auth.role_mask)
    _invalidate_material_download_caches()
    return api_ok(data)


@router.get("/api/materials/{id}/download/file")
def material_download_asset(
    id: int,
    token: str = Query(...),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> Response:
    material, path, filename = service.resolve_download_asset(session, id, token)
    if path is not None and path.exists():
        return FileResponse(
            path,
            media_type=service.asset_store.guess_media_type(path.name),
            headers=_build_download_headers(filename),
        )
    return _placeholder_download_response(material.file_type or "zip", filename)


@router.get("/api/materials/{id}/preview/images/{index}")
def material_preview_asset(
    id: int,
    index: int,
    token: str = Query(...),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> Response:
    material, claims = service.resolve_preview_asset(session, id, index, token)
    if claims.get("kind") == "preview-image" and claims.get("key"):
        key = str(claims["key"])
        try:
            content = service.asset_store.read_bytes(key, max_size_bytes=service.settings.material_preview_image_max_size_bytes)
            return Response(
                content=content,
                media_type=service.asset_store.guess_media_type(key, default="image/png"),
                headers={"Cache-Control": "private, max-age=300"},
            )
        except Exception:
            pass
    svg = _build_preview_placeholder_svg(material.title, index, material.preview_watermark_enabled)
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/api/materials/{id}/assets/custom/{index}")
def material_custom_preview_asset(
    id: int,
    index: int,
    token: str = Query(...),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> Response:
    path = service.resolve_public_custom_preview_path(session, id, index, token)
    return FileResponse(path, media_type=service.asset_store.guess_media_type(path.name, default="image/png"))


def _coerce_upload_list(values: list[object]) -> list[UploadFile]:
    return [value for value in values if hasattr(value, "filename")]


def _invalidate_material_read_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "materials", "leaderboard")
    _invalidate_contributor_leaderboard_cache()


def _invalidate_material_detail_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "materials:detail")


def _invalidate_material_download_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "materials:detail", "leaderboard")
    _invalidate_contributor_leaderboard_cache()


def _invalidate_contributor_leaderboard_cache() -> None:
    service = get_leaderboard_read_service()
    invalidate = getattr(service, "invalidate_contributor_cache", None)
    if callable(invalidate):
        invalidate()


def _placeholder_download_response(file_type: str, filename: str) -> Response:
    normalized_type = (file_type or "").lower()
    if normalized_type == "pdf":
        content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R>>endobj\n4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 36 96 Td (StudyHub Placeholder PDF) Tj ET\nendstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
        headers = _build_download_headers(filename)
        return Response(content=content, media_type="application/pdf", headers=headers)
    if normalized_type == "zip":
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", "StudyHub placeholder archive")
        headers = _build_download_headers(filename)
        return Response(content=buffer.getvalue(), media_type="application/zip", headers=headers)
    headers = _build_download_headers(filename)
    return Response(content=b"StudyHub placeholder file", media_type="application/octet-stream", headers=headers)


def _build_download_headers(filename: str) -> dict[str, str]:
    ascii_fallback = "".join(char if ord(char) < 128 else "_" for char in (filename or "download.bin")) or "download.bin"
    encoded = quote(filename or "download.bin")
    return {"Content-Disposition": f"attachment; filename={ascii_fallback}; filename*=UTF-8''{encoded}"}


def _build_preview_placeholder_svg(title: str, index: int, watermark_enabled: bool) -> str:
    watermark = "StudyHub Preview" if watermark_enabled else "Preview"
    escaped_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1448" viewBox="0 0 1024 1448">
  <rect width="1024" height="1448" fill="#f6f7fb"/>
  <rect x="72" y="72" width="880" height="1304" rx="36" fill="#ffffff" stroke="#d7dce7"/>
  <text x="128" y="180" font-size="34" font-family="Arial, sans-serif" fill="#111827">{escaped_title}</text>
  <text x="128" y="250" font-size="24" font-family="Arial, sans-serif" fill="#4b5563">第 {index} 页预览</text>
  <text x="512" y="760" text-anchor="middle" font-size="54" font-family="Arial, sans-serif" fill="#d1d5db" transform="rotate(-24 512 760)">{watermark}</text>
  <text x="128" y="1320" font-size="22" font-family="Arial, sans-serif" fill="#6b7280">当前为本地 Step 8 预览占位图</text>
</svg>"""
