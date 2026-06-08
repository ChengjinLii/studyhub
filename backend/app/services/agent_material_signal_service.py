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

    description = _clean_text(safe_material_value(material, "description"), max_chars=400)
    tags = _json_string_list(safe_material_value(material, "tags_json"))
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

    review_status = _clean_text(safe_material_value(material, "review_status"), max_chars=32).upper()
    if review_status in {"APPROVED", "PASSED"}:
        quality_score += 2
        quality_signals.append("审核通过")
    elif review_status in {"REJECTED", "NEEDS_CHANGES", "BLOCKED"}:
        risk_signals.append("审核状态需复核")

    preview_status = _clean_text(safe_material_value(material, "preview_status"), max_chars=32).lower()
    if preview_status == "done":
        quality_score += 1
        quality_signals.append("预览已生成")
    elif _looks_like_pdf(material) and preview_status and preview_status not in {"done", "unsupported"}:
        risk_signals.append("预览未就绪")

    if _clean_text(safe_material_value(material, "copyright_owner"), max_chars=64):
        quality_score += 1
        quality_signals.append("版权归属已标注")
    elif not bool(safe_material_value(material, "is_free", True)) or _safe_int(safe_material_value(material, "price"), 0) > 0:
        risk_signals.append("版权归属未标注")

    rating_count = _safe_int(safe_material_value(material, "rating_count"), 0)
    rating_avg = _safe_float(safe_material_value(material, "rating_avg"), 0.0)
    if rating_count >= 3 and rating_avg >= 4:
        quality_score += 3
        quality_signals.append("高评分资料")
    elif rating_count > 0 and rating_avg < 3:
        risk_signals.append("评分偏低")

    download_count = _safe_int(safe_material_value(material, "download_count"), 0)
    like_count = _safe_int(safe_material_value(material, "like_count"), 0)
    if download_count >= 50:
        quality_score += 2
        quality_signals.append("下载量较高")
    elif download_count >= 10:
        quality_score += 1
        quality_signals.append("已有下载反馈")
    if like_count >= 10:
        quality_score += 1
        quality_signals.append("点赞反馈较多")

    risk_signals.extend(_content_risk_signals(material))

    return AgentMaterialSignals(
        quality_score=quality_score,
        quality_signals=tuple(_dedupe(quality_signals)[:8]),
        risk_signals=tuple(_dedupe(risk_signals)[:8]),
    )


def _has_delivery_source(material: MaterialRecord) -> bool:
    return bool(
        _clean_text(safe_material_value(material, "file_storage_key"), max_chars=512)
        or _clean_text(safe_material_value(material, "netdisk_url"), max_chars=512)
        or _clean_text(safe_material_value(material, "custom_preview_text"), max_chars=128)
    )


def _looks_like_pdf(material: MaterialRecord) -> bool:
    file_type = _clean_text(safe_material_value(material, "file_type"), max_chars=32).lower()
    filename = _clean_text(safe_material_value(material, "original_filename"), max_chars=255).lower()
    key = _clean_text(safe_material_value(material, "file_storage_key"), max_chars=512).lower()
    return file_type == "pdf" or filename.endswith(".pdf") or key.endswith(".pdf")


def _content_risk_signals(material: MaterialRecord) -> list[str]:
    text = _material_text(material)
    normalized = text.lower()
    signals: list[str] = []
    if _contains_any(normalized, ("加微信", "微信号", "qq", "vx", "联系方式", "联系我", "群号")):
        signals.append("外部联系方式需复核")
    if _contains_any(normalized, ("代考", "代写", "枪手", "保过", "包过", "买卖答案", "出售答案")):
        signals.append("疑似违规交易风险")
    if _contains_any(normalized, ("盗版", "破解", "泄露", "未授权转载", "内部泄题", "原题泄露")):
        signals.append("疑似版权或来源风险")
    return signals


def _material_text(material: MaterialRecord) -> str:
    values = [
        safe_material_value(material, "title"),
        safe_material_value(material, "description"),
        safe_material_value(material, "keywords"),
        safe_material_value(material, "custom_preview_text"),
        " ".join(_json_string_list(safe_material_value(material, "tags_json"))),
    ]
    return " ".join(_clean_text(value, max_chars=400) for value in values if value).lower()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in text for needle in needles)


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


def safe_material_value(material: MaterialRecord, field: str, default: Any = None) -> Any:
    state = getattr(material, "__dict__", {})
    if isinstance(state, dict) and field in state:
        return state[field]
    return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
