from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    get_market_asset_store,
    get_legacy_market_read_service,
    get_market_service,
    get_optional_auth_context,
    require_auth_context,
    require_privileged_auth_context,
)
from app.core.config import get_settings
from app.core.db import get_db_session
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
from app.services.legacy_market_read_service import LegacyMarketReadService
from app.services.market_service import MarketService


router = APIRouter(tags=["market"])


@router.get("/api/market")
def list_market(
    keyword: str | None = None,
    category: str | None = None,
    page: int = 1,
    size: int = 20,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    legacy_service: LegacyMarketReadService = Depends(get_legacy_market_read_service),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    settings = get_settings()
    if settings.requires_private_env_file:
        return api_ok(
            legacy_service.list_market(
                session,
                auth.user_id if auth else None,
                keyword=keyword,
                category=category,
                page=page,
                size=size,
            )
        )
    return api_ok(
        service.list_market(session, auth.user_id if auth else None, keyword=keyword, category=category, page=page, size=size)
    )


@router.get("/api/market/wanted")
def market_wanted(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.get_wanted_ids(session, auth.user_id))


@router.get("/api/market/{id}")
def market_detail(
    id: int,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    legacy_service: LegacyMarketReadService = Depends(get_legacy_market_read_service),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    settings = get_settings()
    if settings.requires_private_env_file:
        return api_ok(legacy_service.get_detail(session, auth.user_id if auth else None, id))
    return api_ok(service.get_detail(session, auth.user_id if auth else None, id))


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
    return api_ok(service.create_item(session, payload, images, auth.user_id or 0))


@router.post("/api/market/{id}/want")
def want_market_item(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.want_item(session, id, auth.user_id or 0))


@router.delete("/api/market/{id}/want")
def cancel_want_market_item(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.cancel_want_item(session, id, auth.user_id or 0))


@router.patch("/api/market/{id}/status")
def update_market_item_status(
    id: int,
    payload: MarketStatusPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.update_status(session, id, auth.user_id or 0, payload))


@router.delete("/api/market/{id}")
def delete_market_item(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    service.delete_item(session, id, auth.user_id or 0)
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


@router.post("/api/admin/market/batch-update")
def batch_update_market_for_admin(
    payload: AdminMarketBatchUpdatePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.batch_update(session, payload))


@router.post("/api/admin/market/batch-delete")
def batch_delete_market_for_admin(
    payload: AdminMarketBatchDeletePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    return api_ok(service.batch_delete(session, payload))


@router.delete("/api/admin/market/{id}")
def delete_market_item_for_admin(
    id: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MarketService = Depends(get_market_service),
) -> dict[str, object]:
    service.remove_by_admin(session, id)
    return api_ok()


def _coerce_upload_list(values: list[object]) -> list[UploadFile]:
    return [item for item in values if isinstance(item, UploadFile) or hasattr(item, "filename")]
