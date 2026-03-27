from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SessionPayload(BaseModel):
    user: dict[str, Any]
