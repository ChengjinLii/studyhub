from __future__ import annotations

from pydantic import BaseModel


class LocalDevPayload(BaseModel):
    enabled: bool
    quickLoginEnabled: bool
    developerUsername: str | None = None
    providers: dict[str, str] | None = None


class HealthPayload(BaseModel):
    status: str
    service: str
    environment: str
    localDev: LocalDevPayload | None = None
    database: str
    providers: dict[str, str] | None = None
    build: dict[str, str] | None = None


class ReadyPayload(BaseModel):
    status: str
    service: str
    environment: str
    deep: bool
    checks: dict[str, dict[str, object]]
    build: dict[str, str] | None = None
