from __future__ import annotations

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db import session_scope
from app.core.security import JwtTokenCodec
from app.models.auth import AuthUser, EmailVerification
from app.schemas.auth import VerificationPurpose
from app.services.auth_cookie_service import AuthCookieService
from app.services.auth_service import AuthService
from app.services.captcha_service import CaptchaService


def _issue_captcha(client: TestClient, captcha_service: CaptchaService) -> tuple[str, str]:
    response = client.get("/api/auth/captcha")
    assert response.status_code == 200
    payload = response.json()["data"]
    captcha_id = payload["captchaId"]
    captcha_code = captcha_service.peek_code_for_testing(captcha_id)
    assert captcha_code is not None
    return captcha_id, captcha_code


def _register_and_verify(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
    *,
    username: str,
    email: str,
    password: str,
) -> None:
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    register_response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
        },
    )
    assert register_response.status_code == 200
    with session_scope() as session:
        verification_code = auth_service.peek_latest_verification_code_for_testing(
            session,
            email=email,
            purpose=VerificationPurpose.REGISTER,
        )
    assert verification_code is not None
    verify_response = client.post(
        "/api/auth/verify",
        json={
            "email": email,
            "code": verification_code,
            "purpose": "REGISTER",
        },
    )
    assert verify_response.status_code == 200


def test_registration_ticket_is_one_time_and_register_state_is_not_persisted(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
) -> None:
    email = "ticket-once@example.com"
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    send_response = client.post(
        "/api/registration-verifications",
        json={
            "username": "ticket_once",
            "email": email,
            "password": "secret123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
        },
    )
    assert send_response.status_code == 200
    with session_scope() as session:
        code = auth_service.peek_latest_verification_code_for_testing(
            session,
            email=email,
            purpose=VerificationPurpose.REGISTER,
        )
        assert session.query(EmailVerification).filter(EmailVerification.email == email).count() == 0
    assert code is not None

    ticket_response = client.post(
        "/api/registration-tickets",
        json={"email": email, "code": code, "purpose": "REGISTER"},
    )
    assert ticket_response.status_code == 200
    ticket = ticket_response.json()["data"]["registrationTicket"]

    registration = client.post(
        "/api/registrations",
        json={"registrationTicket": ticket, "purpose": "REGISTER"},
    )
    assert registration.status_code == 200
    replay = client.post(
        "/api/registrations",
        json={"registrationTicket": ticket, "purpose": "REGISTER"},
    )
    assert replay.status_code == 409


def test_register_validation_uses_user_facing_username_message(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": "bad name!",
            "email": "bad-name@example.com",
            "password": "secret123",
            "captchaId": "captcha-id",
            "captchaCode": "1234",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["msg"] == "用户名仅支持中文、英文、数字、下划线或短横线"
    assert "String should match pattern" not in payload["msg"]


def test_register_accepts_trimmed_hyphenated_username(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
) -> None:
    _register_and_verify(
        client,
        captcha_service,
        auth_service,
        username="  user-name  ",
        email="hyphen-user@example.com",
        password="secret123",
    )

    session_response = client.get("/api/session")
    assert session_response.status_code == 200
    assert session_response.json()["data"]["user"]["username"] == "user-name"


def test_login_logout_and_session_restore(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
) -> None:
    _register_and_verify(
        client,
        captcha_service,
        auth_service,
        username="compat_user",
        email="compat@example.com",
        password="secret123",
    )

    session_response = client.get("/api/session")
    assert session_response.status_code == 200
    assert session_response.json()["data"]["user"]["username"] == "compat_user"

    client.cookies.clear()
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    login_response = client.post(
        "/api/auth/login",
        json={
            "identifier": "compat@example.com",
            "password": "secret123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
            "rememberMe": True,
        },
    )
    assert login_response.status_code == 200
    set_cookie_headers = login_response.headers.get_list("set-cookie")
    assert any("studyhub_token=" in header and "Max-Age=604800" in header and "SameSite=Lax" in header for header in set_cookie_headers)
    assert any("studyhub_user=" in header and "HttpOnly" in header for header in set_cookie_headers)
    assert all("Secure" not in header for header in set_cookie_headers)

    auth_logout = client.post("/api/auth/logout")
    assert auth_logout.status_code == 200
    auth_cleared_headers = auth_logout.headers.get_list("set-cookie")
    assert any("studyhub_token=" in header and "Max-Age=0" in header for header in auth_cleared_headers)
    assert any("studyhub_user=" in header and "Max-Age=0" in header for header in auth_cleared_headers)
    assert client.get("/api/session").status_code == 401

    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    login_again_response = client.post(
        "/api/auth/login",
        json={
            "identifier": "compat@example.com",
            "password": "secret123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
            "rememberMe": True,
        },
    )
    assert login_again_response.status_code == 200
    session_logout = client.post("/api/logout")
    assert session_logout.status_code == 200
    cleared_headers = session_logout.headers.get_list("set-cookie")
    assert any("studyhub_token=" in header and "Max-Age=0" in header for header in cleared_headers)
    assert any("studyhub_user=" in header and "Max-Age=0" in header for header in cleared_headers)
    assert client.get("/api/session").status_code == 401


def test_auth_response_hides_token_by_default_in_production() -> None:
    settings = Settings(
        environment="production",
        jwt_secret="studyhub-fastapi-test-secret-1234567890abcdefghijkl",
    )
    service = AuthCookieService(settings, JwtTokenCodec(settings.jwt_secret, settings.jwt_algorithm))
    response = Response()
    user = AuthUser(
        id=1,
        username="alice",
        email="alice@example.com",
        password_hash="hash",
        nickname="Alice",
        role_mask=1,
        verified=True,
        free_download_quota=7,
    )

    payload = service.write_auth_cookies_for_user(response, user, remember_me=False)

    assert payload == {"user": service.build_user_payload(user)}
    assert "token" not in payload
    set_cookie_headers = response.headers.getlist("set-cookie")
    assert any("studyhub_token=" in header and "HttpOnly" in header for header in set_cookie_headers)


def test_auth_response_can_include_token_for_compatibility() -> None:
    settings = Settings(
        environment="production",
        auth_response_include_token=True,
        jwt_secret="studyhub-fastapi-test-secret-1234567890abcdefghijkl",
    )
    service = AuthCookieService(settings, JwtTokenCodec(settings.jwt_secret, settings.jwt_algorithm))
    response = Response()
    user = AuthUser(
        id=1,
        username="alice",
        email="alice@example.com",
        password_hash="hash",
        nickname="Alice",
        role_mask=1,
        verified=True,
        free_download_quota=7,
    )

    payload = service.write_auth_cookies_for_user(response, user, remember_me=False)

    assert isinstance(payload.get("token"), str)
    assert payload["user"]["username"] == "alice"


def test_login_preserves_username_case_for_identifier_lookup(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
) -> None:
    _register_and_verify(
        client,
        captcha_service,
        auth_service,
        username="CaseUser",
        email="case-user@example.com",
        password="secret123",
    )

    client.cookies.clear()
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    login_response = client.post(
        "/api/auth/login",
        json={
            "identifier": "CaseUser",
            "password": "secret123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
        },
    )

    assert login_response.status_code == 200


def test_me_account_patch_refreshes_cookies(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
) -> None:
    _register_and_verify(
        client,
        captcha_service,
        auth_service,
        username="refresh_user",
        email="refresh@example.com",
        password="secret123",
    )

    client.cookies.clear()
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    login_response = client.post(
        "/api/auth/login",
        json={
            "identifier": "refresh_user",
            "password": "secret123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
            "rememberMe": True,
        },
    )
    assert login_response.status_code == 200

    patch_response = client.patch(
        "/api/me/account",
        json={
            "nickname": "刷新后的昵称",
            "emailPrivacy": True,
            "signature": "hello markdown",
            "gradeStages": ["大一", "大二", "大二"],
        },
    )
    assert patch_response.status_code == 200
    patch_data = patch_response.json()["data"]
    assert patch_data["nickname"] == "刷新后的昵称"
    assert patch_data["emailPrivacy"] is True
    assert patch_data["gradeStages"] == ["大一", "大二"]

    refreshed_headers = patch_response.headers.get_list("set-cookie")
    assert any("studyhub_token=" in header and "Max-Age=604800" in header for header in refreshed_headers)
    assert any("studyhub_user=" in header and "%E5%88%B7%E6%96%B0%E5%90%8E%E7%9A%84%E6%98%B5%E7%A7%B0" in header for header in refreshed_headers)
    assert all("Secure" not in header for header in refreshed_headers)

    session_response = client.get("/api/session")
    assert session_response.status_code == 200
    assert session_response.json()["data"]["user"]["nickname"] == "刷新后的昵称"
    assert session_response.json()["data"]["user"]["emailPrivacy"] is True


def test_bind_email_and_reset_password_flow(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
) -> None:
    with session_scope() as session:
        user = auth_service.create_local_user(
            session,
            username="bind_user",
            password="origin123",
        )
        user_id = user.id
    client.cookies.clear()
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    login_response = client.post(
        "/api/auth/login",
        json={
            "identifier": "bind_user",
            "password": "origin123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
        },
    )
    assert login_response.status_code == 200

    send_bind = client.post("/api/auth/bind-email", json={"email": "bind@example.com"})
    assert send_bind.status_code == 200
    with session_scope() as session:
        bind_code = auth_service.peek_latest_verification_code_for_testing(
            session,
            email="bind@example.com",
            purpose=VerificationPurpose.BIND,
            user_id=user_id,
        )
    assert bind_code is not None

    confirm_bind = client.post(
        "/api/auth/bind-email",
        json={"email": "bind@example.com", "code": bind_code},
    )
    assert confirm_bind.status_code == 200
    assert confirm_bind.json()["data"] == {"email": "bind@example.com", "verified": True}

    reset_captcha_id, reset_captcha_code = _issue_captcha(client, captcha_service)
    send_reset = client.post(
        "/api/auth/reset-password",
        json={
            "identifier": "bind_user",
            "newPassword": "renew123",
            "captchaId": reset_captcha_id,
            "captchaCode": reset_captcha_code,
        },
    )
    assert send_reset.status_code == 200
    with session_scope() as session:
        reset_code = auth_service.peek_latest_verification_code_for_testing(
            session,
            email="bind@example.com",
            purpose=VerificationPurpose.RESET,
            user_id=user_id,
        )
    assert reset_code is not None

    confirm_reset = client.post(
        "/api/auth/reset-password",
        json={
            "identifier": "bind_user",
            "newPassword": "renew123",
            "code": reset_code,
        },
    )
    assert confirm_reset.status_code == 200
    assert any("studyhub_token=" in header and "Max-Age=0" in header for header in confirm_reset.headers.get_list("set-cookie"))

    client.cookies.clear()
    relogin_captcha_id, relogin_captcha_code = _issue_captcha(client, captcha_service)
    relogin = client.post(
        "/api/auth/login",
        json={
            "identifier": "bind_user",
            "password": "renew123",
            "captchaId": relogin_captcha_id,
            "captchaCode": relogin_captcha_code,
        },
    )
    assert relogin.status_code == 200


def test_password_reset_can_hide_unknown_account_in_production_mode(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_service.settings, "password_reset_hide_unknown_account", True)
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)

    response = client.post(
        "/api/password-resets",
        json={
            "identifier": "missing_user",
            "newPassword": "renew123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["email"] == "no-reply@study-hub.cn"
    assert payload["expiresInSeconds"] == auth_service.settings.verification_ttl_seconds
    with session_scope() as session:
        reset_code = auth_service.peek_latest_verification_code_for_testing(
            session,
            email="no-reply@study-hub.cn",
            purpose=VerificationPurpose.RESET,
        )
    assert reset_code is None


def test_change_password_clears_cookies(
    client: TestClient,
    captcha_service: CaptchaService,
    auth_service: AuthService,
) -> None:
    _register_and_verify(
        client,
        captcha_service,
        auth_service,
        username="password_user",
        email="password@example.com",
        password="before123",
    )

    change_response = client.post(
        "/api/auth/password",
        json={
            "oldPassword": "before123",
            "newPassword": "after123",
        },
    )
    assert change_response.status_code == 200
    assert any("studyhub_token=" in header and "Max-Age=0" in header for header in change_response.headers.get_list("set-cookie"))

    client.cookies.clear()
    captcha_id, captcha_code = _issue_captcha(client, captcha_service)
    relogin = client.post(
        "/api/auth/login",
        json={
            "identifier": "password_user",
            "password": "after123",
            "captchaId": captcha_id,
            "captchaCode": captcha_code,
        },
    )
    assert relogin.status_code == 200
