from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from app.models.materials import MaterialRecord


@dataclass(frozen=True, slots=True)
class AgentMaterialSignals:
    quality_score: int
    quality_signals: tuple[str, ...]
    risk_signals: tuple[str, ...]

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"quality_score": self.quality_score}
        if self.quality_signals:
            payload["quality_signals"] = list(self.quality_signals)
        if self.risk_signals:
            payload["risk_signals"] = list(self.risk_signals)
        return payload


def build_material_signals(material: MaterialRecord) -> AgentMaterialSignals:
    quality_score = 0
    quality_signals: list[str] = []
    risk_signals: list[str] = []

    description = _clean_text(getattr(material, "description", None), max_chars=400)
    tags = _json_string_list(getattr(material, "tags_json", None))
    if len(description) >= 24:
        quality_score += 2
        quality_signals.append("简介完整")
    elif not description:
        risk_signals.append("简介缺失")
    else:
        risk_signals.append("简介较短")

    if len(tags) >= 2:
        quality_score += 2
        quality_signals.append("标签较完整")
    elif not tags:
        risk_signals.append("标签缺失")

    if _has_delivery_source(material):
        quality_score += 2
        quality_signals.append("交付信息可用")
    else:
        risk_signals.append("交付信息缺失")

    review_status = _clean_text(getattr(material, "review_status", None), max_chars=32).upper()
    if review_status in {"APPROVED", "PASSED"}:
        quality_score += 2
        quality_signals.append("审核通过")
    elif review_status in {"REJECTED", "NEEDS_CHANGES", "BLOCKED"}:
        risk_signals.append("审核状态需复核")

    preview_status = _clean_text(getattr(material, "preview_status", None), max_chars=32).lower()
    if preview_status == "done":
        quality_score += 1
        quality_signals.append("预览已生成")
    elif _looks_like_pdf(material) and preview_status and preview_status not in {"done", "unsupported"}:
        risk_signals.append("预览未就绪")

    if _clean_text(getattr(material, "copyright_owner", None), max_chars=64):
        quality_score += 1
        quality_signals.append("版权归属已标注")
    elif not bool(getattr(material, "is_free", True)) or int(getattr(material, "price", 0) or 0) > 0:
        risk_signals.append("版权归属未标注")

    rating_count = int(getattr(material, "rating_count", 0) or 0)
    rating_avg = float(getattr(material, "rating_avg", 0) or 0)
    if rating_count >= 3 and rating_avg >= 4:
        quality_score += 3
        quality_signals.append("高评分资料")
    elif rating_count > 0 and rating_avg < 3:
        risk_signals.append("评分偏低")

    download_count = int(getattr(material, "download_count", 0) or 0)
    like_count = int(getattr(material, "like_count", 0) or 0)
    if download_count >= 50:
        quality_score += 2
        quality_signals.append("下载量较高")
    elif download_count >= 10:
        quality_score += 1
        quality_signals.append("已有下载反馈")
    if like_count >= 10:
        quality_score += 1
        quality_signals.append("点赞反馈较多")

    return AgentMaterialSignals(
        quality_score=quality_score,
        quality_signals=tuple(_dedupe(quality_signals)[:8]),
        risk_signals=tuple(_dedupe(risk_signals)[:8]),
    )


def _has_delivery_source(material: MaterialRecord) -> bool:
    return bool(
        _clean_text(getattr(material, "file_storage_key", None), max_chars=512)
        or _clean_text(getattr(material, "netdisk_url", None), max_chars=512)
        or _clean_text(getattr(material, "custom_preview_text", None), max_chars=128)
    )


def _looks_like_pdf(material: MaterialRecord) -> bool:
    file_type = _clean_text(getattr(material, "file_type", None), max_chars=32).lower()
    filename = _clean_text(getattr(material, "original_filename", None), max_chars=255).lower()
    key = _clean_text(getattr(material, "file_storage_key", None), max_chars=512).lower()
    return file_type == "pdf" or filename.endswith(".pdf") or key.endswith(".pdf")


def _json_string_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [_clean_text(item, max_chars=40) for item in parsed if _clean_text(item, max_chars=40)]


def _clean_text(value: Any, *, max_chars: int) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:max_chars]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
