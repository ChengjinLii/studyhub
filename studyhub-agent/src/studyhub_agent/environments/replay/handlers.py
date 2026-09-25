from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from studyhub_agent.contracts.episode import Principal
from studyhub_agent.environments.replay.index import Bm25Index
from studyhub_agent.environments.replay.snapshot import ReplaySnapshot, SnapshotMaterial
from studyhub_agent.guardrails.permissions import can_read
from studyhub_agent.guardrails.privacy import FORBIDDEN_KEYS, sanitize_output
from studyhub_agent.guardrails.web_security import UnsafeUrlError, WebSecurityPolicy

SNAPSHOT_HOST_ADDRESS = "93.184.216.34"
_WEB_POLICY = WebSecurityPolicy()
# Matches the memory_update tool's own description ("记忆键，小写英文和下划线" / lowercase English
# and underscore). ASCII-only on purpose: str.isalnum() is Unicode-aware and treats Han/other
# non-ASCII "alphanumeric" characters as valid, which would let a non-English key silently bypass
# the (English-only) FORBIDDEN_KEYS set below.
_MEMORY_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class ReplayState:
    principal: Principal
    discovered: frozenset[int] = frozenset()
    read: tuple[int, ...] = ()
    memory: Mapping[str, str] = MappingProxyType({})


Result = tuple[bool, dict[str, Any], str | None, ReplayState]
Handler = Callable[["ReplayContext", ReplayState, dict[str, Any]], Result]


@dataclass(frozen=True, slots=True)
class ReplayContext:
    snapshot: ReplaySnapshot
    index: Bm25Index
    materials: Mapping[int, SnapshotMaterial]
    pages: Mapping[str, Any]


def _visible(context: ReplayContext, state: ReplayState, material: SnapshotMaterial) -> bool:
    # Search/get/read here only ever expose metadata and the public preview pages (see the
    # materials_read ToolSpec: "公开预览页正文"), never the gated full content that
    # guardrails.permissions.can_read's "paid" branch protects (no tool in TOOL_SPECS reads
    # full paid content). So "paid" is discoverable/previewable like "public"/"free"; only
    # "owner" scoped drafts stay gated, via can_read.
    if material.access_scope == "owner":
        return can_read(
            state.principal, material_id=material.material_id, access_scope="owner", owner_id=material.owner_id
        )
    return True


def _summary(material: SnapshotMaterial) -> dict[str, Any]:
    return {
        "material_id": material.material_id,
        "title": material.title,
        "course": material.course,
        "school": material.school,
        "price_cents": material.price_cents,
        "tags": list(material.tags),
    }


def _error(state: ReplayState, code: str, **details: Any) -> Result:
    return False, {"error": code, **details}, code, state


def _clamp(value: Any, *, default: int, upper: int) -> int:
    return max(1, min(int(value if value is not None else default), upper))


def _search_rows(
    context: ReplayContext, state: ReplayState, query: str, limit: int, **filters: str | None
) -> list[SnapshotMaterial]:
    hits = context.index.search(query, limit=len(context.materials))
    rows = [row for _, row in hits if _visible(context, state, row)]
    for field, expected in filters.items():
        if expected:
            rows = [row for row in rows if getattr(row, field) == expected]
    return rows[:limit]


def materials_search(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    rows = _search_rows(
        context,
        state,
        args["query"],
        _clamp(args.get("limit"), default=5, upper=10),
        school=args.get("school"),
        course=args.get("course"),
    )
    new_state = replace(state, discovered=state.discovered | {row.material_id for row in rows})
    return True, {"results": [_summary(row) for row in rows]}, None, new_state


def materials_recommend(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    candidates = _search_rows(context, state, args["context"], len(context.materials))
    limit = _clamp(args.get("limit"), default=3, upper=5)
    rows = sorted(candidates, key=lambda row: (-row.downloads, row.material_id))[:limit]
    new_state = replace(state, discovered=state.discovered | {row.material_id for row in rows})
    return True, {"results": [_summary(row) for row in rows]}, None, new_state


def _discovered_material(context: ReplayContext, state: ReplayState, material_id: int) -> SnapshotMaterial | str:
    material = context.materials.get(material_id)
    if material is None or not _visible(context, state, material):
        return "material_not_found"
    if material_id not in state.discovered:
        return "material_not_discovered"
    return material


def materials_get(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    material = _discovered_material(context, state, args["material_id"])
    if isinstance(material, str):
        return _error(state, material, material_id=args["material_id"])
    payload = {
        **_summary(material),
        "summary": material.summary,
        "preview_page_count": len(material.preview_pages),
        "downloads": material.downloads,
    }
    return True, payload, None, state


def materials_read(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    material = _discovered_material(context, state, args["material_id"])
    if isinstance(material, str):
        return _error(state, material, material_id=args["material_id"])
    if not set(material.unlock_after) <= set(state.read):
        return _error(
            state, "material_locked", material_id=material.material_id, read_first=list(material.unlock_after)
        )
    page = int(args.get("page") or 1)
    if not 1 <= page <= len(material.preview_pages):
        return _error(
            state, "page_out_of_range", material_id=material.material_id, page_count=len(material.preview_pages)
        )
    read = state.read if material.material_id in state.read else (*state.read, material.material_id)
    payload = {
        "material_id": material.material_id,
        "page": page,
        "text": material.preview_pages[page - 1],
        "citation": f"[{material.material_id}:{page}]",
    }
    return True, payload, None, replace(state, read=read)


def platform_policy(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    text = context.snapshot.policies.get(args["topic"])
    if text is None:
        return _error(state, "policy_not_found", topic=args["topic"])
    return True, {"topic": args["topic"], "text": text}, None, state


def web_extract(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    urls = list(args["urls"])
    if len(urls) > _WEB_POLICY.max_urls_per_call:
        return _error(state, "too_many_urls", limit=_WEB_POLICY.max_urls_per_call)
    pages = []
    for url in urls:
        try:
            _WEB_POLICY.validate_url(url, resolver=lambda _host: [SNAPSHOT_HOST_ADDRESS])
        except UnsafeUrlError:
            pages.append({"url": url, "error": "unsafe_url"})
            continue
        page = context.pages.get(url)
        if page:
            pages.append({"url": url, "title": page.title, "text": page.text})
        else:
            pages.append({"url": url, "error": "not_in_snapshot"})
    return True, {"pages": pages}, None, state


def memory_get(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    keys = args.get("keys")
    memory = dict(state.memory) if not keys else {key: state.memory[key] for key in keys if key in state.memory}
    return True, {"memory": memory}, None, state


def memory_update(context: ReplayContext, state: ReplayState, args: dict[str, Any]) -> Result:
    key = str(args["key"]).strip().lower()
    if key in FORBIDDEN_KEYS or not _MEMORY_KEY_PATTERN.match(key):
        return _error(state, "forbidden_memory_key", key=key)
    value = sanitize_output(str(args["value"]))
    new_memory = MappingProxyType({**state.memory, key: value})
    return True, {"key": key, "stored": True}, None, replace(state, memory=new_memory)


HANDLERS: Mapping[str, Handler] = MappingProxyType(
    {
        "materials_search": materials_search,
        "materials_get": materials_get,
        "materials_recommend": materials_recommend,
        "materials_read": materials_read,
        "platform_policy": platform_policy,
        "web_extract": web_extract,
        "memory_get": memory_get,
        "memory_update": memory_update,
    }
)
