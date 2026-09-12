"""Shared SQL and projections for synchronous and asynchronous legacy reads.

Session execution and compatibility conversion policies stay with the caller.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.sql.elements import TextClause


def tags_statement() -> TextClause:
    return text("""
        SELECT material_id, tag
        FROM material_tags
        WHERE material_id IN :material_ids
        ORDER BY id ASC
    """).bindparams(bindparam("material_ids", expanding=True))


def comment_counts_statement() -> TextClause:
    return text("""
        SELECT material_id, COUNT(*) AS total
        FROM comments
        WHERE status = 'visible' AND material_id IN :material_ids
        GROUP BY material_id
    """).bindparams(bindparam("material_ids", expanding=True))


def versions_statement() -> TextClause:
    return text("""
        SELECT id, version_label, changelog, file_type, created_at
        FROM material_versions
        WHERE material_id = :material_id
        ORDER BY created_at DESC, id DESC
    """)


def reviews_statement() -> TextClause:
    return text("""
        SELECT id, reviewer, rating, comment, created_at
        FROM reviews
        WHERE material_id = :material_id
        ORDER BY created_at DESC, id DESC
    """)


def tags_map(rows: Iterable[Mapping[str, Any]], material_ids: list[int], *, has_text: Callable[[Any], bool]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {material_id: [] for material_id in material_ids}
    for row in rows:
        material_id = int(row["material_id"])
        if has_text(row["tag"]):
            result.setdefault(material_id, []).append(str(row["tag"]))
    return result


def comment_counts(rows: Iterable[Mapping[str, Any]]) -> dict[int, int]:
    return {int(row["material_id"]): int(row["total"]) for row in rows}


def versions(rows: Iterable[Mapping[str, Any]], *, serialize_datetime: Callable[[Any], str | None]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(row["id"]),
            "versionLabel": row["version_label"],
            "changelog": row["changelog"],
            "fileType": row["file_type"],
            "createdAt": serialize_datetime(row["created_at"]),
        }
        for row in rows
    ]


def reviews(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_int: Callable[[Any], int],
    serialize_datetime: Callable[[Any], str | None],
) -> list[dict[str, Any]]:
    return [
        {
            "id": int(row["id"]),
            "reviewer": row["reviewer"],
            "rating": as_int(row["rating"]),
            "comment": row["comment"],
            "createdAt": serialize_datetime(row["created_at"]),
        }
        for row in rows
    ]
