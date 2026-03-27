from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class ApiResponseEnvelope(BaseModel):
    ok: bool
    data: Any | None = None
    error: ErrorBody | None = None
    msg: str | None = None
