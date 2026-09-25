from pathlib import Path

import pytest

from studyhub_agent.contracts.episode import EpisodeSpec, Principal, ToolCall
from studyhub_agent.environments.replay.environment import ReplayEnvironment
from studyhub_agent.environments.replay.snapshot import load_snapshot

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")


def _env(principal: Principal | None = None) -> ReplayEnvironment:
    env = ReplayEnvironment(SNAPSHOT)
    env.reset(
        EpisodeSpec(
            episode_id="ep",
            task_id="t",
            user_message="q",
            principal=principal or Principal(principal_id="u-1001"),
            tool_names=("materials_search",),
        )
    )
    return env


def _call(name: str, **arguments) -> ToolCall:
    return ToolCall(call_id="c1", name=name, arguments=arguments)


def test_read_requires_discovery_first() -> None:
    env = _env()
    blocked = env.execute(_call("materials_read", material_id=101))
    assert blocked.ok is False and blocked.error_code == "material_not_discovered"
    env.execute(_call("materials_search", query="高等数学 提纲"))
    read = env.execute(_call("materials_read", material_id=101, page=2))
    assert read.ok and "链式法则" in read.payload["text"]


def test_unlock_after_requires_reading_prerequisite() -> None:
    env = _env()
    env.execute(_call("materials_search", query="线性代数"))
    assert env.execute(_call("materials_read", material_id=104)).error_code == "material_locked"
    env.execute(_call("materials_read", material_id=103))
    assert env.execute(_call("materials_read", material_id=104)).ok


def test_owner_scoped_material_is_invisible_to_others() -> None:
    env = _env()
    result = env.execute(_call("materials_search", query="概率论 草稿"))
    assert all(item["material_id"] != 105 for item in result.payload["results"])
    owner_env = _env(Principal(principal_id="u-2002"))
    result = owner_env.execute(_call("materials_search", query="概率论 草稿"))
    assert any(item["material_id"] == 105 for item in result.payload["results"])


def test_search_filters_and_limit_bounds() -> None:
    env = _env()
    result = env.execute(_call("materials_search", query="笔记 习题", school="四川大学", limit=50))
    assert {item["school"] for item in result.payload["results"]} == {"四川大学"}
    assert len(result.payload["results"]) <= 10


def test_get_returns_metadata_without_preview_text() -> None:
    env = _env()
    env.execute(_call("materials_search", query="真题"))
    detail = env.execute(_call("materials_get", material_id=102))
    assert detail.ok and detail.payload["price_cents"] == 990 and detail.payload["preview_page_count"] == 1
    assert "preview_pages" not in detail.payload


def test_read_page_out_of_range() -> None:
    env = _env()
    env.execute(_call("materials_search", query="提纲"))
    assert env.execute(_call("materials_read", material_id=101, page=9)).error_code == "page_out_of_range"


def test_policy_and_web_extract() -> None:
    env = _env()
    assert "24 小时" in env.execute(_call("platform_policy", topic="refund")).payload["text"]
    pages = env.execute(
        _call("web_extract", urls=["https://www.example.edu.cn/exam-schedule", "https://unknown.example.com"])
    )
    assert pages.ok
    assert pages.payload["pages"][0]["text"].startswith("高等数学期末")
    assert pages.payload["pages"][1]["error"] == "not_in_snapshot"


def test_web_extract_blocks_unsafe_and_too_many_urls() -> None:
    env = _env()
    result = env.execute(_call("web_extract", urls=["http://127.0.0.1/admin"]))
    assert result.payload["pages"][0]["error"] == "unsafe_url"
    assert env.execute(_call("web_extract", urls=["https://a.cn"] * 4)).error_code == "too_many_urls"


def test_web_extract_handles_malformed_port_without_raising() -> None:
    env = _env()
    result = env.execute(_call("web_extract", urls=["http://example.com:abc/"]))
    assert result.ok
    assert result.payload["pages"][0]["error"] == "unsafe_url"


def test_memory_update_is_per_episode_and_rejects_personal_keys() -> None:
    env = _env()
    assert env.execute(_call("memory_get")).payload["memory"] == {"exam_date": "2027-01-08", "goal": "高数 85 分"}
    assert env.execute(_call("memory_update", key="email", value="a@b.com")).error_code == "forbidden_memory_key"
    assert env.execute(_call("memory_update", key="weak_topic", value="积分")).ok
    assert env.execute(_call("memory_get", keys=["weak_topic"])).payload["memory"] == {"weak_topic": "积分"}
    fresh = _env()
    assert "weak_topic" not in fresh.execute(_call("memory_get")).payload["memory"]
    assert "weak_topic" not in SNAPSHOT.memory["u-1001"]


def test_memory_update_rejects_non_ascii_keys() -> None:
    # A pre-Unicode-normalization bug used str.isalnum() to check the key, which is Unicode-aware
    # and treats Han characters as alphanumeric -- so a Chinese key would bypass the (English-only)
    # FORBIDDEN_KEYS set entirely. The key pattern must be ASCII-only, matching the tool's own
    # description ("小写英文和下划线" / lowercase English and underscore).
    env = _env()
    assert env.execute(_call("memory_update", key="电话", value="123")).error_code == "forbidden_memory_key"
    assert env.execute(_call("memory_update", key="Weak_Topic", value="x")).ok
    assert env.execute(_call("memory_update", key="9weak", value="x")).error_code == "forbidden_memory_key"


def test_trace_records_discovery_reads_and_calls() -> None:
    env = _env()
    env.execute(_call("materials_search", query="提纲"))
    env.execute(_call("materials_read", material_id=101))
    trace = env.trace()
    assert 101 in trace["discovered_material_ids"] and trace["read_material_ids"] == [101]
    assert trace["snapshot_digest"].startswith("sha256:")


def test_unknown_tool_is_an_error_observation() -> None:
    assert _env().execute(_call("web_fetch", url="x")).error_code == "unknown_tool"


def test_execute_before_reset_is_a_programming_error() -> None:
    with pytest.raises(RuntimeError, match="reset"):
        ReplayEnvironment(SNAPSHOT).execute(_call("memory_get"))
