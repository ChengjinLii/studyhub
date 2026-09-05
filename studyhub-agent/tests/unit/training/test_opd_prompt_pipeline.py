import json

from scripts.data.build_opd_prompt_pool_v1 import (
    stratified_probe,
    validate_candidate,
    validate_environment,
)
from scripts.data.package_opd_prompt_pool_runtime import package_pool
from scripts.data.select_opd_training_pool_v1 import (
    family_scores,
    reserve_validation,
    task_priority,
    verifier_map,
)
from scripts.train.run_opd_policy_probe import aggregate


def task(task_id: str, *, family: str = "rag_and_multihop", tools: list[str] | None = None) -> dict:
    return {
        "schema_version": "studyhub.agent-rl-task.v3",
        "task_id": task_id,
        "goal": f"Find supported evidence for {task_id}.",
        "initial_state": {},
        "available_tools": tools or ["knowledge_search", "knowledge_read"],
        "hard_constraints": {
            "hidden_oracle_access": False,
            "respect_acl": True,
            "no_cross_user_memory": True,
            "citations_must_be_observed": True,
            "max_tool_calls": 4,
        },
        "environment_id": task_id,
        "budget_tier": "short",
        "metadata": {
            "family": family,
            "source_dataset": "unit",
            "source_group_id": f"group-{task_id}",
            "split": "train",
            "verifier_id": task_id,
            "oracle_fields_exposed": False,
        },
    }


def verifier(task_id: str, *, family: str = "rag_and_multihop") -> dict:
    return {
        "schema_version": "studyhub.reward-verifier.v3",
        "verifier_id": task_id,
        "task_id": task_id,
        "family": family,
        "objective": {"mode": "facts", "acceptable_answers": [["supported"]]},
        "claims": [],
        "semantic_rubric": {"requirements": []},
        "process": {},
        "hard_constraints": {"max_tool_calls": 4},
        "thresholds": {"objective": 0.99, "grounding": 0.99, "semantic": 0.75},
    }


def environment(task_id: str, tools: list[str]) -> dict:
    return {
        "schema_version": "studyhub.rl-environment.v3",
        "task_id": task_id,
        "environment_kind": "replay",
        "available_tools": tools,
    }


def test_candidate_rejects_redundant_web_alias() -> None:
    row = task("legacy-web", family="web", tools=["web_search", "web_fetch"])
    failures = validate_candidate(
        row,
        verifier("legacy-web", family="web"),
        blocked_task_ids=set(),
        blocked_groups=set(),
        blocked_prompt_hashes=set(),
        blocked_prompt_terms_by_size={},
    )

    assert "legacy_redundant_tool" in failures


def test_environment_requires_exact_task_tool_surface() -> None:
    row = task("tool-contract")
    failures = validate_environment(
        row,
        verifier("tool-contract"),
        environment("tool-contract", ["knowledge_search"]),
    )

    assert failures == ["tool_surface_mismatch"]


def test_probe_is_deterministic_and_family_stratified() -> None:
    rows = [task(f"rag-{index}") for index in range(8)] + [
        task(f"direct-{index}", family="direct_answer_and_abstention", tools=[]) for index in range(2)
    ]

    first = stratified_probe(rows, 5, 7)
    second = stratified_probe(rows, 5, 7)

    assert [row["task_id"] for row in first] == [row["task_id"] for row in second]
    assert {row["metadata"]["family"] for row in first} == {
        "rag_and_multihop",
        "direct_answer_and_abstention",
    }


def test_probe_aggregate_separates_infra() -> None:
    rows = [
        {
            "family": "rag_and_multihop",
            "status": "SCORED",
            "strict_success": True,
            "diagnostic_score": 0.8,
            "tool_validity": 1.0,
        },
        {
            "family": "rag_and_multihop",
            "status": "INFRA_EXCLUDED",
            "strict_success": False,
            "diagnostic_score": 0.0,
            "tool_validity": 0.0,
        },
    ]

    result = aggregate(rows)

    assert result["tasks"] == 2
    assert result["scored"] == 1
    assert result["infra_excluded"] == 1
    assert result["strict_success_rate"] == 1.0


def test_teacher_only_task_has_priority_over_unevaluated_family_fill() -> None:
    teacher = {
        "observed": {
            "family": "rag_and_multihop",
            "strict_success": True,
            "diagnostic_score": 0.9,
        }
    }
    student = {
        "observed": {
            "family": "rag_and_multihop",
            "strict_success": False,
            "diagnostic_score": 0.2,
        }
    }
    scores = family_scores(teacher, student)
    observed = {
        "task_id": "observed",
        "metadata": {"family": "rag_and_multihop"},
    }
    unseen = {
        "task_id": "unseen",
        "metadata": {"family": "rag_and_multihop"},
    }
    assert task_priority(
        observed,
        teacher=teacher,
        student=student,
        family=scores,
        seed=1,
    ) < task_priority(
        unseen,
        teacher=teacher,
        student=student,
        family=scores,
        seed=1,
    )


def test_validation_reserved_before_ranking_is_balanced_and_excludes_probe_groups() -> None:
    rows = [
        task(f"{family}-{index}", family=family)
        for family in ("memory", "function_calling", "recovery_and_acl")
        for index in range(12)
    ]
    duplicate_group = task("probe-sibling", family="memory")
    duplicate_group["metadata"]["source_group_id"] = "group-memory-0"
    rows.append(duplicate_group)
    first = reserve_validation(rows, {"memory-0"}, 9, 7)
    assert first == reserve_validation(list(reversed(rows)), {"memory-0"}, 9, 7)
    assert {row["metadata"]["family"] for row in first} == {"memory", "function_calling", "recovery_and_acl"}
    assert len({row["metadata"]["source_group_id"] for row in first}) == 9
    assert "group-memory-0" not in {row["metadata"]["source_group_id"] for row in first}


def test_verifier_map_reads_jsonl_and_rejects_duplicate_tasks(tmp_path) -> None:
    path = tmp_path / "train.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"task_id":"task-a","verifier_id":"verifier-a"}',
                '{"task_id":"task-b","verifier_id":"verifier-b"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert sorted(verifier_map(path)) == ["task-a", "task-b"]

    path.write_text('{"task_id":"task-a"}\n{"task_id":"task-a"}\n', encoding="utf-8")
    try:
        verifier_map(path)
    except RuntimeError as error:
        assert "duplicate verifier task IDs" in str(error)
    else:
        raise AssertionError("duplicate verifier task IDs were accepted")


def test_runtime_packaging_materializes_split_verifier_jsonl(tmp_path) -> None:
    root = tmp_path / "pool"
    (root / "tasks").mkdir(parents=True)
    (root / "verifiers").mkdir()
    (root / "environments").mkdir()
    train = task("train-task")
    validation = task("validation-task")
    (root / "tasks/train.jsonl").write_text(json.dumps(train) + "\n", encoding="utf-8")
    (root / "tasks/validation.jsonl").write_text(json.dumps(validation) + "\n", encoding="utf-8")
    for row in (train, validation):
        task_id = row["task_id"]
        (root / f"verifiers/{task_id}.json").write_text(json.dumps(verifier(task_id)), encoding="utf-8")
        (root / f"environments/{task_id}.json").write_text(
            json.dumps(environment(task_id, row["available_tools"])),
            encoding="utf-8",
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "status": "PASS_TEACHER_ALIGNED_SELECTION",
                "train_rows": 1,
                "validation_rows": 1,
                "lineage": {},
            }
        ),
        encoding="utf-8",
    )

    first = package_pool(root)
    second = package_pool(root)

    assert first["status"] == "PASS_OPD_RUNTIME_PACKAGING"
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert len((root / "verifiers/train.jsonl").read_text().splitlines()) == 1
    assert len((root / "verifiers/validation.jsonl").read_text().splitlines()) == 1
