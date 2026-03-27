from __future__ import annotations

from fastapi import HTTPException, Response, status

from app.core.config import Settings
from app.core.security import UserCookieCodec
from app.services.auth_cookie_service import AuthCookieService


class SessionService:
    def __init__(self, settings: Settings, auth_cookie_service: AuthCookieService) -> None:
        self.settings = settings
        self.auth_cookie_service = auth_cookie_service

    def read_session(self, raw_user_cookie: str | None) -> dict[str, object]:
        if not raw_user_cookie:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
        try:
            user_payload = UserCookieCodec.decode(raw_user_cookie)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="会话已失效") from exc
        return {"user": user_payload}

    def clear_auth_cookies(self, response: Response) -> None:
        self.auth_cookie_service.clear_auth_cookies(response)
