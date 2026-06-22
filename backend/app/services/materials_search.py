from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from app.models.materials import MaterialRecord


TOKEN_SPLIT_PATTERN = re.compile(r"[\s,，、;；|/\\]+")
DEFAULT_SYNONYM_FILE = Path(__file__).resolve().parents[3] / "private" / "material_search_synonyms.json"
SYNONYM_FILE_ENV = "STUDYHUB_MATERIAL_SEARCH_SYNONYMS_PATH"

AUXILIARY_TERMS = {
    "答案",
    "补考",
    "报告",
    "笔记",
    "复习",
    "讲义",
    "考研",
    "解析",
    "期末",
    "期中",
    "ppt",
    "PPT",
    "试卷",
    "实验",
    "速成",
    "题库",
    "真题",
}


@dataclass(frozen=True)
class MaterialSearchQuery:
    raw: str
    required_groups: tuple[tuple[str, ...], ...]
    boost_terms: tuple[str, ...]

    @property
    def has_terms(self) -> bool:
        return bool(self.required_groups or self.boost_terms)


_synonym_cache: dict[tuple[str, float | None], dict[str, tuple[str, ...]]] = {}


def clear_material_search_cache() -> None:
    _synonym_cache.clear()


def _normalize_term(value: str) -> str:
    return value.strip().lower()


NORMALIZED_AUXILIARY_TERMS = {_normalize_term(item) for item in AUXILIARY_TERMS}


def _synonym_file_path() -> Path:
    configured = os.getenv(SYNONYM_FILE_ENV)
    return Path(configured) if configured else DEFAULT_SYNONYM_FILE


def _load_synonym_map() -> dict[str, tuple[str, ...]]:
    path = _synonym_file_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cache_key = (str(path), mtime)
    cached = _synonym_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    synonyms: dict[str, tuple[str, ...]] = {}
    if isinstance(raw, dict):
        for key, values in raw.items():
            if not isinstance(key, str):
                continue
            terms = [_normalize_term(key)]
            if isinstance(values, list):
                terms.extend(_normalize_term(item) for item in values if isinstance(item, str))
            unique = tuple(term for term in dict.fromkeys(terms) if term)
            if unique:
                for term in unique:
                    synonyms[term] = unique
    _synonym_cache.clear()
    _synonym_cache[cache_key] = synonyms
    return synonyms


def parse_material_search_query(keyword: str | None) -> MaterialSearchQuery:
    raw = (keyword or "").strip()
    if not raw:
        return MaterialSearchQuery(raw="", required_groups=(), boost_terms=())
    synonyms = _load_synonym_map()
    required_groups: list[tuple[str, ...]] = []
    boost_terms: list[str] = []
    seen_groups: set[tuple[str, ...]] = set()
    seen_boosts: set[str] = set()
    for token in TOKEN_SPLIT_PATTERN.split(raw):
        term = _normalize_term(token)
        if not term:
            continue
        if term in NORMALIZED_AUXILIARY_TERMS:
            if term not in seen_boosts:
                seen_boosts.add(term)
                boost_terms.append(term)
            continue
        group = synonyms.get(term, (term,))
        if group not in seen_groups:
            seen_groups.add(group)
            required_groups.append(group)
    return MaterialSearchQuery(raw=raw, required_groups=tuple(required_groups), boost_terms=tuple(boost_terms))


def _material_fields(material: MaterialRecord, tags_loader: Callable[[str | None], list[Any]]) -> dict[str, str]:
    tags = [str(item) for item in tags_loader(material.tags_json) if item is not None]
    return {
        "title": material.title or "",
        "keywords": material.keywords or "",
        "tags": " ".join(tags),
        "filename": material.original_filename or "",
        "description": material.description or "",
        "school": material.school or "",
        "college": material.college or "",
        "major": material.major or "",
    }


def _contains_any(fields: dict[str, str], terms: tuple[str, ...]) -> bool:
    normalized_values = [_normalize_term(value) for value in fields.values() if value]
    return any(term in value for term in terms for value in normalized_values)


def material_matches_search(
    material: MaterialRecord,
    query: MaterialSearchQuery,
    tags_loader: Callable[[str | None], list[Any]],
) -> bool:
    if not query.has_terms:
        return True
    fields = _material_fields(material, tags_loader)
    if query.required_groups:
        return all(_contains_any(fields, group) for group in query.required_groups)
    return all(_contains_any(fields, (term,)) for term in query.boost_terms)


def material_search_score(
    material: MaterialRecord,
    query: MaterialSearchQuery,
    tags_loader: Callable[[str | None], list[Any]],
) -> int:
    if not query.has_terms:
        return 0
    fields = {name: _normalize_term(value) for name, value in _material_fields(material, tags_loader).items()}
    weighted_fields = (
        ("title", 50),
        ("keywords", 35),
        ("tags", 35),
        ("filename", 25),
        ("description", 12),
        ("major", 8),
        ("college", 6),
        ("school", 4),
    )
    score = 0
    term_groups = list(query.required_groups) + [(term,) for term in query.boost_terms]
    for group in term_groups:
        for field_name, weight in weighted_fields:
            value = fields[field_name]
            if value and any(term in value for term in group):
                score += weight
                break
    score += min(int(material.download_count or 0), 100) // 5
    score += min(int(material.like_count or 0), 30)
    score += min(int(material.rating_count or 0), 20) * max(0, min(int(float(material.rating_avg or 0)), 5))
    return score


def material_mapping_matches_search(material: dict[str, Any], query: MaterialSearchQuery) -> bool:
    if not query.has_terms:
        return True
    tags = material.get("tags") or []
    fields = {
        "title": str(material.get("title") or ""),
        "keywords": str(material.get("keywords") or ""),
        "tags": " ".join(str(item) for item in tags if item is not None),
        "filename": str(material.get("originalFilename") or ""),
        "description": str(material.get("description") or ""),
        "school": str(material.get("school") or ""),
        "college": str(material.get("college") or ""),
        "major": str(material.get("major") or ""),
    }
    if query.required_groups:
        return all(_contains_any(fields, group) for group in query.required_groups)
    return all(_contains_any(fields, (term,)) for term in query.boost_terms)


def material_mapping_search_score(material: dict[str, Any], query: MaterialSearchQuery) -> int:
    if not query.has_terms:
        return 0
    tags = material.get("tags") or []
    fields = {
        "title": _normalize_term(str(material.get("title") or "")),
        "keywords": _normalize_term(str(material.get("keywords") or "")),
        "tags": _normalize_term(" ".join(str(item) for item in tags if item is not None)),
        "filename": _normalize_term(str(material.get("originalFilename") or "")),
        "description": _normalize_term(str(material.get("description") or "")),
        "major": _normalize_term(str(material.get("major") or "")),
        "college": _normalize_term(str(material.get("college") or "")),
        "school": _normalize_term(str(material.get("school") or "")),
    }
    weighted_fields = (
        ("title", 50),
        ("keywords", 35),
        ("tags", 35),
        ("filename", 25),
        ("description", 12),
        ("major", 8),
        ("college", 6),
        ("school", 4),
    )
    score = 0
    term_groups = list(query.required_groups) + [(term,) for term in query.boost_terms]
    for group in term_groups:
        for field_name, weight in weighted_fields:
            value = fields[field_name]
            if value and any(term in value for term in group):
                score += weight
                break
    score += min(int(material.get("downloadCount") or 0), 100) // 5
    score += min(int(material.get("likeCount") or 0), 30)
    score += min(int(material.get("ratingCount") or 0), 20) * max(0, min(int(float(material.get("ratingAvg") or 0)), 5))
    return score
