from __future__ import annotations

import json

from app.models.materials import MaterialRecord
from app.services.materials_query_support import (
    compat_material_filter_parts,
    compat_material_order_clause,
    compat_sort_material_rows,
)
from app.services.materials_search import (
    SYNONYM_FILE_ENV,
    clear_material_search_cache,
    material_mapping_matches_search,
    material_mapping_search_score,
    material_matches_search,
    material_search_glossary,
    material_search_score,
    parse_material_search_query,
)


def _material(
    *,
    title: str,
    description: str = "",
    keywords: str = "",
    tags: list[str] | None = None,
    filename: str = "",
    downloads: int = 0,
) -> MaterialRecord:
    return MaterialRecord(
        id=1,
        title=title,
        description=description,
        keywords=keywords,
        tags_json=json.dumps(tags or [], ensure_ascii=False),
        original_filename=filename,
        is_free=True,
        price=0,
        download_count=downloads,
        like_count=0,
        rating_count=0,
        rating_avg=0,
        general_course=False,
        preview_watermark_enabled=True,
        preview_source="AUTO",
        status="VISIBLE",
    )


def _load_tags(raw: str | None) -> list[str]:
    return json.loads(raw or "[]")


def test_multi_keyword_requires_course_core_term(monkeypatch, tmp_path) -> None:
    synonym_file = tmp_path / "synonyms.json"
    synonym_file.write_text('{"概率论": ["概率论与数理统计", "概率统计"]}', encoding="utf-8")
    monkeypatch.setenv(SYNONYM_FILE_ENV, str(synonym_file))
    clear_material_search_cache()

    query = parse_material_search_query("概率论 期末 真题")
    probability = _material(title="概率论与数理统计期末真题解析", tags=["真题"])
    calculus = _material(title="微积分期末真题解析", tags=["真题"])

    assert material_matches_search(probability, query, _load_tags) is True
    assert material_matches_search(calculus, query, _load_tags) is False


def test_auxiliary_only_query_matches_all_requested_aux_terms() -> None:
    query = parse_material_search_query("期末 真题")

    assert material_mapping_matches_search({"title": "微积分期末真题", "tags": []}, query) is True
    assert material_mapping_matches_search({"title": "微积分期末复习", "tags": []}, query) is False


def test_private_synonym_file_expands_short_course_names(monkeypatch, tmp_path) -> None:
    synonym_file = tmp_path / "synonyms.json"
    synonym_file.write_text('{"大物": ["大学物理"]}', encoding="utf-8")
    monkeypatch.setenv(SYNONYM_FILE_ENV, str(synonym_file))
    clear_material_search_cache()

    query = parse_material_search_query("大物 复习")
    material = _material(title="大学物理期末复习 PPT")

    assert material_matches_search(material, query, _load_tags) is True


def test_private_synonyms_supply_agent_platform_glossary(monkeypatch, tmp_path) -> None:
    synonym_file = tmp_path / "synonyms.json"
    synonym_file.write_text('{"ESD": ["电子系统设计"], "CPS": ["通信原理"]}', encoding="utf-8")
    monkeypatch.setenv(SYNONYM_FILE_ENV, str(synonym_file))
    clear_material_search_cache()

    glossary = material_search_glossary("两周后考 ESD，之后还要复习 CPS")

    assert glossary == {
        "esd": ["esd", "电子系统设计"],
        "cps": ["cps", "通信原理"],
    }


def test_keyword_score_prefers_title_match_over_description_only() -> None:
    query = parse_material_search_query("期末 真题")
    title_match = _material(title="线性代数期末真题", description="", downloads=1)
    description_match = _material(title="线性代数资料", description="包含期末真题", downloads=20)

    assert material_search_score(title_match, query, _load_tags) > material_search_score(description_match, query, _load_tags)
    assert material_mapping_search_score({"title": "线性代数期末真题"}, query) > material_mapping_search_score({"description": "包含期末真题"}, query)


def test_compat_keyword_filter_uses_core_groups_and_synonyms(monkeypatch, tmp_path) -> None:
    synonym_file = tmp_path / "synonyms.json"
    synonym_file.write_text('{"概率论": ["概率论与数理统计"]}', encoding="utf-8")
    monkeypatch.setenv(SYNONYM_FILE_ENV, str(synonym_file))
    clear_material_search_cache()

    clauses, params = compat_material_filter_parts(
        keyword="概率论 期末 真题",
        school=None,
        college=None,
        major=None,
        tag=None,
        grade_value=None,
        course_category=None,
        price=None,
        visible_material_status_sql="m.status = 'VISIBLE'",
    )

    joined = " AND ".join(clauses)
    assert "keyword_core_0_0" in joined
    assert "keyword_core_0_1" in joined
    assert "keyword_aux" not in joined
    assert params["keyword_core_0_0"] == "%概率论%"
    assert params["keyword_core_0_1"] == "%概率论与数理统计%"


def test_compat_order_clause_adds_keyword_score_for_default_sort(monkeypatch, tmp_path) -> None:
    synonym_file = tmp_path / "synonyms.json"
    synonym_file.write_text('{"概率论": ["概率论与数理统计"]}', encoding="utf-8")
    monkeypatch.setenv(SYNONYM_FILE_ENV, str(synonym_file))
    clear_material_search_cache()

    order_sql, params, score_sql = compat_material_order_clause(sort="latest", profile=None, keyword="概率论 真题")

    assert order_sql.startswith("recommendation_score DESC")
    assert "keyword_score_0_0" in score_sql
    assert "keyword_score_0_1" in score_sql
    assert "keyword_score_1_0" in score_sql
    assert params["keyword_score_0_0"] == "%概率论%"


def test_explicit_material_sort_orders_are_stable_across_database_paths() -> None:
    newest_sql, newest_params, newest_score = compat_material_order_clause(
        sort="newest", profile={"school": "电子科技大学"}, keyword="概率论"
    )
    downloads_sql, downloads_params, downloads_score = compat_material_order_clause(
        sort="downloads", profile={"school": "电子科技大学"}, keyword="概率论"
    )

    assert newest_sql == "m.created_at DESC, m.id DESC"
    assert newest_params == {}
    assert newest_score == "0"
    assert downloads_sql.startswith("COALESCE(m.download_count, 0) DESC")
    assert downloads_params == {}
    assert downloads_score == "0"

    rows = [
        {"id": 1, "download_count": 5, "created_at": "2026-01-03T00:00:00Z"},
        {"id": 2, "download_count": 20, "created_at": "2026-01-01T00:00:00Z"},
        {"id": 3, "download_count": 5, "created_at": "2026-01-04T00:00:00Z"},
    ]
    assert [row["id"] for row in compat_sort_material_rows(rows, sort="newest", profile=None)] == [3, 1, 2]
    assert [row["id"] for row in compat_sort_material_rows(rows, sort="downloads", profile=None)] == [2, 3, 1]
