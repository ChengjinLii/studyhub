import pytest

from studyhub_agent.tools.specs import TOOL_SPECS, mcp_name_for, select_tools

EXPECTED = {
    "materials_search": "materials.search",
    "materials_get": "materials.get",
    "materials_recommend": "materials.recommend",
    "platform_policy": "platform.policy",
    "materials_read": None,
    "web_extract": None,
    "memory_get": None,
    "memory_update": None,
}


def test_tool_set_and_mcp_names() -> None:
    assert {spec.name: spec.mcp_name for spec in TOOL_SPECS} == EXPECTED
    assert all(mcp_name_for(name) == mcp for name, mcp in EXPECTED.items())


def test_snapshot_capability_is_explicit() -> None:
    assert all(spec.capability == "snapshot" for spec in TOOL_SPECS)


def test_select_tools_preserves_request_order_and_rejects_unknown() -> None:
    assert [spec.name for spec in select_tools(["web_extract", "materials_search"])] == [
        "web_extract",
        "materials_search",
    ]
    with pytest.raises(KeyError, match="web_fetch"):
        select_tools(["web_fetch"])
