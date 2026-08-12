from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.profile_metadata import SUPPORTED_COLLEGES, normalize_college_selection, normalize_major_selection


def test_profile_metadata_prioritizes_common_colleges() -> None:
    assert SUPPORTED_COLLEGES[:2] == ("格院", "信通")


@pytest.mark.parametrize(
    "college",
    [
        "信通",
        "计算机科学与工程学院（网络空间安全学院）",
        "物理学院",
    ],
)
def test_profile_metadata_accepts_current_uestc_colleges(college: str) -> None:
    assert normalize_college_selection(college) == college


@pytest.mark.parametrize(
    "major",
    ["通信", "电工", "量子信息科学", "低空技术与工程", "大数据管理与应用", "供应链管理"],
)
def test_profile_metadata_accepts_current_uestc_majors(major: str) -> None:
    assert normalize_major_selection(major) == major


def test_profile_metadata_keeps_historical_short_labels() -> None:
    assert normalize_college_selection("信通") == "信通"
    assert normalize_major_selection("通信") == "通信"


def test_profile_metadata_rejects_unlisted_values() -> None:
    with pytest.raises(HTTPException, match="电子科技大学院系"):
        normalize_college_selection("不存在的学院")
    with pytest.raises(HTTPException, match="电子科技大学专业"):
        normalize_major_selection("不存在的专业")
