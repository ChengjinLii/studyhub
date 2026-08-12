from __future__ import annotations

from fastapi import HTTPException, status


DEFAULT_FREE_DOWNLOAD_QUOTA = 200

SUPPORTED_SCHOOL = "电子科技大学"
# Mirror the selectable catalog in frontend/constants/metadata.ts.
SUPPORTED_COLLEGES = (
    "格院",
    "信通",
    "英才实验学院（未来技术学院）",
    "电子科学与工程学院",
    "集成电路科学与工程学院（示范性微电子学院）",
    "材料与能源学院",
    "机械与电气工程学院",
    "光电科学与工程学院",
    "自动化工程学院",
    "资源与环境学院",
    "计算机科学与工程学院（网络空间安全学院）",
    "信息与软件工程学院（示范性软件学院）",
    "航空航天学院",
    "数学科学学院",
    "物理学院",
    "医学院",
    "生命科学与技术学院",
    "经济与管理学院",
    "外国语学院",
    "公共管理学院",
)
SUPPORTED_MAJORS = (
    "通信",
    "电工",
    "网络工程",
    "电磁场与无线技术",
    "电子科学与技术",
    "微电子科学与工程",
    "集成电路设计与集成系统",
    "计算机科学与技术",
    "网络空间安全",
    "人工智能",
    "光电信息科学与工程",
    "信息工程",
    "测控技术与仪器",
    "自动化",
    "材料科学与工程",
    "机械设计制造及其自动化",
    "机器人工程",
    "生物医学工程",
    "信息对抗技术",
    "物联网工程",
    "数理基础科学",
    "新能源材料与器件",
    "应用化学",
    "电气工程及其自动化",
    "智能电网信息工程",
    "工业工程",
    "遥感科学与技术",
    "地球信息科学与技术",
    "数据科学与大数据技术",
    "软件工程",
    "航空航天工程",
    "无人驾驶航空器系统工程",
    "飞行器控制与信息工程",
    "低空技术与工程",
    "数学与应用数学",
    "信息与计算科学",
    "电子信息科学与技术",
    "应用物理学",
    "量子信息科学",
    "临床医学",
    "护理学",
    "生物技术",
    "工商管理",
    "金融学",
    "电子商务",
    "大数据管理与应用",
    "供应链管理",
    "英语",
    "日语",
    "法语",
    "法学",
    "信息管理与信息系统",
    "行政管理",
    "城市管理",
    "微电子",
)
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择平台内置的电子科技大学院系")
    return normalized


def normalize_major_selection(value: str | None) -> str | None:
    normalized = _strip_or_none(value)
    if normalized is None:
        return None
    if normalized not in SUPPORTED_MAJORS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择平台内置的电子科技大学专业")
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
