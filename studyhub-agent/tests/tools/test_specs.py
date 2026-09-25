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


def test_select_tools_returns_canonical_order_regardless_of_request_order() -> None:
    # Canonical (TOOL_SPECS) order, not request order: render_text renders tools in list order, so
    # if select_tools preserved request order, two requests for the same tool set in a different
    # order would render different prompts while contract_hash's sorted-by-name component stayed
    # identical (same hash, different prompt).
    assert [spec.name for spec in select_tools(["web_extract", "materials_search"])] == [
        "materials_search",
        "web_extract",
    ]
    with pytest.raises(KeyError, match="web_fetch"):
        select_tools(["web_fetch"])


def test_select_tools_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="materials_search"):
        select_tools(["materials_search", "materials_search"])


def test_select_tools_can_filter_a_smaller_available_set() -> None:
    subset = tuple(spec for spec in TOOL_SPECS if spec.name != "materials_read")
    assert [spec.name for spec in select_tools(["web_extract"], subset)] == ["web_extract"]
    with pytest.raises(KeyError, match="materials_read"):
        select_tools(["materials_read"], subset)
