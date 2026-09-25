from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SnapshotMaterial(_Frozen):
    material_id: int
    title: str
    course: str
    school: str
    summary: str
    tags: tuple[str, ...] = ()
    access_scope: Literal["public", "free", "paid", "owner"]
    owner_id: str | None = None
    price_cents: int = Field(ge=0)
    downloads: int = Field(default=0, ge=0)
    preview_pages: tuple[str, ...]
    unlock_after: tuple[int, ...] = ()


class SnapshotWebPage(_Frozen):
    url: str
    title: str
    text: str


class ReplaySnapshot(_Frozen):
    schema_version: Literal["studyhub.replay.v3"]
    snapshot_id: str
    materials: tuple[SnapshotMaterial, ...]
    policies: dict[str, str]
    web_pages: tuple[SnapshotWebPage, ...] = ()
    memory: dict[str, dict[str, str]] = Field(default_factory=dict)


def load_snapshot(path: Path) -> ReplaySnapshot:
    return ReplaySnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def snapshot_digest(snapshot: ReplaySnapshot) -> str:
    payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
