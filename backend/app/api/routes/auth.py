from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_auth_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.core.tasks import BackgroundDispatcher
from app.schemas.auth import (
    BindEmailRequestPayload,
    CompleteRegistrationRequestPayload,
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
@router.get("/api/captchas")
def get_captcha(
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.captcha_service.generate())


@router.post("/api/registration-verifications")
@router.post("/api/auth/register")
def register(
    payload: RegisterRequestPayload,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.send_register_code(session, payload, dispatcher=BackgroundDispatcher(background_tasks)))


@router.post("/api/registrations")
@router.post("/api/auth/verify")
def verify_email(
    payload: CompleteRegistrationRequestPayload,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.complete_registration(session, payload, response))


@router.post("/api/registration-tickets")
def issue_registration_ticket(
    payload: VerifyEmailRequestPayload,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.issue_registration_ticket(payload))


@router.post("/api/session")
@router.post("/api/auth/login")
def login(
    payload: LoginRequestPayload,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.login(session, payload, response))


@router.post("/api/dev-session")
@router.post("/api/auth/dev-login", include_in_schema=False)
def dev_login(
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(service.dev_login(session, response))


@router.post("/api/auth/logout")
def auth_logout(
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    service.auth_cookie_service.clear_auth_cookies(response)
    return api_ok()


@router.post("/api/password-resets")
@router.post("/api/auth/reset-password")
def reset_password(
    payload: ResetPasswordRequestPayload,
    background_tasks: BackgroundTasks,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    if payload.code:
        service.reset_password(session, payload, response)
        return api_ok()
    return api_ok(service.send_reset_password_code(session, payload, dispatcher=BackgroundDispatcher(background_tasks)))


@router.patch("/api/me/password")
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


@router.put("/api/me/email")
@router.post("/api/auth/bind-email")
def bind_email(
    payload: BindEmailRequestPayload,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, object]:
    return api_ok(
        service.bind_email(
            session,
            auth.user_id or 0,
            payload,
            dispatcher=BackgroundDispatcher(background_tasks),
        )
    )
