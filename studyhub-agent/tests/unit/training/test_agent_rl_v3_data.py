from __future__ import annotations

import asyncio
import json
from collections import Counter

import pytest

from scripts.data.build_reward_v3_calibration import EXPECTED_CASES, build_cases
from training.rl.dataset_v3 import (
    PUBLIC_TASK_SCHEMA_VERSION,
    validate_hidden_verifier,
    validate_public_task,
)
from training.rl.environment_v3 import TrainingTaskEnvironmentV3
from training.rl.hermes_workflow_v3 import decode_public_task_row
from training.rl.reward_v3 import evaluate_reward_v3
from training.rl.task_factory_v3 import (
    CUSTOM_FACTORIES,
    convert_function_candidate,
    custom_web,
)


def test_public_task_rejects_nested_oracle_fields() -> None:
    task = {
        "schema_version": PUBLIC_TASK_SCHEMA_VERSION,
        "task_id": "t",
        "goal": "answer safely",
        "initial_state": {},
        "available_tools": [],
        "hard_constraints": {"nested": {"expected_answers": ["hidden"]}},
        "environment_id": "t",
        "budget_tier": "direct",
        "metadata": {"verifier_id": "t"},
    }

    with pytest.raises(ValueError, match="forbidden fields"):
        validate_public_task(task)


def test_hidden_verifier_rejects_gold_action_paths() -> None:
    verifier = {
        "schema_version": "studyhub.reward-verifier.v3",
        "verifier_id": "t",
        "task_id": "t",
        "family": "function_calling",
        "objective": {"mode": "state", "state_assertions": []},
        "debug": {"expected_calls": [{"name": "hidden"}]},
    }

    with pytest.raises(ValueError, match="forbidden fields"):
        validate_hidden_verifier(verifier)


def test_areal_transport_decodes_only_the_public_task() -> None:
    task = {
        "schema_version": PUBLIC_TASK_SCHEMA_VERSION,
        "task_id": "transport-task",
        "goal": "answer",
        "initial_state": {},
        "available_tools": [],
        "hard_constraints": {},
        "environment_id": "transport-task",
        "budget_tier": "direct",
        "metadata": {"verifier_id": "transport-task"},
    }
    decoded = decode_public_task_row({"task_id": "transport-task", "task_json": json.dumps(task)})

    assert decoded == task
    with pytest.raises(ValueError, match="transport ID mismatch"):
        decode_public_task_row({"task_id": "other", "task_json": json.dumps(task)})


@pytest.mark.parametrize("family", sorted(CUSTOM_FACTORIES))
def test_custom_factory_witnesses_execute_in_the_real_v3_environment(family: str, tmp_path) -> None:
    bundle = CUSTOM_FACTORIES[family](17)
    witness = bundle["witness"]

    async def run(actions, final_answer):
        runtime = TrainingTaskEnvironmentV3(bundle["environment"], root=tmp_path)
        for action in actions:
            await runtime.execute(action["name"], action["arguments"])
        return evaluate_reward_v3(
            final_answer=final_answer,
            trace=runtime.trace_dict(),
            final_state=runtime.state_snapshot(),
            verifier=bundle["verifier"],
        )

    canonical = asyncio.run(run(witness["actions"], witness["final_answer"]))
    assert canonical.strict_success is True
    if witness["alternative_actions"]:
        alternative = asyncio.run(run(witness["alternative_actions"], witness["alternative_final_answer"]))
        assert alternative.strict_success is True


def test_training_web_environment_requires_search_before_fetch(tmp_path) -> None:
    bundle = custom_web(23)
    runtime = TrainingTaskEnvironmentV3(bundle["environment"], root=tmp_path)
    fetch = bundle["witness"]["actions"][1]

    result = asyncio.run(runtime.execute(fetch["name"], fetch["arguments"]))

    assert "url_not_discovered" in result
    assert "url_not_discovered" in runtime.trace_dict()["policy_errors"]


def test_external_function_converter_normalizes_and_deduplicates_schema() -> None:
    malformed = {
        "source_dataset": "toolace",
        "source_id": "schema-smoke",
        "group_id": "schema-smoke",
        "user_request": "set count",
        "tools": [
            {
                "name": "set_count",
                "parameters": {
                    "type": "dict",
                    "properties": {"count": {"type": "int", "default": "bad-default"}},
                    "required": ["count"],
                    "additionalProperties": False,
                },
            },
            {"name": "set_count", "parameters": {"type": "object"}},
        ],
        "fixture": {
            "routes": [
                {
                    "name": "set_count",
                    "arguments": {"count": 1},
                    "result": {"ok": True},
                }
            ]
        },
        "verifier": {
            "expected_calls": [{"name": "set_count", "arguments": {"count": 1}}],
            "expected_answers": ["done"],
        },
    }

    bundle = convert_function_candidate(malformed, "function_calling")
    schemas = bundle["environment"]["tool_schemas"]

    assert len(schemas) == 1
    assert schemas[0]["parameters"]["type"] == "object"
    assert schemas[0]["parameters"]["properties"]["count"]["type"] == "integer"
    assert "default" not in schemas[0]["parameters"]["properties"]["count"]


def test_reward_calibration_builder_creates_exact_balanced_contract() -> None:
    tasks = []
    witnesses = {}
    for family_index, family in enumerate(sorted(CUSTOM_FACTORIES)):
        for index in range(20):
            task_id = f"{family}-{index}"
            tasks.append(
                {
                    "task_id": task_id,
                    "metadata": {
                        "family": family,
                        "source_group_id": f"group-{family_index}-{index}",
                    },
                }
            )
            witnesses[task_id] = {"alternative_actions": [{"name": "noop"}]}

    cases = build_cases(tasks, witnesses, seed=6209)

    assert len(cases) == EXPECTED_CASES
    assert Counter(row["case_type"] for row in cases) == {
        "normal": 160,
        "boundary": 160,
        "adversarial": 160,
        "reward_hacking": 160,
        "alternative_valid_path": 160,
    }
