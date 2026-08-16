from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from ml.agentic_platform.sft.build_grounded_tutor_9b_v1 import DEFAULT_HOLDOUT
from ml.agentic_platform.sft.controlled_v2.ablation import attribution_groups
from ml.agentic_platform.sft.controlled_v2.configs import generate_configs
from ml.agentic_platform.sft.controlled_v2.completion_audit import (
    _experiment_evidence,
    _sealed_requirement,
)
from ml.agentic_platform.sft.controlled_v2.contract import (
    CONTRACT_VERSION,
    ControlledPaths,
    ExperimentSpec,
    contract_payload,
    initial_experiments,
    lora_rank_experiments,
    router_epoch_experiments,
    router_lora_target_experiment,
)
from ml.agentic_platform.sft.controlled_v2.context_study import (
    _completed_evaluation,
)
from ml.agentic_platform.sft.controlled_v2.evaluate import (
    _report_progress,
    _tutor_scores,
)
from ml.agentic_platform.sft.controlled_v2.gates import gate_router, gate_tutor
from ml.agentic_platform.sft.controlled_v2.finalize import (
    ROUTER_LEGACY_FAMILIES,
    _subset_rate,
    _winner_specs,
)
from ml.agentic_platform.sft.controlled_v2.prepare import (
    ROUTER_CHALLENGE_COUNT,
    TUTOR_CHALLENGE_COUNT,
    _material_ids,
    _router_challenge,
    _tutor_pressure_dataset,
)
from ml.agentic_platform.sft.controlled_v2.report import (
    _context_table,
    _seed_panel,
    build_report,
)
from ml.agentic_platform.sft.controlled_v2.review import (
    build_challenge_review,
    build_final_review,
    validate_challenge_review,
    validate_final_review,
)
from ml.agentic_platform.sft.controlled_v2.result_index import (
    _telemetry_path as result_index_telemetry_path,
)
from ml.agentic_platform.sft.controlled_v2.registry import record_selection
from ml.agentic_platform.sft.controlled_v2.select import (
    _router_epoch_candidates,
    rank_candidates,
)
from ml.agentic_platform.sft.controlled_v2.sealed import _write_exclusive_json
from ml.agentic_platform.sft.controlled_v2.statistics import (
    mcnemar_exact,
    paired_bootstrap,
    summarize_seeds,
)
from ml.agentic_platform.sft.controlled_v2.variants import (
    ROUTER_FIXED_OPTIMIZER_STEPS,
    router_data_experiments,
    tutor_mix_experiments,
)
from ml.agentic_platform.sft.spec import load_jsonl, sha256_file


pytestmark = pytest.mark.private_sft_corpus


def test_contract_preregisters_shared_runtime_and_initial_arms() -> None:
    payload = contract_payload()
    arms = initial_experiments()

    assert payload["schema_version"] == CONTRACT_VERSION
    assert payload["runtime"]["train_on_prompt"] is False
    assert payload["runtime"]["effective_batch_size"] == 8
    assert payload["selection"]["paired_bootstrap_resamples"] == 10_000
    assert len(arms) == 4
    assert {arm.task for arm in arms} == {"router", "tutor"}
    assert all(arm.parent_experiment_id is None for arm in arms)


def test_generated_configs_start_from_raw_base(tmp_path: Path) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    spec = ExperimentSpec(
        experiment_id="r-opt-test",
        task="router",
        seed=7703,
        learning_rate=2e-5,
        epochs=1.0,
        lora_rank=16,
    )
    [result] = generate_configs([spec], paths=paths)
    config = yaml.safe_load(Path(result["config_path"]).read_text(encoding="utf-8"))

    assert config["model_name_or_path"].endswith("models/P0/Qwen3.5-2B")
    assert "adapter_name_or_path" not in config
    assert config["train_on_prompt"] is False
    assert config["lora_rank"] == 16
    assert config["gradient_accumulation_steps"] * config["per_device_train_batch_size"] == 8
    assert config["output_dir"].endswith("router/r-opt-test/7703")


def test_reference_telemetry_uses_original_sft_run_directory(
    tmp_path: Path,
) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    reference = ExperimentSpec(
        experiment_id="r-base-engineering-sft-v1-7",
        task="router",
        seed=7703,
        learning_rate=5e-6,
        epochs=1.0,
        lora_rank=16,
        reference_adapter_path=str(tmp_path / "reference-adapter"),
    )

    telemetry = result_index_telemetry_path(paths, reference)
    evidence = _experiment_evidence(paths, [reference])

    assert telemetry == (
        tmp_path
        / "training_artifacts/studyhub_agent_sft/run_telemetry"
        / "router_2b_v1_7_seed_7703/run_summary.json"
    )
    assert evidence["all_telemetry_exists"] is False


def test_router_challenge_is_balanced_and_query_disjoint() -> None:
    paths = ControlledPaths()
    source = load_jsonl(paths.router_source)
    challenge = _router_challenge(source)
    source_queries = {next(item for item in row["messages"] if item["role"] == "user")["content"] for row in source}

    assert len(challenge) == ROUTER_CHALLENGE_COUNT
    assert len({row["example_id"] for row in challenge}) == ROUTER_CHALLENGE_COUNT
    assert all(row["training_eligible"] is False for row in challenge)
    assert all(next(item for item in row["messages"] if item["role"] == "user")["content"] not in source_queries for row in challenge)


def test_tutor_challenge_has_six_balanced_material_isolated_families() -> None:
    paths = ControlledPaths()
    train = load_jsonl(paths.tutor_source)
    holdout = load_jsonl(DEFAULT_HOLDOUT)
    challenge = _tutor_pressure_dataset(holdout, items_per_family=40, split="validation")

    assert len(challenge) == TUTOR_CHALLENGE_COUNT
    assert _material_ids(train).isdisjoint(_material_ids(challenge))
    assert all(row["training_eligible"] is False for row in challenge)
    assert {row["task_family"] for row in challenge} == {
        "normal_answer_v2",
        "no_answer_v2",
        "distractor_v2",
        "conflict_v2",
        "partial_evidence_v2",
        "citation_counterfactual_v2",
    }


def test_paired_statistics_detect_candidate_improvement() -> None:
    baseline = [False, False, True, False, True, False, False, True]
    candidate = [True, True, True, False, True, True, False, True]
    bootstrap = paired_bootstrap(baseline, candidate, resamples=1_000, seed=7)
    mcnemar = mcnemar_exact(baseline, candidate)

    assert bootstrap["observed_delta"] == 0.375
    assert bootstrap["ci95"][1] > 0
    assert mcnemar["baseline_fail_candidate_pass"] == 3
    assert mcnemar["baseline_pass_candidate_fail"] == 0


def test_seed_summary_reports_variance_and_median_seed() -> None:
    summaries = [{"seed": seed, "metrics": {"score": {"rate": rate}}} for seed, rate in ((3407, 0.94), (7703, 0.96), (9109, 0.95))]
    result = summarize_seeds(summaries, metric="score", expected_seeds=(3407, 7703, 9109))

    assert result["mean"] == 0.95
    assert result["std"] == 0.01
    assert result["median_seed"] == 9109


def _metric(rate: float) -> dict[str, float | int]:
    return {"passed": round(rate * 100), "total": 100, "rate": rate}


def test_router_and_tutor_gates_apply_hard_boundaries() -> None:
    router = {
        "metrics": {
            key: _metric(1.0)
            for key in (
                "json_valid",
                "contract_valid",
                "tool_required_name",
                "mode_correct",
                "material_id_exact",
                "page_exact",
                "force_final_compliant",
                "injection_permission_safety",
                "strict_route_pass",
            )
        },
        "task_family_floor": 0.95,
    }
    tutor = {
        "metrics": {
            key: _metric(1.0)
            for key in (
                "strict_grounded_pass",
                "citation_exact",
                "citation_entailment",
                "no_answer_abstention",
                "conflict_disclosure",
                "unsupported_claim_free",
                "no_tool_actions",
                "sensitive_output_free",
            )
        }
    }

    assert gate_router(router, {"projection_correction_rate": 0.01})["passed"] is True
    assert gate_tutor(tutor)["passed"] is True
    tutor["metrics"]["no_tool_actions"] = _metric(0.99)
    failed = gate_tutor(tutor)
    assert failed["passed"] is False
    assert "no_tool_actions" in failed["failures"]

    router["metrics"]["contract_valid"] = _metric(0.97)
    quality_failure = gate_router(router, {"projection_correction_rate": 0.01})
    assert quality_failure["passed"] is False
    assert quality_failure["screening_eligible"] is True

    router["metrics"]["injection_permission_safety"] = _metric(0.99)
    safety_failure = gate_router(router, {"projection_correction_rate": 0.01})
    assert safety_failure["screening_eligible"] is False


def test_winner_specs_require_same_configuration_for_all_seeds(
    tmp_path: Path,
) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    paths.contract_dir.mkdir(parents=True)
    specs = [
        ExperimentSpec(
            experiment_id="winner",
            task="router",
            seed=seed,
            learning_rate=2e-5 if seed != 9109 else 5e-5,
            epochs=1.0,
            lora_rank=16,
        ).to_dict()
        for seed in (3407, 7703, 9109)
    ]
    paths.experiment_registry.write_text(
        json.dumps(
            {
                "initial_experiments": [],
                "reference_experiments": [],
                "dynamic_experiments": specs,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="changes controlled fields"):
        _winner_specs(paths=paths, task="router", experiment_id="winner")


def test_subset_rate_uses_only_preregistered_legacy_families(
    tmp_path: Path,
) -> None:
    predictions = tmp_path / "predictions.jsonl"
    rows = [
        {
            "example_id": "a",
            "task_family": "search_replay_v1_7",
            "scores": {"strict_route_pass": True},
        },
        {
            "example_id": "b",
            "task_family": "search_replay_v1_7",
            "scores": {"strict_route_pass": False},
        },
        {
            "example_id": "c",
            "task_family": "new_family",
            "scores": {"strict_route_pass": True},
        },
    ]
    predictions.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    assert (
        _subset_rate(
            predictions,
            metric="strict_route_pass",
            families=set(ROUTER_LEGACY_FAMILIES),
        )
        == 0.5
    )


def test_router_epoch_stage_allows_one_safe_learning_rate() -> None:
    result = router_epoch_experiments((2e-5,))

    assert len(result) == 2
    assert {item.epochs for item in result} == {0.5, 2.0}


def test_router_epoch_candidates_exclude_learning_rates_not_admitted() -> None:
    initial = [
        ExperimentSpec(
            experiment_id=f"lr-{rate}",
            task="router",
            seed=7703,
            learning_rate=rate,
            epochs=1.0,
            lora_rank=16,
            stage="r-opt-lr",
        )
        for rate in (2e-5, 5e-5, 8e-5)
    ]
    epoch = list(router_epoch_experiments((2e-5, 5e-5)))

    candidates = _router_epoch_candidates([*initial, *epoch])

    assert {item.learning_rate for item in candidates} == {2e-5, 5e-5}
    assert all(item.experiment_id != "lr-8e-05" for item in candidates)


def test_candidate_regression_is_a_hard_selection_constraint(tmp_path: Path) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    paths.contract_dir.mkdir(parents=True)
    reference = ExperimentSpec(
        experiment_id="r-base-engineering-sft-v1-7",
        task="router",
        seed=7703,
        learning_rate=5e-6,
        epochs=1.0,
        lora_rank=16,
        reference_adapter_path="/tmp/reference",
    )
    candidate = ExperimentSpec(
        experiment_id="candidate",
        task="router",
        seed=7703,
        learning_rate=2e-5,
        epochs=1.0,
        lora_rank=16,
    )
    paths.experiment_registry.write_text(
        json.dumps(
            {
                "initial_experiments": [candidate.to_dict()],
                "reference_experiments": [reference.to_dict()],
                "dynamic_experiments": [],
            }
        ),
        encoding="utf-8",
    )

    def write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def write_predictions(path: Path, values: list[bool]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps(
                    {
                        "example_id": f"row-{index}",
                        "task_family": "search_replay_v1_7",
                        "scores": {"strict_route_pass": value},
                    }
                )
                + "\n"
                for index, value in enumerate(values)
            ),
            encoding="utf-8",
        )

    reference_predictions = (
        paths.evaluation_root
        / reference.experiment_id
        / str(reference.seed)
        / "sft/raw/predictions.jsonl"
    )
    candidate_root = (
        paths.evaluation_root
        / candidate.experiment_id
        / str(candidate.seed)
    )
    write_predictions(reference_predictions, [True, True])
    write_predictions(candidate_root / "sft/raw/predictions.jsonl", [True, False])
    write_json(candidate_root / "sft/raw/summary.json", {"task_family_floor": 0.5})
    write_json(
        candidate_root / "gate.json",
        {
            "screening_eligible": True,
            "passed": False,
            "selection_score": 0.5,
            "failures": {},
        },
    )
    write_json(
        paths.training_root
        / "run_telemetry/candidate-seed7703/run_summary.json",
        {
            "duration_seconds": 10,
            "gpu": {"peak_memory_mib": 100, "exclusive_gpu_observed": True},
        },
    )

    [ranked] = rank_candidates([candidate], paths=paths)

    assert ranked["safety_eligible"] is True
    assert ranked["regression"]["regression_pp"] == 50.0
    assert ranked["screening_eligible"] is False


def test_selection_record_is_idempotent_and_rejects_changed_evidence(
    tmp_path: Path,
) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    paths.contract_dir.mkdir(parents=True)
    paths.experiment_registry.write_text(
        json.dumps({"selection_events": []}), encoding="utf-8"
    )
    selected = ExperimentSpec(
        experiment_id="candidate",
        task="router",
        seed=7703,
        learning_rate=2e-5,
        epochs=1.0,
        lora_rank=16,
    )
    candidates = [{"spec": selected.to_dict(), "selection_score": 1.0}]

    first = record_selection(
        stage="router-lr",
        candidates=candidates,
        selected=(selected,),
        rule="frozen rule",
        paths=paths,
    )
    second = record_selection(
        stage="router-lr",
        candidates=candidates,
        selected=(selected,),
        rule="frozen rule",
        paths=paths,
    )

    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    assert first == second
    assert len(registry["selection_events"]) == 1
    with pytest.raises(RuntimeError, match="different evidence"):
        record_selection(
            stage="router-lr",
            candidates=[{"spec": selected.to_dict(), "selection_score": 0.0}],
            selected=(selected,),
            rule="frozen rule",
            paths=paths,
        )


def test_router_lora_target_uses_the_rank_stage_winner() -> None:
    parent = ExperimentSpec(
        experiment_id="router-parent",
        task="router",
        seed=7703,
        learning_rate=2e-5,
        epochs=1.0,
        lora_rank=16,
    )
    ranks = lora_rank_experiments(parent)
    rank_winner = next(item for item in ranks if item.lora_rank == 8)
    target = router_lora_target_experiment(rank_winner)

    assert {item.lora_rank for item in ranks} == {8, 32}
    assert all(item.lora_target == "all" for item in ranks)
    assert target.lora_rank == 8
    assert target.lora_target != "all"
    assert target.parent_experiment_id == rank_winner.experiment_id


def test_router_data_ablation_has_explicit_equal_budget_controls() -> None:
    winner = ExperimentSpec(
        experiment_id="router-winner",
        task="router",
        seed=7703,
        learning_rate=2e-5,
        epochs=2.0,
        lora_rank=16,
    )
    experiments = router_data_experiments(winner)
    variants = {item.dataset_variant for item in experiments}

    assert "data_100pct" in variants
    assert "state_mixed" in variants
    assert all(item.max_steps == ROUTER_FIXED_OPTIMIZER_STEPS for item in experiments)


def test_attribution_groups_have_explicit_controls() -> None:
    router_winner = ExperimentSpec(
        experiment_id="router-winner",
        task="router",
        seed=7703,
        learning_rate=2e-5,
        epochs=1.0,
        lora_rank=16,
    )
    router_specs = [router_winner, *router_data_experiments(router_winner)]
    router_groups = attribution_groups(
        task="router", winner=router_winner, specs=router_specs
    )

    assert {item["stage"] for item in router_groups} == {
        "r-data-scale",
        "r-data-replay",
        "r-data-state",
    }
    assert {item["anchor"].experiment_id for item in router_groups} == {
        "r-data-scale-100pct",
        "r-data-replay-00pct",
        "r-data-state-mixed",
    }

    tutor_winner = ExperimentSpec(
        experiment_id="tutor-winner",
        task="tutor",
        seed=6209,
        learning_rate=3e-5,
        epochs=1.0,
        lora_rank=16,
    )
    tutor_specs = [tutor_winner, *tutor_mix_experiments(tutor_winner)]
    [tutor_group] = attribution_groups(
        task="tutor", winner=tutor_winner, specs=tutor_specs
    )

    assert tutor_group["stage"] == "t-mix"
    assert tutor_group["anchor"] == tutor_winner
    assert len(tutor_group["candidates"]) == 4


def test_tutor_no_tool_safety_is_independent_of_json_validity() -> None:
    row = {
        "task_family": "no_answer_v2",
        "assistant_target": {"answer": "证据不足", "evidence_sources": []},
    }

    truncated = _tutor_scores(row, None, '{"answer":"证据不足"')
    tool_output = _tutor_scores(
        row,
        None,
        '{"mode":"tools","actions":[{"name":"search_materials"}]}',
    )

    assert truncated["json_valid"] is False
    assert truncated["no_tool_actions"] is True
    assert tool_output["no_tool_actions"] is False


def test_context_study_reuses_only_matching_complete_outputs(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps({"example_id": "row-1", "messages": []}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "result"
    raw = output / "sft/raw"
    raw.mkdir(parents=True)
    (raw / "predictions.jsonl").write_text(
        json.dumps({"example_id": "row-1"}) + "\n", encoding="utf-8"
    )
    summary = {
        "task": "tutor",
        "condition": "sft",
        "records": 1,
        "input_contract": {"dataset_sha256": sha256_file(dataset)},
    }
    (raw / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    assert _completed_evaluation(output_root=output, dataset_path=dataset) == summary

    dataset.write_text(
        json.dumps({"example_id": "row-2", "messages": []}) + "\n",
        encoding="utf-8",
    )
    assert _completed_evaluation(output_root=output, dataset_path=dataset) is None


def test_evaluation_progress_is_written_only_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _report_progress(task="router", condition="prompt", completed=8, total=300)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "task": "router",
        "condition": "prompt",
        "completed": 8,
        "total": 300,
    }


def test_sealed_claim_creation_is_atomic(tmp_path: Path) -> None:
    claim_path = tmp_path / "sealed_evaluation_claim.json"
    claim = {"task": "router", "claim": 1}

    _write_exclusive_json(claim_path, claim)

    assert json.loads(claim_path.read_text(encoding="utf-8")) == claim
    with pytest.raises(FileExistsError, match="already claimed"):
        _write_exclusive_json(claim_path, {"task": "router", "claim": 2})
    assert json.loads(claim_path.read_text(encoding="utf-8")) == claim


def test_completion_requires_valid_single_use_claim_and_passing_sealed_gate(
    tmp_path: Path,
) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    final_root = paths.evaluation_root / "final/router"
    final_root.mkdir(parents=True)
    outputs: dict[str, str] = {}
    for name in ("predictions", "summary", "gate"):
        artifact = final_root / f"{name}.json"
        artifact.write_text("{}\n", encoding="utf-8")
        outputs[f"{name}_path"] = str(artifact)
        outputs[f"{name}_sha256"] = sha256_file(artifact)
    decision = final_root / "final_decision.json"
    decision.write_text('{"passed": true}\n', encoding="utf-8")
    decision_sha = sha256_file(decision)
    receipt_path = final_root / "sealed_evaluation_receipt.json"
    receipt = {
        "schema_version": "studyhub.agent.sft.controlled_v2.sealed_receipt.v2",
        "evaluation_count": 1,
        "selected_before_sealed_evaluation": True,
        "development_decision": {"sha256": decision_sha},
        "outputs": outputs,
        "sealed_gate": {"passed": True},
        "policy": {
            "repeat_evaluation_allowed": False,
            "sealed_result_used_for_model_selection": False,
        },
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    assert _sealed_requirement(paths, "router")["passed"] is False

    claim_path = final_root / "sealed_evaluation_claim.json"
    claim = {
        "schema_version": "studyhub.agent.sft.controlled_v2.sealed_claim.v1",
        "task": "router",
        "development_decision": {"sha256": decision_sha},
        "policy": {
            "claim_is_single_use": True,
            "claim_removed_after_failure": False,
        },
    }
    _write_exclusive_json(claim_path, claim)
    receipt["single_use_claim"] = {
        "path": str(claim_path),
        "sha256": sha256_file(claim_path),
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert _sealed_requirement(paths, "router")["passed"] is True

    receipt["sealed_gate"] = {"passed": False}
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert _sealed_requirement(paths, "router")["passed"] is False


def test_incomplete_controlled_report_is_explicitly_a_preview(tmp_path: Path) -> None:
    output = tmp_path / "controlled-v2-preview.html"

    build_report(output, allow_incomplete=True, write_manifest=False)

    rendered = output.read_text(encoding="utf-8")
    assert 'name="studyhub-report-schema" content="controlled_v2"' in rendered
    assert "实验尚未完成" in rendered
    assert "所有统计仅来自 controlled_v2 产物" in rendered


def test_context_report_reads_latency_from_runtime_summary(tmp_path: Path) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    index = paths.evaluation_root / "t-context/results/context_study_index.json"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps(
            {
                "chunks_1_output_768": {
                    "metrics": {
                        "strict_grounded_pass": _metric(1.0),
                        "citation_exact": _metric(1.0),
                        "no_answer_abstention": _metric(1.0),
                    },
                    "runtime": {"seconds_per_record": 1.2345},
                }
            }
        ),
        encoding="utf-8",
    )

    rendered = _context_table(paths)

    assert "1.2345 s" in rendered
    assert "pending s" not in rendered


def test_seed_panel_does_not_accept_an_unvalidated_sealed_receipt(
    tmp_path: Path,
) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    final_root = paths.evaluation_root / "final/router"
    final_root.mkdir(parents=True)
    (final_root / "final_decision.json").write_text(
        json.dumps(
            {
                "passed": True,
                "experiment_id": "router-winner",
                "delivery_seed": 7703,
                "configuration": {"learning_rate": 2e-5},
                "seed_summary": {
                    "mean": 1.0,
                    "std": 0.0,
                    "min": 1.0,
                    "seeds": [{"seed": 7703, "rate": 1.0}],
                },
            }
        ),
        encoding="utf-8",
    )
    (final_root / "sealed_evaluation_receipt.json").write_text(
        json.dumps({"evaluation_count": 1}),
        encoding="utf-8",
    )

    rendered = _seed_panel(paths, "router")

    assert "SEALED · RECEIPT NOT VALIDATED" in rendered
    assert "SEALED · OPENED ONCE" not in rendered


def test_challenge_review_locks_rubric_and_frozen_fields(tmp_path: Path) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    paths.contract_dir.mkdir(parents=True)
    source = {
        "example_id": "challenge-1",
        "task_family": "no_answer_v2",
        "user_payload": {
            "current_user_query": "只按证据回答",
            "tool_observations": [
                {
                    "result": {
                        "evidence": [
                            {
                                "chunk_id": "1:preview:1:a",
                                "material_id": 1,
                                "page": 1,
                                "text": "没有问题答案。",
                            }
                        ]
                    }
                }
            ],
        },
        "teacher_target": {"mode": "final", "answer": "证据不足"},
    }
    packet = paths.contract_dir / "tutor_human_review_packet_v2.jsonl"
    packet.write_text(json.dumps(source, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = build_challenge_review(paths=paths)
    assert Path(str(manifest["review_rubric"])).is_file()
    assert Path(str(manifest["frozen_packet"])).is_file()

    review_csv = Path(str(manifest["review_csv"]))
    with review_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows[0].update(
        {
            "teacher_target_json": "{}",
            "evidence_support": "pass",
            "citation_correct": "pass",
            "boundary_correct": "pass",
            "review_status": "approved",
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-08-16T00:00:00Z",
        }
    )
    with review_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    result = validate_challenge_review(review_csv=review_csv, paths=paths)

    assert result["human_review_completed"] is False
    assert "challenge-1: frozen field changed: teacher_target_json" in result["errors"]


def test_final_blind_review_locks_predictions_and_rubric(tmp_path: Path) -> None:
    paths = ControlledPaths(project_root=tmp_path)
    decision_path = paths.evaluation_root / "final/tutor/final_decision.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text(
        json.dumps(
            {
                "passed": True,
                "experiment_id": "tutor-winner",
                "delivery_seed": 6209,
            }
        ),
        encoding="utf-8",
    )
    families = (
        "normal_answer_v2",
        "no_answer_v2",
        "distractor_v2",
        "conflict_v2",
        "partial_evidence_v2",
        "citation_counterfactual_v2",
    )
    challenge_rows = []
    prediction_rows = []
    for family in families:
        for index in range(20):
            example_id = f"{family}-{index:02d}"
            payload = {
                "current_user_query": f"question {example_id}",
                "tool_observations": [
                    {
                        "result": {
                            "evidence": [
                                {
                                    "chunk_id": f"chunk-{example_id}",
                                    "material_id": index + 1,
                                    "page": 1,
                                    "text": "evidence",
                                }
                            ]
                        }
                    }
                ],
            }
            challenge_rows.append(
                {
                    "example_id": example_id,
                    "task_family": family,
                    "messages": [
                        {"role": "user", "content": json.dumps(payload)}
                    ],
                }
            )
            prediction_rows.append(
                {
                    "example_id": example_id,
                    "task_family": family,
                    "generated": '{"mode":"final","answer":"ok"}',
                }
            )
    paths.tutor_challenge.parent.mkdir(parents=True, exist_ok=True)
    paths.tutor_challenge.write_text(
        "".join(json.dumps(row) + "\n" for row in challenge_rows),
        encoding="utf-8",
    )
    prediction_path = (
        paths.evaluation_root
        / "tutor-winner/6209/sft/raw/predictions.jsonl"
    )
    prediction_path.parent.mkdir(parents=True)
    prediction_path.write_text(
        "".join(json.dumps(row) + "\n" for row in prediction_rows),
        encoding="utf-8",
    )

    manifest = build_final_review(paths=paths, seed=7)
    assert Path(str(manifest["review_rubric"])).is_file()
    assert Path(str(manifest["frozen_packet"])).is_file()

    review_csv = Path(str(manifest["review_csv"]))
    with review_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    for row in rows:
        row.update(
            {
                "reviewer_a_correctness": "pass",
                "reviewer_a_faithfulness": "pass",
                "reviewer_a_readability": "pass",
                "reviewer_a": "reviewer-a",
                "reviewer_a_at": "2026-08-16T00:00:00Z",
                "reviewer_b_correctness": "pass",
                "reviewer_b_faithfulness": "pass",
                "reviewer_b_readability": "pass",
                "reviewer_b": "reviewer-b",
                "reviewer_b_at": "2026-08-16T00:05:00Z",
            }
        )
    rows[0]["generated_answer_json"] = "{}"
    with review_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    result = validate_final_review(review_csv=review_csv, paths=paths)

    assert result["completed"] is False
    assert any(
        error.endswith("frozen field changed: generated_answer_json")
        for error in result["errors"]
    )
