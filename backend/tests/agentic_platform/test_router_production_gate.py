from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.services.agent_tool_loop_service import (
    AGENT_TOOL_LOOP_CONTINUE_INSTRUCTION,
)
from ml.agentic_platform.sft.evaluate_router import (
    DEFAULT_MAX_NEW_TOKENS,
    PRODUCTION_MAX_NEW_TOKENS,
    _decode_generated_output,
    _evaluation_messages,
    _install_set_submodule_compat,
    _resolve_max_new_tokens,
)
from ml.agentic_platform.sft.gate_router_production_diagnostic import (
    THRESHOLDS,
    gate_analysis,
    gate_diagnostic_root,
)


def _analysis(rate: float = 1.0) -> dict:
    metric = {"passed": 100, "total": 100, "rate": rate}
    return {
        "overall": {
            "json_valid": deepcopy(metric),
            "contract_valid": deepcopy(metric),
        },
        "subset_metrics": {
            "tool_required_mode": deepcopy(metric),
            "tool_required_name": deepcopy(metric),
            "force_final_compliant": deepcopy(metric),
            "explicit_page_number_preserved": deepcopy(metric),
            "material_ids_exact": deepcopy(metric),
            "direct_no_tool_compliant": deepcopy(metric),
            "synthesis_contract": deepcopy(metric),
            "policy_refusal_compliant": deepcopy(metric),
            "injection_safe_readonly": deepcopy(metric),
        },
        "safety": {
            "unsupported_tool_count": 0,
            "sensitive_output_count": 0,
        },
    }


def test_router_gate_requires_every_metric_and_safety() -> None:
    passing = _analysis()
    assert gate_analysis(passing)["passed"] is True

    failing_metric = _analysis()
    failing_metric["subset_metrics"]["tool_required_name"]["rate"] = THRESHOLDS["tool_required_name"] - 0.01
    result = gate_analysis(failing_metric)
    assert result["passed"] is False
    assert result["failures"] == {
        "tool_required_name": {
            "actual": THRESHOLDS["tool_required_name"] - 0.01,
            "required": THRESHOLDS["tool_required_name"],
        }
    }

    failing_safety = _analysis()
    failing_safety["safety"]["sensitive_output_count"] = 1
    result = gate_analysis(failing_safety)
    assert result["passed"] is False
    assert result["safety_passed"] is False


def test_router_gate_requires_both_runtime_paths(tmp_path: Path) -> None:
    for variant in ("raw", "normalized"):
        directory = tmp_path / variant
        directory.mkdir()
        analysis = _analysis()
        if variant == "normalized":
            analysis["subset_metrics"]["injection_safe_readonly"]["rate"] = 0.9
        (directory / "analysis.json").write_text(json.dumps(analysis))

    result = gate_diagnostic_root(root=tmp_path)
    assert result["passed"] is False
    assert result["variants"]["raw"]["passed"] is True
    assert result["variants"]["normalized"]["passed"] is False
    assert result["final_holdout_read"] is False
    assert (tmp_path / "gate.json").is_file()


def test_production_evaluation_replaces_stale_payload_instruction() -> None:
    record = {
        "messages": [
            {"role": "system", "content": "old system"},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "force_final": False,
                        "instruction": "old evaluation instruction",
                        "budget": {
                            "remaining_rounds": 2,
                            "remaining_tool_calls": 3,
                            "remaining_search_calls": 1,
                        },
                        "tool_observations": [],
                    }
                ),
            },
            {"role": "assistant", "content": "{}"},
        ]
    }

    raw = _evaluation_messages(
        record,
        normalize_routing_state=False,
        production_contract=True,
    )
    normalized = _evaluation_messages(
        record,
        normalize_routing_state=True,
        production_contract=True,
    )

    raw_payload = json.loads(raw[1]["content"])
    normalized_payload = json.loads(normalized[1]["content"])
    assert raw_payload["instruction"] == AGENT_TOOL_LOOP_CONTINUE_INSTRUCTION
    assert "routing_state" not in raw_payload
    assert normalized_payload["instruction"] == AGENT_TOOL_LOOP_CONTINUE_INSTRUCTION
    assert normalized_payload["routing_state"]["version"] == "studyhub.router.state.v1"


def test_nf4_module_replacement_compatibility_is_idempotent() -> None:
    class LegacyModule:
        def __init__(self) -> None:
            self.block = type("Block", (), {"projection": "old"})()

        def get_submodule(self, target: str):
            current = self
            for name in target.split(".") if target else ():
                current = getattr(current, name)
            return current

    assert _install_set_submodule_compat(LegacyModule) is True
    model = LegacyModule()
    model.set_submodule("block.projection", "nf4")
    assert model.block.projection == "nf4"
    assert _install_set_submodule_compat(LegacyModule) is False


def test_production_evaluation_defaults_to_runtime_output_budget() -> None:
    assert _resolve_max_new_tokens(None, production_contract=False) == (DEFAULT_MAX_NEW_TOKENS)
    assert _resolve_max_new_tokens(None, production_contract=True) == (PRODUCTION_MAX_NEW_TOKENS)
    assert _resolve_max_new_tokens(512, production_contract=True) == 512


def test_constrained_evaluation_preserves_raw_output_and_protects_page() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_user_query": "读取第4页证据",
                    "task_context": {},
                    "tool_observations": [
                        {
                            "tool": "search_materials",
                            "result": {"candidates": [{"id": 21}]},
                        }
                    ],
                    "budget": {
                        "remaining_rounds": 2,
                        "remaining_tool_calls": 3,
                        "remaining_search_calls": 0,
                        "remaining_candidate_slots": 5,
                    },
                    "force_final": False,
                }
            ),
        },
    ]
    generated, parsed, diagnostics = _decode_generated_output(
        "not-json",
        messages,
        constrained_decoding=True,
        deterministic_argument_protection=True,
    )

    assert json.loads(generated) == parsed
    assert parsed["actions"][0]["arguments"]["material_ids"] == [21]
    assert parsed["actions"][0]["arguments"]["page_numbers"] == [4]
    assert diagnostics["source_status"] == "fallback"
