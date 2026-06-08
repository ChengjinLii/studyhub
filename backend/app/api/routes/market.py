from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    get_market_asset_store,
    get_public_read_cache,
    get_market_service,
    get_optional_auth_context,
    require_auth_context,
    require_privileged_auth_context,
)
from app.core.db import get_db_session
from app.core.public_read_cache import PublicReadCache, cache_if_anonymous_async, invalidate_prefixes
from app.core.response import api_ok
from app.core.security import AuthContext
from app.integrations.market_asset_store import MarketAssetStore
from app.schemas.market import (
    AdminMarketBatchDeletePayload,
    AdminMarketBatchUpdatePayload,
    MarketStatusPayload,
    MarketCreatePayload,
    parse_payload_json,
)
from app.services.market_service import MarketService


router = APIRouter(tags=["market"])


def _call_service_method(service, async_name: str, sync_name: str, *args, **kwargs):
    method = getattr(service, async_name, None)
    if method is not None:
        return method(*args, **kwargs)
    return getattr(service, sync_name)(*args, **kwargs)


@router.get("/api/market")
async def list_market(
    keyword: str | None = None,
    category: str | None = None,
    page: int = 1,
    size: int = 20,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = await cache_if_anonymous_async(
        cache,
        current_user_id=current_user_id,
        namespace="market:list",
        key=(keyword, category, page, size),
        factory=lambda: _call_service_method(
            service,
            "list_market_async",
            "list_market",
            session,
            current_user_id,
            keyword=keyword,
            category=category,
            page=page,
            size=size,
        ),
    )
    return api_ok(data)


@router.get("/api/market/wanted")
def market_wanted(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.get_wanted_ids(session, auth.user_id))


@router.get("/api/market/{id}")
async def market_detail(
    id: int,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = await cache_if_anonymous_async(
        cache,
        current_user_id=current_user_id,
        namespace="market:detail",
        key=(id,),
        factory=lambda: _call_service_method(
            service,
            "get_detail_async",
            "get_detail",
            session,
            current_user_id,
            id,
        ),
    )
    return api_ok(data)


@router.get("/api/market/{id}/images/{index}")
def market_image(
    id: int,
    index: int,
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
    asset_store: MarketAssetStore = Depends(get_market_asset_store),
) -> FileResponse:
    _, key = service.resolve_public_image(session, id, index)
    if key.startswith("http://") or key.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    path = asset_store.resolve_path(key)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    return FileResponse(path, media_type=asset_store.guess_media_type(key, default="image/jpeg"))


@router.post("/api/market")
async def create_market_item(
    request: Request,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    form = await request.form()
    payload = parse_payload_json(form.get("payload"), MarketCreatePayload)
    images = _coerce_upload_list(form.getlist("images"))
    data = service.create_item(session, payload, images, auth.user_id or 0)
    _invalidate_market_read_caches()
    return api_ok(data)


@router.put("/api/market/{id}/want")
@router.post("/api/market/{id}/want", include_in_schema=False)
def want_market_item(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    data = service.want_item(session, id, auth.user_id or 0)
    _invalidate_market_engagement_caches()
    return api_ok(data)


@router.delete("/api/market/{id}/want")
def cancel_want_market_item(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    data = service.cancel_want_item(session, id, auth.user_id or 0)
    _invalidate_market_engagement_caches()
    return api_ok(data)


@router.patch("/api/market/{id}/status")
def update_market_item_status(
    id: int,
    payload: MarketStatusPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    data = service.update_status(session, id, auth.user_id or 0, payload)
    _invalidate_market_read_caches()
    return api_ok(data)


@router.delete("/api/market/{id}")
def delete_market_item(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    service.delete_item(session, id, auth.user_id or 0)
    _invalidate_market_read_caches()
    return api_ok()


@router.get("/api/admin/market")
def list_market_for_admin(
    page: int = 1,
    size: int = 15,
    keyword: str | None = None,
    category: str | None = None,
    status: str | None = None,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.list_for_admin(session, page=page, size=size, keyword=keyword, category=category, status_value=status))


@router.patch("/api/admin/market")
@router.post("/api/admin/market/batch-update", include_in_schema=False)
def batch_update_market_for_admin(
    payload: AdminMarketBatchUpdatePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    data = service.batch_update(session, payload)
    _invalidate_market_read_caches()
    return api_ok(data)


@router.delete("/api/admin/market")
@router.post("/api/admin/market/batch-delete", include_in_schema=False)
def batch_delete_market_for_admin(
    payload: AdminMarketBatchDeletePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    data = service.batch_delete(session, payload)
    _invalidate_market_read_caches()
    return api_ok(data)


@router.delete("/api/admin/market/{id}")
def delete_market_item_for_admin(
    id: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    service.remove_by_admin(session, id)
    _invalidate_market_read_caches()
    return api_ok()


def _coerce_upload_list(values: list[object]) -> list[UploadFile]:
    return [item for item in values if isinstance(item, UploadFile) or hasattr(item, "filename")]


def _invalidate_market_read_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "market")


def _invalidate_market_engagement_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "market:detail")
