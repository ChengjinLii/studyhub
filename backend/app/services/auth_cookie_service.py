from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from fastapi import Request, Response

from app.core.config import Settings
from app.core.profile_metadata import resolve_free_download_quota
from app.core.security import JwtTokenCodec, build_cookie_header
from app.models.auth import AuthUser


ADMIN_BIT = 8
DEVELOPER_BIT = 16


class AuthCookieService:
    def __init__(self, settings: Settings, token_codec: JwtTokenCodec) -> None:
        self.settings = settings
        self.token_codec = token_codec

    def build_user_payload(self, user: AuthUser) -> dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "verified": bool(user.verified),
            "nickname": user.nickname,
            "roleMask": user.role_mask,
            "freeDownloadQuota": self._resolve_free_download_quota(user),
            "emailPrivacy": user.email_privacy,
        }

    def build_auth_response(self, user: AuthUser, remember_me: bool) -> dict[str, Any]:
        ttl_seconds = self._resolve_ttl_seconds(remember_me)
        token = self.token_codec.encode(
            {
                "sub": str(user.id),
                "roleMask": user.role_mask,
                "nickname": user.nickname,
                "remember": remember_me,
            },
            ttl_seconds=ttl_seconds,
        )
        return {
            "token": token,
            "user": self.build_user_payload(user),
        }

    def write_auth_cookies(self, response: Response, payload: Mapping[str, Any], remember_me: bool) -> None:
        token = payload.get("token")
        user_payload = payload.get("user")
        if not isinstance(token, str) or not isinstance(user_payload, Mapping):
            return

        ttl_seconds = self._resolve_ttl_seconds(remember_me)
        response.headers.append(
            "set-cookie",
            build_cookie_header(
                self.settings.cookie_token_name,
                token,
                max_age=ttl_seconds,
                path=self.settings.cookie_path,
                same_site=self.settings.cookie_same_site,
            ),
        )
        response.headers.append(
            "set-cookie",
            build_cookie_header(
                self.settings.cookie_user_name,
                self._serialize_user_cookie(user_payload),
                max_age=ttl_seconds,
                path=self.settings.cookie_path,
                same_site=self.settings.cookie_same_site,
            ),
        )

    def write_auth_cookies_for_user(self, response: Response, user: AuthUser, remember_me: bool) -> dict[str, Any]:
        payload = self.build_auth_response(user, remember_me)
        self.write_auth_cookies(response, payload, remember_me)
        return payload

    def clear_auth_cookies(self, response: Response) -> None:
        response.headers.append(
            "set-cookie",
            build_cookie_header(
                self.settings.cookie_token_name,
                "",
                max_age=0,
                path=self.settings.cookie_path,
                same_site=self.settings.cookie_same_site,
            ),
        )
        response.headers.append(
            "set-cookie",
            build_cookie_header(
                self.settings.cookie_user_name,
                "",
                max_age=0,
                path=self.settings.cookie_path,
                same_site=self.settings.cookie_same_site,
            ),
        )

    def resolve_remember_flag(self, request: Request) -> bool:
        raw_token = request.cookies.get(self.settings.cookie_token_name)
        if not raw_token:
            return False
        try:
            claims = self.token_codec.decode(raw_token)
        except Exception:  # noqa: BLE001
            return False
        return bool(claims.get("remember"))

    def _resolve_ttl_seconds(self, remember_me: bool) -> int:
        if remember_me:
            return self.settings.remember_cookie_ttl_seconds
        return self.settings.auth_cookie_ttl_seconds

    def _resolve_free_download_quota(self, user: AuthUser) -> int | None:
        role_mask = user.role_mask or 0
        if (role_mask & ADMIN_BIT) == ADMIN_BIT or (role_mask & DEVELOPER_BIT) == DEVELOPER_BIT:
            return None
        return resolve_free_download_quota(user.free_download_quota)

    def _serialize_user_cookie(self, payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
