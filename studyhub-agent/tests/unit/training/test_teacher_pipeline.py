from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import training.teacher.providers as teacher_providers
from scripts.data.build_runtime_sft_v3_1 import _apply_teacher_self_review, _select_teacher_rows
from scripts.data.build_teacher_task_specs import _environment, _source_group_ids
from scripts.data.select_runtime_sft_v3 import public_benchmark_prompt_hashes
from scripts.data.verify_teacher_trajectories import accepted_record, verify_run
from training.rl.frozen_environment import FrozenTaskEnvironment
from training.teacher.hermes_controller import collect_trajectory
from training.teacher.providers import (
    CodexSparkProvider,
    LocalOpenAIProvider,
    ResponsesAPIProvider,
    _chat_action_output,
    _codex_event_audit,
    _parse_action,
    _visible_runtime_state,
    build_provider,
)

ROOT = Path(__file__).resolve().parents[3]


def _builder_row(
    tools: list[dict],
    calls: list[tuple[str, str, dict, dict]],
) -> dict:
    messages = []
    for call_id, name, arguments, observation in calls:
        messages.extend(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(observation),
                },
            ]
        )
    return {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": name,
                    "parameters": parameters,
                },
            }
            for name, parameters in tools
        ],
        "messages": messages,
    }


def _teacher_root(tmp_path: Path, task_id: str) -> Path:
    root = tmp_path / "teacher"
    for directory in ("environments", "fixtures", "verifiers", "raw_runs"):
        (root / directory).mkdir(parents=True)
    tool = {
        "name": "teacher_fixture_lookup",
        "description": "Read one deterministic fixture value.",
        "capability": "function_call",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    }
    (root / "environments" / f"{task_id}.json").write_text(
        json.dumps({"tools": [tool], "documents": []}),
        encoding="utf-8",
    )
    (root / "fixtures" / f"{task_id}.json").write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "name": "teacher_fixture_lookup",
                        "arguments": {"key": "answer"},
                        "result": {"value": "42"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def test_codex_event_audit_rejects_any_codex_tool_event() -> None:
    safe = "\n".join(
        [
            json.dumps({"type": "thread.started"}),
            json.dumps({"type": "item.completed", "item": {"type": "reasoning"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4}}),
        ]
    )
    unsafe = (
        safe
        + "\n"
        + json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "cat secret"}})
    )

    assert _codex_event_audit(safe)["zero_codex_tool_events"] is True
    audit = _codex_event_audit(unsafe)
    assert audit["zero_codex_tool_events"] is False
    assert audit["forbidden_item_types"] == ["command_execution"]


def test_provider_action_decodes_strict_schema_argument_string() -> None:
    action = _parse_action(
        json.dumps(
            {
                "type": "tool_call",
                "name": "knowledge_search",
                "arguments": json.dumps({"query": "通信原理", "limit": 3}),
                "content": "",
            }
        )
    )

    assert action["arguments"] == {"query": "通信原理", "limit": 3}


def test_provider_final_ignores_nonsemantic_arguments_field() -> None:
    action = _parse_action(
        json.dumps(
            {
                "type": "final",
                "name": "",
                "arguments": "",
                "content": "Supported final answer.",
            }
        )
    )

    assert action["arguments"] == {}


def test_chat_action_output_recovers_structured_compatibility_fields() -> None:
    tool_output, tool_mode = _chat_action_output(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "knowledge_search",
                                    "arguments": '{"query":"通信原理"}',
                                }
                            }
                        ],
                    }
                }
            ]
        }
    )
    reasoning_output, reasoning_mode = _chat_action_output(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": json.dumps(
                            {"type": "final", "name": "", "arguments": "{}", "content": "done"}
                        ),
                    }
                }
            ]
        }
    )

    assert json.loads(tool_output)["name"] == "knowledge_search"
    assert tool_mode == "tool_calls"
    assert json.loads(reasoning_output)["type"] == "final"
    assert reasoning_mode == "reasoning_json"


def test_visible_runtime_state_separates_discovery_from_grounded_evidence() -> None:
    task = {
        "max_steps": 6,
        "max_tool_calls": 5,
        "completion_contract": {
            "minimum_grounded_citations": 1,
            "minimum_successful_state_changes": 1,
        },
    }
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "web_search", "arguments": {}}}],
        },
        {
            "role": "tool",
            "name": "web_search",
            "content": json.dumps({"results": [{"source_id": "web:one", "url": "https://one"}]}),
        },
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "web_fetch", "arguments": {}}}],
        },
        {
            "role": "tool",
            "name": "web_fetch",
            "content": json.dumps({"content": {"source_id": "web:one", "text": "evidence"}}),
        },
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "study_plan_update", "arguments": {}}}],
        },
        {
            "role": "tool",
            "name": "study_plan_update",
            "content": json.dumps(
                {
                    "ok": True,
                    "content": {"ok": True, "postcondition": "study_plan_updated"},
                }
            ),
        },
    ]

    state = _visible_runtime_state(task, messages, turn=2)

    assert state["discovered_source_ids"] == ["web:one"]
    assert state["grounded_source_ids"] == ["web:one"]
    assert state["grounded_citation_deficit"] == 0
    assert state["remaining_tool_calls"] == 2
    assert state["final_evidence_ready"] is True
    assert state["successful_state_postconditions"] == ["study_plan_updated"]
    assert state["successful_state_change_deficit"] == 0
    assert state["final_state_ready"] is True
    assert state["final_ready"] is True


def test_teacher_builder_preserves_permission_denial_as_executable_route() -> None:
    source_id = "paid-source:203"
    row = _builder_row(
        [
            (
                "knowledge_read",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"source_id": {"type": "string"}},
                    "required": ["source_id"],
                },
            )
        ],
        [
            (
                "read-private",
                "knowledge_read",
                {"source_id": source_id},
                {"ok": False, "error": "permission_denied", "source_id": source_id},
            )
        ],
    )

    environment, fixture, expected_tools = _environment(row)

    assert environment["documents"] == []
    assert fixture["routes"] == [
        {
            "name": "knowledge_read",
            "arguments": {"source_id": source_id},
            "result": {"ok": False, "error": "permission_denied", "source_id": source_id},
        }
    ]
    assert expected_tools == ["knowledge_read"]
    runtime = FrozenTaskEnvironment(environment, fixture)
    result = json.loads(asyncio.run(runtime.execute("knowledge_read", {"source_id": source_id})))
    assert result["error"] == "permission_denied"
    assert runtime.trace.invalid_tool_calls == 0


def test_teacher_builder_preserves_web_fetch_route_and_records_evidence() -> None:
    url = "https://example.edu/current"
    source_id = "web:official-current"
    row = _builder_row(
        [
            (
                "web_search",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            (
                "web_fetch",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            ),
        ],
        [
            (
                "search-web",
                "web_search",
                {"query": "current policy"},
                {"results": [{"url": url, "title": "Official result"}]},
            ),
            (
                "fetch-web",
                "web_fetch",
                {"url": url},
                {"content": {"source_id": source_id, "text": "Current official evidence."}},
            ),
        ],
    )

    environment, fixture, expected_tools = _environment(row)

    assert [route["name"] for route in fixture["routes"]] == ["web_search", "web_fetch"]
    assert expected_tools == ["web_search", "web_fetch"]
    runtime = FrozenTaskEnvironment(environment, fixture)
    search = json.loads(asyncio.run(runtime.execute("web_search", {"query": "current policy"})))
    fetch = json.loads(asyncio.run(runtime.execute("web_fetch", {"url": url})))
    assert search["results"] == [{"url": url, "title": "Official result"}]
    assert fetch["fixture_match"] is True
    assert runtime.trace.read_source_ids == {source_id}


def test_teacher_builder_supplements_every_frozen_web_result_from_train_library() -> None:
    first_url = "https://example.edu/first"
    second_url = "https://example.edu/second"
    row = _builder_row(
        [
            (
                "web_search",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            (
                "web_fetch",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            ),
        ],
        [
            (
                "search-web",
                "web_search",
                {"query": "compare sources"},
                {
                    "results": [
                        {"url": first_url, "source_id": "web-material:1"},
                        {"url": second_url, "source_id": "web-material:2"},
                    ]
                },
            ),
            (
                "fetch-first",
                "web_fetch",
                {"url": first_url},
                {"source_id": "web-material:1", "text": "First evidence."},
            ),
        ],
    )
    row.update({"id": "web-row", "group_id": "studyhub-material:1"})
    library = {
        second_url: {
            "result": {"source_id": "web-material:2", "text": "Second evidence."},
            "source_group_id": "studyhub-material:2",
            "source_row_id": "web-row-two",
        }
    }

    environment, fixture, _expected_tools = _environment(row, web_fetch_library=library)

    fetch_routes = [route for route in fixture["routes"] if route["name"] == "web_fetch"]
    assert [route["arguments"]["url"] for route in fetch_routes] == [first_url, second_url]
    assert fetch_routes[1]["provenance"]["origin"] == "frozen_train_fetch_library"
    assert _source_group_ids(row, library) == ["studyhub-material:1", "studyhub-material:2"]
    runtime = FrozenTaskEnvironment(environment, fixture)
    result = json.loads(asyncio.run(runtime.execute("web_fetch", {"url": second_url})))
    assert result["fixture_match"] is True
    assert runtime.trace.read_source_ids == {"web-material:2"}


def test_fixture_route_accepts_declared_equivalent_state_text() -> None:
    environment = FrozenTaskEnvironment(
        {
            "tools": [
                {
                    "name": "study_plan_update",
                    "description": "Update a plan.",
                    "capability": "function_call",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string"},
                            "weekly_minutes": {"type": "integer"},
                            "resource_ids": {"type": "array", "items": {"type": "integer"}},
                        },
                        "required": ["topic", "weekly_minutes", "resource_ids"],
                    },
                }
            ],
            "documents": [],
        },
        {
            "routes": [
                {
                    "name": "study_plan_update",
                    "arguments": {"topic": "reference wording", "weekly_minutes": 90, "resource_ids": [1, 2]},
                    "argument_match": {"mode": "exact_except", "flexible_fields": ["topic"]},
                    "result": {"ok": True, "postcondition": "study_plan_updated"},
                }
            ]
        },
    )

    result = json.loads(
        asyncio.run(
            environment.execute(
                "study_plan_update",
                {"topic": "equivalent teacher wording", "weekly_minutes": 90, "resource_ids": [1, 2]},
            )
        )
    )

    assert result["ok"] is True
    assert result["fixture_match"] is True
    assert environment.trace.invalid_tool_calls == 0


def test_nested_fetch_observation_is_valid_grounded_citation() -> None:
    task = {
        "family": "web_fallback_conflict",
        "max_tool_calls": 3,
        "metadata": {"source_group_id": "web:one", "teacher_dataset": "studyhub_teacher_v2"},
    }
    run = {
        "status": "COMPLETED",
        "controller": {
            "hermes_registry_dispatch": True,
            "controller_errors": [],
            "environment_errors": [],
            "runtime_errors": [],
            "invalid_tool_calls": 0,
            "tool_calls": 1,
            "read_source_ids": [],
        },
        "provider_events": [],
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "web_fetch", "arguments": {"url": "https://one"}}}],
            },
            {
                "role": "tool",
                "name": "web_fetch",
                "content": json.dumps({"ok": True, "content": {"source_id": "web:one", "text": "supported fact"}}),
            },
            {"role": "assistant", "content": "supported fact [web:one]"},
        ],
        "final_answer": "supported fact [web:one]",
    }
    verifier = {
        "reference_final": "supported fact [web:one]",
        "allowed_citations": ["web:one"],
        "minimum_citations": 1,
        "expected_tool_names": ["web_fetch"],
        "required_tool_names": [],
        "minimum_tool_calls": 1,
        "benchmark_prompt_overlap": False,
    }

    failures, diagnostics = verify_run(run, task, verifier)

    assert failures == []
    assert diagnostics["grounded_citations"] == ["web:one"]


def test_teacher_provider_availability_never_confuses_cli_with_responses_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert ResponsesAPIProvider().availability()["available"] is False
    assert CodexSparkProvider(command="missing-studyhub-codex").availability()["available"] is False
    assert build_provider("local-best-of-n", model="fixture").native_tool_calling is True
    compatible = build_provider("authorized-openai-compatible", model="fixture")
    assert compatible.availability()["available"] is False


def test_local_teacher_bounds_action_tokens_and_disables_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_post(_url, body, _headers, _timeout):
        captured.update(body)
        return {
            "model": "default",
            "choices": [{"message": {"content": "done"}}],
        }

    monkeypatch.setattr(teacher_providers, "_post_json", fake_post)
    provider = LocalOpenAIProvider(
        model="default",
        base_url="http://127.0.0.1:30000/v1",
        chat_template_kwargs={"enable_thinking": False},
        native_tool_calling=True,
    )

    action, _event = provider.choose_action(
        {"max_steps": 2, "max_tool_calls": 1, "completion_contract": {}},
        [],
        [{"role": "user", "content": "answer"}],
        0,
    )

    assert action["type"] == "final"
    assert action["content"] == "done"
    assert captured["max_completion_tokens"] == 1024
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert "response_format" not in captured
    assert "tools" not in captured
    assert captured["messages"][0]["role"] == "system"
    assert "native function interface" in captured["messages"][0]["content"]


def test_local_teacher_exposes_studyhub_tools_through_native_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_post(_url, body, _headers, _timeout):
        captured.update(body)
        return {
            "model": "default",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "knowledge_search",
                                    "arguments": '{"query":"通信原理","limit":3}',
                                }
                            }
                        ],
                    },
                }
            ],
        }

    monkeypatch.setattr(teacher_providers, "_post_json", fake_post)
    provider = LocalOpenAIProvider(
        model="default",
        base_url="http://127.0.0.1:30000/v1",
        chat_template_kwargs={"enable_thinking": False},
        native_tool_calling=True,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "knowledge_search",
                "description": "Search public StudyHub sources.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]

    action, event = provider.choose_action(
        {"max_steps": 3, "max_tool_calls": 2, "completion_contract": {}},
        tools,
        [{"role": "system", "content": "StudyHub teacher."}, {"role": "user", "content": "检索通信原理"}],
        0,
    )

    assert action == {
        "type": "tool_call",
        "name": "knowledge_search",
        "arguments": {"query": "通信原理", "limit": 3},
        "content": "",
    }
    assert captured["tools"] == tools
    assert captured["tool_choice"] == "auto"
    assert captured["parallel_tool_calls"] is False
    assert "response_format" not in captured
    assert event["response_mode"] == "native_tool_calls"
    assert event["native_studyhub_tool_names"] == ["knowledge_search"]


def test_public_benchmark_hash_inventory_never_requires_sealed_task_files(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmarks/studyhub-agent-v2/development"
    benchmark.mkdir(parents=True)
    (benchmark / "tasks.jsonl").write_text(
        json.dumps({"task_id": "dev-1", "user_request": "public development task"}) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "public_files": {"development/tasks.jsonl": "fixture"},
        "counts": {
            "regression": 0,
            "development": 1,
            "calibration_challenge": 0,
            "sealed_a": 999,
            "sealed_b": 999,
        },
        "hidden_files": {
            "tasks/sealed_a.jsonl": "must-not-be-opened",
            "tasks/sealed_b.jsonl": "must-not-be-opened",
        },
    }

    hashes, count = public_benchmark_prompt_hashes(tmp_path, manifest)

    assert count == 1
    assert len(hashes) == 1


def test_actual_hermes_registry_executes_teacher_action_and_verifier_accepts(tmp_path: Path) -> None:
    checkout = ROOT / ".vendor/hermes-agent"
    if not checkout.is_dir():
        pytest.skip("pinned Hermes checkout is not installed")
    lock = json.loads((ROOT / "integrations/hermes/upstream.lock.json").read_text(encoding="utf-8"))
    task_id = "teacher-fixture"
    root = _teacher_root(tmp_path, task_id)
    task = {
        "schema_version": "studyhub.teacher-task.v1",
        "task_id": task_id,
        "family": "state_function",
        "user_request": "Look up the answer and report it.",
        "allowed_tools": ["teacher_fixture_lookup"],
        "max_steps": 3,
        "max_tool_calls": 2,
        "metadata": {
            "source_dataset": "fixture",
            "source_row_id": "fixture-row",
            "source_group_id": "fixture-group",
            "split": "train",
            "benchmark_overlap": False,
            "environment_id": task_id,
            "verifier_id": task_id,
        },
    }

    def choose_action(_task, _tools, _messages, turn):
        if turn == 0:
            return (
                {
                    "type": "tool_call",
                    "name": "teacher_fixture_lookup",
                    "arguments": {"key": "answer"},
                    "content": "",
                },
                {"interface": "fixture", "model": "fixture-teacher"},
            )
        return (
            {"type": "final", "name": "", "arguments": {}, "content": "The observed answer is 42."},
            {"interface": "fixture", "model": "fixture-teacher"},
        )

    run = collect_trajectory(
        task=task,
        root=root,
        hermes_checkout=checkout,
        hermes_commit=lock["commit"],
        choose_action=choose_action,
    )
    run.update(
        {
            "run_id": "fixture-run",
            "candidate_index": 0,
            "collection_mode": "teacher_rollout",
            "provider": {"interface": "fixture", "model": "fixture-teacher"},
            "collector_git_commit": "fixture-commit",
            "raw_run_path": "raw_runs/fixture-run.json",
        }
    )
    verifier = {
        "reference_final": "The observed answer is 42.",
        "expected_citations": [],
        "expected_tool_names": ["teacher_fixture_lookup"],
        "minimum_tool_calls": 1,
        "benchmark_prompt_overlap": False,
    }
    failures, diagnostics = verify_run(run, task, verifier)

    assert failures == []
    assert run["status"] == "COMPLETED"
    assert run["controller"]["hermes_registry_dispatch"] is True
    assert run["controller"]["tool_calls"] == 1
    record = accepted_record(run, task, verifier, diagnostics)
    assert record["quality_tier"] == "teacher_verified_complete"
    assert record["runtime_native"] is True


def test_controller_rejects_premature_final_and_records_repair(tmp_path: Path) -> None:
    checkout = ROOT / ".vendor/hermes-agent"
    if not checkout.is_dir():
        pytest.skip("pinned Hermes checkout is not installed")
    lock = json.loads((ROOT / "integrations/hermes/upstream.lock.json").read_text(encoding="utf-8"))
    task_id = "teacher-repair-fixture"
    root = _teacher_root(tmp_path, task_id)
    fixture_path = root / "fixtures" / f"{task_id}.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["routes"][0]["result"] = {
        "ok": True,
        "value": "42",
        "postcondition": "answer_recorded",
    }
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    task = {
        "schema_version": "studyhub.teacher-task.v2.1",
        "task_id": task_id,
        "family": "state_function",
        "user_request": "Record the answer before reporting completion.",
        "allowed_tools": ["teacher_fixture_lookup"],
        "completion_contract": {
            "minimum_grounded_citations": 0,
            "minimum_successful_state_changes": 1,
        },
        "max_steps": 3,
        "max_tool_calls": 2,
        "metadata": {"source_group_id": "repair-fixture"},
    }

    def choose_action(_task, _tools, _messages, turn):
        actions = [
            {"type": "final", "name": "", "arguments": {}, "content": "Recorded."},
            {
                "type": "tool_call",
                "name": "teacher_fixture_lookup",
                "arguments": {"key": "answer"},
                "content": "",
            },
            {"type": "final", "name": "", "arguments": {}, "content": "The answer 42 is recorded."},
        ]
        return actions[turn], {"interface": "fixture", "model": "fixture-teacher"}

    run = collect_trajectory(
        task=task,
        root=root,
        hermes_checkout=checkout,
        hermes_commit=lock["commit"],
        choose_action=choose_action,
    )

    assert run["status"] == "COMPLETED"
    assert run["final_answer"] == "The answer 42 is recorded."
    assert run["controller"]["policy_corrections"] == [
        {
            "turn": 0,
            "reason": "premature_final",
            "grounded_citation_deficit": 0,
            "successful_state_change_deficit": 1,
            "remaining_model_steps": 2,
            "remaining_tool_calls": 2,
        }
    ]
    assert any(
        message.get("role") == "user" and "runtime_feedback" in message.get("content", "")
        for message in run["messages"]
    )
    assert all(message.get("content") != "Recorded." for message in run["messages"])


def test_controller_repairs_public_tool_schema_failure_without_training_bad_action(tmp_path: Path) -> None:
    checkout = ROOT / ".vendor/hermes-agent"
    if not checkout.is_dir():
        pytest.skip("pinned Hermes checkout is not installed")
    lock = json.loads((ROOT / "integrations/hermes/upstream.lock.json").read_text(encoding="utf-8"))
    task_id = "teacher-schema-repair-fixture"
    root = _teacher_root(tmp_path, task_id)
    fixture_path = root / "fixtures" / f"{task_id}.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["routes"][0]["result"] = {
        "ok": True,
        "value": "42",
        "postcondition": "answer_recorded",
    }
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    task = {
        "schema_version": "studyhub.teacher-task.v2.1",
        "task_id": task_id,
        "family": "state_function",
        "user_request": "Record the answer before reporting completion.",
        "allowed_tools": ["teacher_fixture_lookup"],
        "completion_contract": {
            "minimum_grounded_citations": 0,
            "minimum_successful_state_changes": 1,
        },
        "max_steps": 4,
        "max_tool_calls": 2,
        "metadata": {"source_group_id": "schema-repair-fixture"},
    }

    def choose_action(_task, _tools, _messages, turn):
        actions = [
            {
                "type": "tool_call",
                "name": "teacher_fixture_lookup",
                "arguments": {"answer": "42"},
                "content": "",
            },
            {
                "type": "tool_call",
                "name": "teacher_fixture_lookup",
                "arguments": {"key": "answer"},
                "content": "",
            },
            {"type": "final", "name": "", "arguments": {}, "content": "The answer 42 is recorded."},
        ]
        return actions[turn], {"interface": "fixture", "model": "fixture-teacher"}

    run = collect_trajectory(
        task=task,
        root=root,
        hermes_checkout=checkout,
        hermes_commit=lock["commit"],
        choose_action=choose_action,
    )

    assert run["status"] == "COMPLETED"
    assert run["controller"]["controller_errors"] == []
    assert run["controller"]["tool_calls"] == 1
    assert len(run["controller"]["schema_validation_failures"]) == 1
    correction = run["controller"]["policy_corrections"][0]
    assert correction["reason"] == "tool_schema_validation_failed"
    assert correction["tool_name"] == "teacher_fixture_lookup"
    assert correction["argument_keys"] == ["answer"]
    validators = {row["validator"] for row in correction["validation_errors"]}
    assert validators == {"additionalProperties", "required"}
    assistant_calls = [
        call
        for message in run["messages"]
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    ]
    assert [call["function"]["arguments"] for call in assistant_calls] == [{"key": "answer"}]
    assert any(
        message.get("role") == "user" and "Tool action not accepted" in message.get("content", "")
        for message in run["messages"]
    )


def test_policy_corrected_teacher_trajectory_uses_repaired_quality_tier() -> None:
    run = {
        "run_id": "repaired-run",
        "candidate_index": 0,
        "collection_mode": "teacher_rollout",
        "provider": {"interface": "fixture", "model": "fixture-teacher"},
        "collector_git_commit": "fixture-commit",
        "raw_run_path": "raw_runs/repaired-run.json",
        "controller": {
            "hermes_commit": "fixture-hermes",
            "policy_corrections": [{"reason": "premature_final"}],
        },
        "tools": [],
        "messages": [
            {"role": "system", "content": "Answer safely."},
            {"role": "user", "content": "Answer."},
            {"role": "assistant", "content": "Supported answer."},
        ],
    }
    task = {
        "family": "direct_abstention",
        "metadata": {"source_group_id": "repaired-fixture", "teacher_dataset": "studyhub_teacher_v2_1"},
    }

    record = accepted_record(run, task, {}, {})

    assert record["quality_tier"] == "teacher_repaired_complete"
    assert record["teacher"]["policy_corrections"] == 1


def test_accepted_direct_teacher_trajectory_is_not_falsely_runtime_native() -> None:
    run = {
        "run_id": "direct-run",
        "candidate_index": 0,
        "collection_mode": "teacher_rollout",
        "provider": {"interface": "fixture", "model": "fixture-teacher"},
        "collector_git_commit": "fixture-commit",
        "raw_run_path": "raw_runs/direct-run.json",
        "controller": {"hermes_commit": "fixture-hermes"},
        "tools": [],
        "messages": [
            {"role": "system", "content": "Answer directly when no tool is needed."},
            {"role": "user", "content": "What is two plus two?"},
            {"role": "assistant", "content": "Four."},
        ],
    }
    task = {
        "family": "direct_abstention",
        "metadata": {
            "source_group_id": "direct-fixture",
            "source_group_ids": ["direct-fixture", "shared-secondary-fixture"],
        },
    }

    record = accepted_record(run, task, {}, {})

    assert record["quality_tier"] == "teacher_verified_complete"
    assert record["runtime_native"] is False
    assert record["source_group_ids"] == ["direct-fixture", "shared-secondary-fixture"]
    selected, drops = _select_teacher_rows(
        [record],
        base_content=set(),
        base_near=set(),
        public_benchmark_hashes=set(),
        max_rows_per_group=4,
    )
    assert [row["id"] for row in selected] == ["teacher-v1:direct-run"]
    assert drops == {}


def test_teacher_selection_caps_secondary_source_groups() -> None:
    def direct_record(run_id: str, group_id: str, question: str, answer: str) -> dict:
        run = {
            "run_id": run_id,
            "candidate_index": 0,
            "collection_mode": "teacher_rollout",
            "provider": {"interface": "fixture", "model": "fixture-teacher"},
            "collector_git_commit": "fixture-commit",
            "raw_run_path": f"raw_runs/{run_id}.json",
            "controller": {"hermes_commit": "fixture-hermes"},
            "tools": [],
            "messages": [
                {"role": "system", "content": "Answer directly."},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
        }
        task = {
            "family": "direct_abstention",
            "metadata": {
                "source_group_id": group_id,
                "source_group_ids": [group_id, "shared-secondary"],
            },
        }
        return accepted_record(run, task, {}, {})

    selected, drops = _select_teacher_rows(
        [
            direct_record("direct-one", "primary-one", "What is one plus one?", "Two."),
            direct_record("direct-two", "primary-two", "What is two plus two?", "Four."),
        ],
        base_content=set(),
        base_near=set(),
        public_benchmark_hashes=set(),
        max_rows_per_group=1,
    )

    assert len(selected) == 1
    assert drops == {"teacher_group_cap": 1}


def test_teacher_self_review_is_hash_bound_and_fail_closed(tmp_path: Path) -> None:
    accepted_path = tmp_path / "accepted.jsonl"
    accepted_path.write_text(
        json.dumps({"source_id": "include"}) + "\n" + json.dumps({"source_id": "exclude"}) + "\n",
        encoding="utf-8",
    )
    accepted_sha = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
    review_path = tmp_path / "self-review.json"
    review_path.write_text(
        json.dumps(
            {
                "status": "SELF_REVIEW",
                "population": {"accepted_jsonl_sha256": accepted_sha},
                "included_run_ids": ["include"],
            }
        ),
        encoding="utf-8",
    )

    selected, review = _apply_teacher_self_review(
        [{"source_id": "include"}, {"source_id": "exclude"}],
        accepted_path=accepted_path,
        review_path=review_path,
    )

    assert selected == [{"source_id": "include"}]
    assert review["status"] == "SELF_REVIEW"
    accepted_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="different accepted dataset"):
        _apply_teacher_self_review(
            [{"source_id": "include"}],
            accepted_path=accepted_path,
            review_path=review_path,
        )


def test_provider_failure_is_rejected_with_specific_taxonomy() -> None:
    task = {
        "family": "direct_abstention",
        "max_tool_calls": 1,
        "metadata": {"source_group_id": "fixture"},
    }
    run = {
        "status": "FAILED",
        "controller": {
            "hermes_registry_dispatch": True,
            "controller_errors": ["invalid_action_type"],
            "environment_errors": [],
            "runtime_errors": [],
            "invalid_tool_calls": 0,
            "tool_calls": 0,
        },
        "provider_events": [{"error_code": "codex_exec_failed"}],
        "messages": [],
        "final_answer": "",
    }
    failures, diagnostics = verify_run(
        run,
        task,
        {
            "reference_final": "fixture",
            "expected_citations": [],
            "expected_tool_names": [],
            "minimum_tool_calls": 0,
            "benchmark_prompt_overlap": False,
        },
    )

    assert "provider:codex_exec_failed" in failures
    assert diagnostics["provider_errors"] == ["codex_exec_failed"]
