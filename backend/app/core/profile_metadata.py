from __future__ import annotations

from fastapi import HTTPException, status


DEFAULT_FREE_DOWNLOAD_QUOTA = 200

SUPPORTED_SCHOOL = "电子科技大学"
SUPPORTED_COLLEGES = ("格院", "信通")
SUPPORTED_MAJORS = ("通信", "微电子", "电工")
SUPPORTED_GRADE_STAGES = ("大一", "大二", "大三", "大四", "研究生", "英语", "技能")


def normalize_school_selection(value: str | None) -> str | None:
    normalized = _strip_or_none(value)
    if normalized is None:
        return None
    if normalized != SUPPORTED_SCHOOL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前仅支持电子科技大学")
    return normalized


def normalize_college_selection(value: str | None) -> str | None:
    normalized = _strip_or_none(value)
    if normalized is None:
        return None
    if normalized not in SUPPORTED_COLLEGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="学院仅支持格院或信通")
    return normalized


def normalize_major_selection(value: str | None) -> str | None:
    normalized = _strip_or_none(value)
    if normalized is None:
        return None
    if normalized not in SUPPORTED_MAJORS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专业仅支持通信、微电子或电工")
    return normalized


def normalize_grade_stages(values: list[str] | None) -> str | None:
    if values is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = _strip_or_none(item)
        if value is None:
            continue
        if value not in SUPPORTED_GRADE_STAGES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="年级/阶段仅支持平台内置选项")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if not normalized:
        return None
    return ",".join(normalized)


def resolve_free_download_quota(quota: int | None) -> int:
    if quota is None:
        return DEFAULT_FREE_DOWNLOAD_QUOTA
    return int(quota)


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
