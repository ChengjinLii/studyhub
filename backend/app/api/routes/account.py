from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_account_service, get_auth_cookie_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.account import AccountUpdateRequestPayload
from app.services.account_service import AccountService
from app.services.auth_cookie_service import AuthCookieService


router = APIRouter(tags=["account"])


@router.get("/api/me/account")
def get_account(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AccountService = Depends(get_account_service),
) -> dict[str, object]:
    return api_ok(service.get_account(session, auth.user_id or 0))


@router.patch("/api/me/account")
def patch_account(
    payload: AccountUpdateRequestPayload,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AccountService = Depends(get_account_service),
    auth_cookie_service: AuthCookieService = Depends(get_auth_cookie_service),
) -> dict[str, object]:
    updated_user = service.update_account(session, auth.user_id or 0, payload)
    remember_me = auth_cookie_service.resolve_remember_flag(request)
    auth_cookie_service.write_auth_cookies_for_user(response, updated_user, remember_me)
    return api_ok(service.to_payload(updated_user))
