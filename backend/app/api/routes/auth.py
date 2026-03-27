from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_auth_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.auth import (
    BindEmailRequestPayload,
    LoginRequestPayload,
    PasswordChangeRequestPayload,
    RegisterRequestPayload,
    ResetPasswordRequestPayload,
    VerifyEmailRequestPayload,
)
from app.services.auth_service import AuthService


router = APIRouter(tags=["auth"])


@router.get("/api/auth/captcha")
@router.get("/api/captcha")
def get_captcha(
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.captcha_service.generate())


@router.post("/api/auth/register")
def register(
    payload: RegisterRequestPayload,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.send_register_code(session, payload))


@router.post("/api/auth/verify")
def verify_email(
    payload: VerifyEmailRequestPayload,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.complete_registration(session, payload, response))


@router.post("/api/auth/login")
def login(
    payload: LoginRequestPayload,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.login(session, payload, response))


@router.post("/api/auth/dev-login")
def dev_login(
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.dev_login(session, response))


@router.post("/api/auth/logout")
def auth_logout() -> dict[str, object]:
    return api_ok()


@router.post("/api/auth/reset-password")
def reset_password(
    payload: ResetPasswordRequestPayload,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    if payload.code:
        service.reset_password(session, payload, response)
        return api_ok()
    return api_ok(service.send_reset_password_code(session, payload))


@router.post("/api/auth/password")
def change_password(
    payload: PasswordChangeRequestPayload,
    response: Response,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    service.change_password(session, auth.user_id or 0, payload.oldPassword, payload.newPassword, response)
    return api_ok()


@router.post("/api/auth/bind-email")
def bind_email(
    payload: BindEmailRequestPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.bind_email(session, auth.user_id or 0, payload))
