from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Protocol
from urllib.parse import quote, unquote

import jwt
from fastapi import Request


class TokenCodec(Protocol):
    def encode(self, payload: Mapping[str, Any], ttl_seconds: int) -> str: ...

    def decode(self, token: str) -> Mapping[str, Any]: ...


class JwtTokenCodec:
    """保持与 Java 侧一致的 HS256 + exp/iat/sub/roleMask 语义。"""

    def __init__(self, secret: str, algorithm: str = "HS256") -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("JWT Secret 长度不足 32 字节，请通过 private/.env 覆盖配置。")
        self.secret = secret
        self.algorithm = algorithm

    def encode(self, payload: Mapping[str, Any], ttl_seconds: int) -> str:
        now = datetime.now(UTC)
        exp = now + timedelta(seconds=ttl_seconds)
        token_payload = dict(payload)
        if "sub" in token_payload:
            token_payload["sub"] = str(token_payload["sub"])
        token_payload["iat"] = int(now.timestamp())
        token_payload["exp"] = int(exp.timestamp())
        return jwt.encode(token_payload, self.secret, algorithm=self.algorithm)

    def decode(self, token: str) -> Mapping[str, Any]:
        return jwt.decode(token, self.secret, algorithms=[self.algorithm])


@dataclass(slots=True)
class AuthContext:
    user_id: int | None = None
    role_mask: int | None = None
    source: str | None = None
    token: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


class UserCookieCodec:
    @staticmethod
    def encode(payload: Mapping[str, Any]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return quote(serialized, safe="")

    @staticmethod
    def decode(raw_cookie: str) -> dict[str, Any]:
        decoded = unquote(raw_cookie)
        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            raise ValueError("studyhub_user cookie 必须是 JSON object")
        return payload


def resolve_token_from_request(request: Request, cookie_name: str) -> tuple[str | None, str | None]:
    header = request.headers.get("authorization")
    if header and header.startswith("Bearer "):
        return header[7:].strip(), "bearer"
    cookie_token = request.cookies.get(cookie_name)
    if cookie_token:
        return cookie_token, "cookie"
    return None, None


def build_cookie_header(
    name: str,
    value: str,
    *,
    max_age: int,
    http_only: bool = True,
    path: str = "/",
    same_site: str = "Lax",
    secure: bool = False,
) -> str:
    encoded = quote(value, safe="")
    segments = [f"{name}={encoded}", f"Max-Age={max_age}", f"Path={path}", f"SameSite={same_site}"]
    if secure:
        segments.append("Secure")
    if http_only:
        segments.append("HttpOnly")
    return "; ".join(segments)
