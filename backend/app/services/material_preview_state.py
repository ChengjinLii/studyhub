from __future__ import annotations

import hashlib
import json
from typing import Any


RENDER_VERSION = "studyhub-preview-3"


def manifest_payload(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def image_keys(value: Any) -> list[str]:
    try:
        values = json.loads(value or "[]") if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
    return [key for key in (values or []) if isinstance(key, str) and key.strip()] if isinstance(values, list) else []


def preview_plan(row: dict, page_limit: int = 3) -> dict:
    manual = image_keys(row.get("manual_preview_keys_json"))
    custom = image_keys(row.get("custom_preview_images_json")) or image_keys(row.get("custom_preview_images"))
    source = str(row.get("preview_source") or "AUTO").upper()
    experience = row.get("_is_experience") or "经验分享" in image_keys(row.get("tags_json"))
    pdf = str(row.get("file_type") or "").lower() == "pdf" and source != "MANUAL" and not experience
    key = row.get("file_storage_key") or row.get("file_key")
    return {
        "pdf": str(key) if pdf and key else None,
        "images": [] if pdf or experience else (manual or custom)[:10],
        "customImages": custom[:5] if pdf and not experience else [],
        "galleryFromPages": source != "MANUAL" and not pdf and not experience,
        "watermark": row.get("preview_watermark_enabled") not in (False, 0, "0"),
        "limit": max(1, min(5, page_limit)),
        "version": RENDER_VERSION,
    }


def plan_fingerprint(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def preview_supported(plan: dict) -> bool:
    return bool(plan["pdf"] or plan["images"])


def preview_blocked(row: dict) -> bool:
    return bool(row.get("deleted_at")) or str(row.get("status") or "").upper() in {"HIDDEN", "REMOVED"} or str(
        row.get("review_status") or ""
    ).upper().startswith("SECURITY_")


def published_preview(manifest: dict, plan: dict) -> dict:
    fingerprint = plan_fingerprint(plan)

    def ready(value: dict) -> bool:
        pages = value.get("pages")
        return value.get("status") in (None, "done") and isinstance(pages, list) and bool(pages) and all(
            isinstance(page, dict) and page.get("key") for page in pages
        )

    if ready(manifest) and (manifest.get("fingerprint") == fingerprint or not str(
        manifest.get("renderVersion") or ""
    ).startswith("studyhub-")):
        return manifest
    previous = manifest.get("previous")
    if manifest.get("fingerprint") == fingerprint and isinstance(previous, dict) and ready(previous):
        if previous.get("fingerprint") == fingerprint or (
            plan["pdf"] and previous.get("sourceKey") == plan["pdf"] and bool(previous.get("watermark")) == plan["watermark"]
        ):
            return previous
    return {}


def public_preview_manifest(raw: Any) -> str | None:
    manifest = manifest_payload(raw)
    if not manifest:
        return None
    # Detail responses must not expose source keys, errors or storage credentials.
    return json.dumps({key: manifest.get(key) for key in ("status", "pageCount", "previewPages")})


def generated_custom_keys(raw: Any, fallback: list[str], *, manual: bool = False) -> list[str]:
    manifest = manifest_payload(raw)
    if manifest.get("renderVersion") != RENDER_VERSION:
        return fallback
    pages = manifest.get("pages" if manual else "customPages") or []
    return [page["key"] for page in pages if isinstance(page, dict) and isinstance(page.get("key"), str)]


def generated_gallery_urls(asset_store, material_id: int, raw: Any) -> list[str] | None:
    manifest = manifest_payload(raw)
    if manifest.get("renderVersion") != RENDER_VERSION:
        return None
    if manifest.get("status") != "done":
        return []
    return [asset_store.build_preview_url(material_id=material_id, index=page["index"], key=page["key"], placeholder=False)
            for page in manifest.get("customPages", [])]
