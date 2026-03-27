from __future__ import annotations

from typing import Any


def api_ok(data: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True}
    if data is not None:
        payload["data"] = data
    return payload


def api_fail(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
        "msg": message,
    }
