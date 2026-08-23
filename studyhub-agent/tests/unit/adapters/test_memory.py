import json

import pytest

from studyhub_agent.adapters.collective_memory import FixtureCollectiveMemoryReader
from studyhub_agent.adapters.personal_memory import HermesPersonalMemoryBridge


def test_personal_memory_crud_is_namespace_isolated(personal_memory) -> None:
    first = personal_memory.add("prod:user-a", "偏好按题型刷真题")
    personal_memory.add("prod:user-b", "每天学习三小时")

    assert [record.memory_id for record in personal_memory.search("prod:user-a", "真题", limit=5)] == [first.memory_id]
    assert personal_memory.search("prod:user-b", "真题", limit=5) == []
    assert personal_memory.update("prod:user-b", first.memory_id, "越权修改") is None
    assert personal_memory.delete("prod:user-b", first.memory_id) is False
    assert personal_memory.reset_namespace("prod:user-a") == 1


def test_hermes_memory_bridge_matches_upstream_lifecycle(personal_memory) -> None:
    personal_memory.add("eval:case-a:7", "每天复习两小时")
    bridge = HermesPersonalMemoryBridge(personal_memory, "eval:case-a:7")
    bridge.initialize("session-1", platform="test")

    assert bridge.is_available() is True
    assert "两小时" in bridge.prefetch("复习")
    schema = bridge.get_tool_schemas()[0]
    assert schema["name"] == "personal_memory_search"
    payload = json.loads(bridge.handle_tool_call("personal_memory_search", {"query": "复习", "limit": 2}))
    assert payload["memories"][0]["namespace"] == "eval:case-a:7"
    bridge.sync_turn("question", "answer")
    bridge.on_session_end([])
    bridge.shutdown()


def test_collective_memory_is_read_only_and_contains_no_user_data(collective_memory) -> None:
    results = collective_memory.search("两周 冲刺", course="通信原理", limit=3)

    assert len(results) == 1
    assert results[0].support_users == 30
    assert not hasattr(collective_memory, "add")


def test_collective_fixture_rejects_user_level_fields(tmp_path) -> None:
    fixture = tmp_path / "invalid.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "memory_id": "collective:test:1",
                    "course": "test",
                    "scenario": "test",
                    "pattern": "test",
                    "support_users": 2,
                    "support_episodes": 2,
                    "confidence": 0.5,
                    "email": "private@example.com",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        FixtureCollectiveMemoryReader.from_json(fixture)
