import json

import pytest

from studyhub_agent.contracts.tools import ToolSpec, ToolSpecError


def _params(**properties):
    return {"type": "object", "properties": properties, "required": [], "additionalProperties": False}


def test_valid_spec_renders_openai_shape() -> None:
    spec = ToolSpec(
        name="materials_get",
        version="1.0",
        description="读取资料详情",
        parameters=_params(material_id={"type": "integer", "description": "资料 ID"}),
        mcp_name="materials.get",
    )
    assert spec.to_openai() == {
        "type": "function",
        "function": {"name": "materials_get", "description": "读取资料详情", "parameters": spec.parameters},
    }


@pytest.mark.parametrize(
    ("name", "parameters", "message"),
    [
        ("Bad-Name", _params(), "name"),
        ("ok_name", {"type": "array"}, "object"),
        ("ok_name", _params(x={"type": "int", "description": "d"}), "type"),
        ("ok_name", _params(x={"type": "string"}), "description"),
        ("ok_name", _params(x={"type": "string", "description": "d", "enum": [str(i) for i in range(40)]}), "enum"),
        ("ok_name", {**_params(x={"type": "string", "description": "d"}), "required": ["y"]}, "required"),
        ("ok_name", {**_params(), "additionalProperties": True}, "additionalProperties"),
        ("ok_name", _params(x={"type": "array", "description": "d"}), "items"),
    ],
)
def test_lint_rejects_invalid_specs(name, parameters, message) -> None:
    with pytest.raises(ToolSpecError, match=message):
        ToolSpec(name=name, version="1.0", description="desc", parameters=parameters)


def test_lint_rejects_bad_version_and_empty_description() -> None:
    with pytest.raises(ToolSpecError, match="version"):
        ToolSpec(name="ok", version="v1", description="desc", parameters=_params())
    with pytest.raises(ToolSpecError, match="description"):
        ToolSpec(name="ok", version="1.0", description=" ", parameters=_params())


def test_canonical_form_is_order_sensitive() -> None:
    # canonical() must hash exactly what the chat template renders (insertion order of
    # `properties`), not an alphabetically-resorted copy — otherwise two schemas that render
    # different prompts (and different SFT targets) could hash identically.
    params_a = _params(x={"type": "string", "description": "d"}, y={"type": "string", "description": "d"})
    params_b = _params(y={"type": "string", "description": "d"}, x={"type": "string", "description": "d"})
    a = ToolSpec(name="t", version="1.0", description="d", parameters=params_a)
    b = ToolSpec(name="t", version="1.0", description="d", parameters=params_b)
    # Plain dict `==` is order-insensitive, so compare the serialized form (what actually gets
    # hashed) as well as the key order directly.
    assert json.dumps(a.canonical()) != json.dumps(b.canonical())
    assert list(a.canonical()["parameters"]["properties"]) == ["x", "y"]
    assert list(b.canonical()["parameters"]["properties"]) == ["y", "x"]


def test_to_openai_returns_a_copy_callers_cannot_mutate() -> None:
    spec = ToolSpec(
        name="materials_get",
        version="1.0",
        description="读取资料详情",
        parameters=_params(material_id={"type": "integer", "description": "资料 ID"}),
    )
    payload = spec.to_openai()
    payload["function"]["parameters"]["properties"]["material_id"]["type"] = "string"
    assert spec.parameters["properties"]["material_id"]["type"] == "integer"
