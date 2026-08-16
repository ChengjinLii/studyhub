from __future__ import annotations

import pytest

from app.ops.index_admin import _plan_token, _select_indexes


def _payload() -> dict[str, object]:
    return {
        "missingIndexes": [
            {"table": "materials", "index": "ix_materials_uploader_id", "columns": ["uploader_id"], "sql": "CREATE INDEX x"},
            {"table": "comments", "index": "ix_comments_material_id", "columns": ["material_id"], "sql": "CREATE INDEX y"},
        ]
    }


def test_index_plan_requires_exact_missing_index_scope() -> None:
    selected = _select_indexes(_payload(), ["comments.ix_comments_material_id"])
    assert [item["index"] for item in selected] == ["ix_comments_material_id"]


def test_index_plan_rejects_unknown_or_invalid_scope() -> None:
    with pytest.raises(RuntimeError, match="不在当前缺失清单"):
        _select_indexes(_payload(), ["comments.ix_missing"])
    with pytest.raises(RuntimeError, match="table.index"):
        _select_indexes(_payload(), ["comments"])


def test_index_plan_token_is_order_independent_for_object_keys() -> None:
    first = [{"table": "comments", "index": "ix_comments_material_id"}]
    second = [{"index": "ix_comments_material_id", "table": "comments"}]
    assert _plan_token(first) == _plan_token(second)
