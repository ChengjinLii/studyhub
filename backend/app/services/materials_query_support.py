from __future__ import annotations

import re
from typing import Any

from app.services.read_support import compat_as_int, compat_normalize_text, compat_timestamp


MAJOR_SPLIT_PATTERN = re.compile(r"[，,、/]+")


def compat_normalize_major_selections(raw: Any) -> list[str]:
    value = compat_normalize_text(raw)
    if not value:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for chunk in MAJOR_SPLIT_PATTERN.split(value):
        item = chunk.strip()
        if not item:
            continue
        if item not in seen:
            seen.add(item)
            normalized.append(item)
    return normalized


def compat_extract_primary_major(raw: Any) -> str | None:
    selections = compat_normalize_major_selections(raw)
    return selections[0] if selections else None


def compat_major_matches(stored: str, target: str) -> bool:
    if not target:
        return False
    return target in compat_normalize_major_selections(stored)


def compat_recommendation_score(
    row: dict[str, Any],
    *,
    school: str | None,
    college: str | None,
    major: str | None,
) -> int:
    score = 0
    material_school = compat_normalize_text(row["school"])
    material_college = compat_normalize_text(row["college"])
    material_major = compat_normalize_text(row["major"])
    if school and material_school and school != material_school:
        score -= 45
    if college and material_college and college != material_college:
        score -= 15
    if major and material_major and not compat_major_matches(material_major, major):
        score -= 8
    return score


def compat_sort_material_rows(
    rows: list[dict[str, Any]],
    *,
    sort: str | None,
    profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    ordered = list(rows)
    normalized_sort = (sort or "latest").strip().lower()
    if normalized_sort == "price":
        ordered.sort(
            key=lambda row: (compat_as_int(row["price"]), compat_timestamp(row["created_at"])),
            reverse=True,
        )
        return ordered
    if normalized_sort == "sales":
        ordered.sort(
            key=lambda row: (compat_as_int(row["sales_count"]), compat_timestamp(row["created_at"])),
            reverse=True,
        )
        return ordered

    school = compat_normalize_text(profile.get("school")) if profile else None
    college = compat_normalize_text(profile.get("college")) if profile else None
    major = compat_extract_primary_major(profile.get("major")) if profile else None
    ordered.sort(
        key=lambda row: (
            compat_recommendation_score(row, school=school, college=college, major=major),
            compat_as_int(row["download_count"]),
            compat_timestamp(row["created_at"]),
        ),
        reverse=True,
    )
    return ordered


def compat_material_order_clause(
    *,
    sort: str | None,
    profile: dict[str, Any] | None,
) -> tuple[str, dict[str, Any], str]:
    normalized_sort = (sort or "latest").strip().lower()
    if normalized_sort == "price":
        return "COALESCE(m.price, 0) DESC, m.created_at DESC, m.id DESC", {}, "0"
    if normalized_sort == "sales":
        return "COALESCE(m.sales_count, 0) DESC, m.created_at DESC, m.id DESC", {}, "0"

    school = compat_normalize_text(profile.get("school")) if profile else None
    college = compat_normalize_text(profile.get("college")) if profile else None
    major = compat_extract_primary_major(profile.get("major")) if profile else None
    params: dict[str, Any] = {
        "profile_school": school,
        "profile_college": college,
        "profile_major_like": f"%{major}%" if major else None,
    }
    recommendation_score_sql = """
        (
            CASE
                WHEN :profile_school IS NOT NULL
                 AND COALESCE(m.school, '') <> ''
                 AND m.school <> :profile_school
                THEN -45 ELSE 0
            END
            +
            CASE
                WHEN :profile_college IS NOT NULL
                 AND COALESCE(m.college, '') <> ''
                 AND m.college <> :profile_college
                THEN -15 ELSE 0
            END
            +
            CASE
                WHEN :profile_major_like IS NOT NULL
                 AND COALESCE(m.major, '') <> ''
                 AND LOWER(COALESCE(m.major, '')) NOT LIKE LOWER(:profile_major_like)
                THEN -8 ELSE 0
            END
        )
    """
    return (
        "recommendation_score DESC, COALESCE(m.download_count, 0) DESC, m.created_at DESC, m.id DESC",
        params,
        recommendation_score_sql,
    )


def compat_material_filter_parts(
    *,
    keyword: str | None,
    school: str | None,
    college: str | None,
    major: str | None,
    tag: str | None,
    grade_value: str | None,
    course_category: str | None,
    price: str | None,
    visible_material_status_sql: str,
) -> tuple[list[str], dict[str, Any]]:
    where_clauses = ["m.deleted_at IS NULL", visible_material_status_sql]
    params: dict[str, Any] = {}
    if compat_normalize_text(keyword):
        params["keyword"] = f"%{keyword.strip().lower()}%"
        where_clauses.append(
            "(LOWER(COALESCE(m.title, '')) LIKE :keyword OR LOWER(COALESCE(m.description, '')) LIKE :keyword OR LOWER(COALESCE(m.keywords, '')) LIKE :keyword)"
        )
    if compat_normalize_text(school):
        params["school"] = school.strip()
        where_clauses.append("m.school = :school")
    if compat_normalize_text(college):
        params["college"] = college.strip()
        where_clauses.append("m.college = :college")
    if compat_normalize_text(major):
        normalized_major = compat_extract_primary_major(major)
        if normalized_major is None:
            return ["1 = 0"], {}
        params["major_like"] = f"%{normalized_major}%"
        where_clauses.append("LOWER(COALESCE(m.major, '')) LIKE LOWER(:major_like)")
    if compat_normalize_text(tag):
        params["tag"] = tag.strip().lower()
        where_clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM material_tags mt
                WHERE mt.material_id = m.id
                  AND LOWER(mt.tag) = :tag
            )
            """
        )
    if compat_normalize_text(grade_value):
        params["grade_value"] = grade_value.strip().lower()
        where_clauses.append("LOWER(COALESCE(m.grade_value, '')) = :grade_value")
    if compat_normalize_text(course_category):
        params["course_category"] = course_category.strip().upper()
        where_clauses.append("UPPER(COALESCE(m.course_category, 'MAJOR')) = :course_category")
    if compat_normalize_text(price):
        normalized_price = price.strip().lower()
        if normalized_price == "free":
            where_clauses.append("m.is_free = 1")
        elif normalized_price == "paid":
            where_clauses.append("m.is_free = 0")
    return where_clauses, params
