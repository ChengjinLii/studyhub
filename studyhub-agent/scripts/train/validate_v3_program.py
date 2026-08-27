#!/usr/bin/env python3
"""Validate the machine-readable StudyHub Agentic Post-Training v3 plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRAM_DIR = PROJECT_ROOT / "configs" / "program-v3"
PROGRAM_PATH = PROGRAM_DIR / "training-program-v3.json"
CAPABILITY_PATH = PROGRAM_DIR / "capability-matrix-v1.json"
ALGORITHM_PATH = PROGRAM_DIR / "algorithm-decision-matrix-v1.json"
SFT_DATA_CARD_PATH = PROGRAM_DIR / "runtime-sft-v3-data-card.json"
SFT_GATE_EVIDENCE_PATH = PROJECT_ROOT / "docs" / "training" / "evidence" / "runtime-sft-v3-9b-gate-20260827.json"
SFT_PROFILE_EVIDENCE_PATH = PROJECT_ROOT / "docs" / "training" / "evidence" / "runtime-sft-v3-9b-profile-20260828.json"
DEFECT_INDEX_PATH = PROJECT_ROOT / "design-defects" / "index.json"
HTML_PLAN_PATH = PROJECT_ROOT / "docs" / "StudyHub_9B_Agentic_Post_Training_Program_v3.html"

EXPECTED_CAPABILITIES = {
    "direct_answer_abstention",
    "tool_routing",
    "function_calling",
    "rag_search_read",
    "query_rewrite",
    "multi_hop_retrieval",
    "citation_claim_grounding",
    "insufficient_evidence",
    "web_search_fetch",
    "rag_to_web_fallback",
    "personal_memory",
    "collective_memory",
    "rag_memory_composition",
    "web_memory_composition",
    "permission_recovery",
    "tool_failure_recovery",
    "conflict_resolution",
    "long_horizon",
    "deep_research",
    "stop_cost_control",
}

VALID_STATES = {
    "UNDEFINED",
    "CONTRACT_ONLY",
    "SFT",
    "RL",
    "DEV",
    "SEALED",
    "SUPPORTED_CLAIM",
}

EXPECTED_ALGORITHMS = {
    "PPO",
    "GRPO",
    "REINFORCE",
    "REINFORCE_PLUS_PLUS",
    "RLOO",
    "DAPO",
    "GSPO",
    "DR_GRPO",
    "CISPO",
    "SAPO_SOFT_ADAPTIVE",
    "OPD",
    "KDRL",
    "DPO",
    "KTO",
    "IPO",
    "OUTCOME_RM",
    "PROCESS_RM",
}

VALID_ALGORITHM_STATUSES = {
    "MAIN_BASELINE",
    "DIAGNOSTIC_CONDITIONAL",
    "LITERATURE_ONLY",
    "OFFLINE_BASELINE_ONLY",
    "REWARD_COMPONENT",
}

EXPECTED_PHASE_ORDER = [
    "FREEZE_V2_HISTORY",
    "CAPABILITY_AND_BENCHMARK_V2",
    "NINE_B_BASE_EVAL",
    "RUNTIME_NATIVE_SFT_DATA",
    "NINE_B_SFT",
    "REWARD_V3_AND_RL_LEARNABILITY",
    "DUAL_H100_PROFILE",
    "NINE_B_GRPO",
    "INDEPENDENT_CONFIRMATION",
]

BENCHMARK_V2_MANIFEST_SHA256 = "da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)


def validate_program(
    project_root: Path = PROJECT_ROOT, *, check_local_assets: bool = False
) -> tuple[list[str], dict[str, Any]]:
    program_path = project_root / "configs" / "program-v3" / "training-program-v3.json"
    capability_path = project_root / "configs" / "program-v3" / "capability-matrix-v1.json"
    algorithm_path = project_root / "configs" / "program-v3" / "algorithm-decision-matrix-v1.json"
    sft_data_card_path = project_root / "configs" / "program-v3" / "runtime-sft-v3-data-card.json"
    sft_gate_evidence_path = project_root / "docs/training/evidence/runtime-sft-v3-9b-gate-20260827.json"
    sft_profile_evidence_path = project_root / "docs/training/evidence/runtime-sft-v3-9b-profile-20260828.json"
    defect_index_path = project_root / "design-defects" / "index.json"

    errors: list[str] = []
    program = _load_json(program_path)
    matrix = _load_json(capability_path)
    algorithm_matrix = _load_json(algorithm_path)
    sft_data_card = _load_json(sft_data_card_path)
    sft_gate_evidence = _load_json(sft_gate_evidence_path)
    sft_profile_evidence = _load_json(sft_profile_evidence_path)
    defects = _load_json(defect_index_path)

    if program.get("schema_version") != "studyhub.training-program.v3":
        errors.append("unexpected training-program schema version")
    if program.get("launch_authorized") is not True:
        errors.append("the reviewed formal r16 SFT launch must be explicitly authorized")
    if program.get("launch_authorization_scope") != ["NINE_B_SFT_FORMAL_R16_ONE_PASS"]:
        errors.append("GPU launch authorization must be limited to one formal r16 SFT pass")
    if program.get("gpu_gate_authorized") is not True:
        errors.append("the accepted SFT data must retain authorization for reproducible diagnostic GPU checks")
    if program.get("sft_profile_authorized") is not True:
        errors.append("equal-budget SFT profiling must be explicitly authorized after the Gate passes")
    if program.get("formal_sft_authorized") is not True:
        errors.append("formal SFT authorization is missing after the controlled profile decision")
    prompt_contracts = (
        ("source_prompt", "source_prompt_sha256"),
        ("benchmark_execution_prompt", "benchmark_execution_prompt_sha256"),
    )
    for path_key, hash_key in prompt_contracts:
        expected_hash = str(program.get(hash_key, ""))
        if len(expected_hash) != 64:
            errors.append(f"{hash_key} is not a SHA-256 digest")
            continue
        prompt_path = Path(str(program.get(path_key, "")))
        if prompt_path.is_file() and _sha256(prompt_path) != expected_hash:
            errors.append(f"{path_key} drifted from its recorded digest")

    architecture = program.get("architecture", {})
    if architecture.get("hermes") != "the only agent loop and tool-interaction harness":
        errors.append("Hermes must remain the only Agent loop")
    required_forbidden = {"router", "planner", "fixed_dag", "second_tool_loop", "second_memory_manager"}
    if not required_forbidden.issubset(set(architecture.get("forbidden_mainline", []))):
        errors.append("frozen architecture boundary is incomplete")

    history = program.get("history", {})
    if history.get("four_b_policy") != "FROZEN_HISTORY_ONLY":
        errors.append("4B must be frozen as historical evidence")
    if program.get("model", {}).get("four_b_is_gate") is not False:
        errors.append("4B must not gate the 9B mainline")
    if program.get("model", {}).get("main_scale") != "9B":
        errors.append("the v3 main model must be 9B")
    if len(history.get("not_promoted", [])) < 3:
        errors.append("legacy v2 SFT, GRPO and Eval32 entry points must be explicitly non-promoted")

    capabilities = matrix.get("capabilities", [])
    capability_ids = {item.get("id") for item in capabilities}
    if capability_ids != EXPECTED_CAPABILITIES:
        missing = sorted(EXPECTED_CAPABILITIES - capability_ids)
        extra = sorted(capability_ids - EXPECTED_CAPABILITIES)
        errors.append(f"capability set mismatch; missing={missing}, extra={extra}")
    invalid_states = sorted({item.get("v3_state") for item in capabilities} - VALID_STATES)
    if invalid_states:
        errors.append(f"invalid capability states: {invalid_states}")
    if any(item.get("development_tasks", 0) <= 0 or item.get("sealed_tasks", 0) <= 0 for item in capabilities):
        errors.append("every capability must retain a positive future scale-up budget")
    if matrix.get("coverage_budget_status") != "SUPERSEDED_BY_STUDYHUB_AGENTBENCH_V2_MANIFEST":
        errors.append("legacy capability task budgets must not override frozen Benchmark v2 counts")

    benchmark = program.get("benchmark", {})
    benchmark_manifest_path = project_root / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark_card_path = project_root / "benchmarks/studyhub-agent-v2/BENCHMARK_CARD.json"
    benchmark_quality_path = project_root / "benchmarks/studyhub-agent-v2/quality-gate.json"
    base_evidence_path = project_root / "docs/benchmark/evidence/qwen35-9b-base-v2-development-variance-20260827.json"
    benchmark_manifest = _load_json(benchmark_manifest_path)
    benchmark_card = _load_json(benchmark_card_path)
    benchmark_quality = _load_json(benchmark_quality_path)
    base_evidence = _load_json(base_evidence_path)
    manifest_sha256 = _sha256(benchmark_manifest_path)
    if manifest_sha256 != BENCHMARK_V2_MANIFEST_SHA256:
        errors.append(f"Benchmark v2 manifest hash drifted: {manifest_sha256}")
    if benchmark.get("version") != "studyhub-agentbench-v2":
        errors.append("v3 must use StudyHub AgentBench v2")
    if benchmark.get("revision") != benchmark_manifest.get("benchmark_revision"):
        errors.append("training program benchmark revision does not match the frozen manifest")
    if benchmark.get("status") != "FROZEN_FOR_BASELINE":
        errors.append("training program benchmark must remain frozen")
    if benchmark.get("manifest_sha256") != manifest_sha256:
        errors.append("training program is not bound to the frozen Benchmark v2 manifest")
    if benchmark_manifest.get("status") != "FROZEN_FOR_BASELINE":
        errors.append("Benchmark v2 manifest is not frozen")
    if benchmark_card.get("status") != "FROZEN_FOR_BASELINE":
        errors.append("Benchmark v2 card is not frozen")
    if benchmark_quality.get("status") != "PASS":
        errors.append("Benchmark v2 quality gate is not passing")
    counts = benchmark_manifest.get("counts", {})
    regression_tasks = benchmark.get("regression", {}).get("tasks", 0)
    development_tasks = benchmark.get("development", {}).get("tasks", 0)
    sealed_a_tasks = benchmark.get("sealed_a", {}).get("tasks", 0)
    sealed_b_tasks = benchmark.get("sealed_b", {}).get("tasks", 0)
    sealed_tasks = sealed_a_tasks + sealed_b_tasks
    calibration_tasks = benchmark.get("calibration_challenge", {}).get("tasks", 0)
    expected_counts = {
        "regression": regression_tasks,
        "development": development_tasks,
        "sealed_a": sealed_a_tasks,
        "sealed_b": sealed_b_tasks,
        "calibration_challenge": calibration_tasks,
    }
    if counts != expected_counts:
        errors.append(f"Benchmark v2 split counts mismatch: program={expected_counts}, manifest={counts}")
    if sum(expected_counts.values()) != benchmark_card.get("tasks"):
        errors.append("Benchmark v2 total does not match the committed card")
    if base_evidence.get("benchmark_manifest_sha256") != manifest_sha256:
        errors.append("9B Base evidence is not bound to the current Benchmark v2 manifest")
    development_evidence = base_evidence.get("development", {})
    variance_evidence = base_evidence.get("variance", {})
    if development_evidence.get("episodes_scored") != development_tasks:
        errors.append("9B Base Development evidence is incomplete")
    if development_evidence.get("infra_excluded") != 0:
        errors.append("9B Base Development contains infrastructure exclusions")
    if variance_evidence.get("tasks_complete") != benchmark.get("variance_panel", {}).get("tasks"):
        errors.append("9B Base variance task evidence is incomplete")
    if variance_evidence.get("episodes_scored") != 140:
        errors.append("9B Base variance rollout evidence is incomplete")
    external_names = {item.get("name") for item in benchmark.get("external", [])}
    required_external = {
        "BFCL V4 Agentic",
        "tau2-bench",
        "DeepResearch Bench II",
        "BrowseComp-Plus",
    }
    if external_names != required_external:
        errors.append("external benchmark stack is incomplete")
    if any(item.get("model_evaluation") != "NOT_RUN" for item in benchmark.get("external", [])):
        errors.append("external model evaluation status must remain honest until official runs exist")
    execution_contract = benchmark.get("execution_contract", {})
    if execution_contract.get("training_examples_from_benchmark") != 0:
        errors.append("Benchmark v2 examples must not enter SFT or RL training")
    if execution_contract.get("sealed_use") != ("one final confirmation after all model and recipe choices are frozen"):
        errors.append("Sealed-A/B access is not restricted to final confirmation")
    if "never collapse" not in execution_contract.get("external_metric_policy", ""):
        errors.append("external benchmark metrics must remain separate")

    data = program.get("data", {})
    sft = data.get("sft", {})
    if not 60000 <= sft.get("candidate_trajectories", 0) <= 120000:
        errors.append("SFT candidate pool must be 60k-120k")
    if not 30000 <= sft.get("final_trajectories", 0) <= 60000:
        errors.append("final SFT set must be 30k-60k")
    token_min, token_max = sft.get("allowed_token_range", [0, 0])
    if not token_min <= sft.get("target_tokens", 0) <= token_max:
        errors.append("SFT target token budget is outside the allowed range")
    if not _close(sft.get("studyhub_share", 0) + sft.get("open_source_share", 0), 1.0):
        errors.append("SFT StudyHub/open source shares must sum to 1")
    if sft.get("runtime_native_multi_turn_min_share", 0) < 0.70:
        errors.append("at least 70% of core SFT must be runtime-native multi-turn")
    source_budget = sft.get("source_budget", [])
    source_total = sum(item.get("trajectories", 0) for item in source_budget)
    if source_total != sft.get("final_trajectories"):
        errors.append(f"SFT source budget mismatch: {source_total}")
    single_source_limit = sft.get("final_trajectories", 0) * sft.get("max_single_source_share", 0)
    oversized_sources = [
        item.get("source") for item in source_budget if item.get("trajectories", 0) > single_source_limit
    ]
    if oversized_sources:
        errors.append(f"SFT sources exceed the 25% cap: {oversized_sources}")
    benchmark_isolation = sft.get("benchmark_isolation", {})
    if benchmark_isolation.get("manifest_sha256") != manifest_sha256:
        errors.append("SFT data contract is not bound to frozen Benchmark v2")
    if benchmark_isolation.get("excluded_tasks") != sum(counts.values()):
        errors.append("SFT data contract does not exclude every Benchmark v2 task")
    if benchmark_isolation.get("public_and_hidden_prompt_hash_required") is not True:
        errors.append("SFT contamination audit must cover public and hidden benchmark prompts")
    if benchmark_isolation.get("sealed_content_visible_to_training") is not False:
        errors.append("Sealed benchmark content must remain unavailable to the training pipeline")

    if sft_data_card.get("status") != "ACCEPTED_FOR_SFT_GATE":
        errors.append("runtime SFT v3 data card is not accepted for the SFT Gate")
    card_rows = sft_data_card.get("rows", {})
    if card_rows.get("candidate") != sft.get("candidate_trajectories"):
        errors.append("runtime SFT candidate count differs from the training contract")
    if card_rows.get("selected") != sft.get("final_trajectories"):
        errors.append("runtime SFT selected count differs from the training contract")
    if sum(card_rows.get(split, 0) for split in ("train", "validation", "protocol_holdout")) != card_rows.get(
        "selected"
    ):
        errors.append("runtime SFT split counts do not sum to the selected total")
    card_source_counts = sft_data_card.get("source_counts", {})
    contract_source_counts = {item.get("source"): item.get("trajectories") for item in source_budget}
    if card_source_counts != contract_source_counts:
        errors.append("runtime SFT source counts differ from the training contract")
    card_runtime = sft_data_card.get("runtime", {})
    if card_runtime.get("runtime_native_share", 0) < sft.get("runtime_native_multi_turn_min_share", 0):
        errors.append("accepted runtime SFT data is below the runtime-native share contract")
    if card_runtime.get("max_source_share", 1) > sft.get("max_single_source_share", 0):
        errors.append("accepted runtime SFT data exceeds the single-source cap")
    card_tokens = sft_data_card.get("tokenization", {}).get("all_tokens", 0)
    if not token_min <= card_tokens <= token_max:
        errors.append("accepted runtime SFT token count is outside the contract")
    card_isolation = sft_data_card.get("isolation", {})
    if card_isolation.get("benchmark_manifest_sha256") != manifest_sha256:
        errors.append("runtime SFT data card is not bound to frozen Benchmark v2")
    if card_isolation.get("benchmark_prompt_overlap") != 0:
        errors.append("runtime SFT data overlaps frozen Benchmark v2 prompts")
    if card_isolation.get("2wiki_cross_split_support_titles") != 0:
        errors.append("runtime SFT data has cross-split 2Wiki support-title leakage")
    if card_isolation.get("2wiki_max_rows_per_document_component") != 1:
        errors.append("runtime SFT 2Wiki document-component concentration exceeds one row")
    quality_tiers = sft_data_card.get("quality_tiers", {})
    if "teacher_verified" in quality_tiers:
        errors.append("runtime SFT data must not claim unperformed teacher verification")
    if sum(quality_tiers.values()) != card_rows.get("selected"):
        errors.append("runtime SFT quality-tier counts do not cover every selected row")
    if sft_data_card.get("audit", {}).get("status") != "PASS" or sft_data_card.get("audit", {}).get("failures") != 0:
        errors.append("runtime SFT final audit has not passed")
    gates = {item.get("id"): item for item in program.get("gates", [])}
    if gates.get("G3", {}).get("status") != "PASSED":
        errors.append("G3 must be passed after accepting the runtime SFT data card")

    sft_training = program.get("training", {}).get("sft", {})
    sft_gate = sft_training.get("gate", {})
    if sft_gate.get("status") != "PASSED":
        errors.append("the runtime SFT Gate must be recorded as passed")
    if sft_gate.get("evidence_path") != "docs/training/evidence/runtime-sft-v3-9b-gate-20260827.json":
        errors.append("the runtime SFT Gate evidence path is not pinned")
    if sft_gate.get("trial") != sft_gate_evidence.get("trial"):
        errors.append("the training program and Gate evidence reference different trials")
    if sft_gate_evidence.get("status") != "PASSED" or sft_gate_evidence.get("evidence_grade") != "A_REAL_REPRODUCED":
        errors.append("runtime SFT Gate evidence is not a passed real run")
    gate_benchmark = sft_gate_evidence.get("benchmark_lock", {})
    if gate_benchmark.get("benchmark_manifest_sha256") != manifest_sha256:
        errors.append("runtime SFT Gate is not bound to frozen Benchmark v2")
    gate_dataset = sft_gate_evidence.get("dataset_release", {})
    if (
        gate_dataset.get("release_status") != "ACCEPTED_FOR_SFT_GATE"
        or gate_dataset.get("final_audit_status") != "PASS"
    ):
        errors.append("runtime SFT Gate did not use the accepted audited dataset release")
    gate_recipe = sft_gate_evidence.get("recipe", {})
    if gate_recipe.get("backend") != "fsdp:d2p1t1" or gate_recipe.get("gpus") != 2:
        errors.append("runtime SFT Gate did not execute the required dual-GPU FSDP recipe")
    gate_lora = sft_gate_evidence.get("lora_update", {})
    if gate_lora.get("update_observed") is not True or gate_lora.get("initial_sha256") == gate_lora.get("final_sha256"):
        errors.append("runtime SFT Gate does not prove a LoRA parameter update")
    gate_step = sft_gate_evidence.get("optimizer_step", {})
    if gate_step.get("sequences") != 8 or gate_step.get("assistant_loss_tokens", 0) <= 0:
        errors.append("runtime SFT Gate optimizer-step evidence is incomplete")
    gate_gpu = sft_gate_evidence.get("gpu", {})
    guard_max = gate_gpu.get("guard_max_used_mib", 0)
    per_gpu = gate_gpu.get("per_gpu", {})
    if set(per_gpu) != {"0", "1"} or any(
        metrics.get("peak_memory_used_mib", guard_max + 1) > guard_max for metrics in per_gpu.values()
    ):
        errors.append("runtime SFT Gate GPU evidence is missing or exceeded the guard")
    if gates.get("G4", {}).get("status") != "FORMAL_AUTHORIZED_PENDING_RUN_AND_EVAL":
        errors.append("G4 must distinguish formal authorization from a completed SFT or evaluation")
    profiles = sft_training.get("profiles", {})
    if profiles.get("status") != "PASSED" or {item.get("id") for item in profiles.get("candidates", [])} != {
        "profile-r16",
        "profile-r32",
    }:
        errors.append("equal-budget r16/r32 SFT profiles are not recorded as passed")
    if profiles.get("evidence_path") != "docs/training/evidence/runtime-sft-v3-9b-profile-20260828.json":
        errors.append("runtime SFT profile evidence path is not pinned")
    if profiles.get("selected_engineering_recipe") != "r16" or profiles.get("quality_claim") != (
        "NOT_EVALUATED_BY_PROFILE"
    ):
        errors.append("runtime SFT profile selection or claim boundary is invalid")
    if sft_training.get("lora_recipe", {}).get("final_choice") != "r16":
        errors.append("formal SFT recipe does not match the controlled profile selection")
    if (
        sft_profile_evidence.get("status") != "PASSED"
        or sft_profile_evidence.get("evidence_grade") != "A_REAL_REPRODUCED"
    ):
        errors.append("runtime SFT profile evidence is not a passed real comparison")
    profile_rows = sft_profile_evidence.get("profiles", {})
    if set(profile_rows) != {"r16", "r32"}:
        errors.append("runtime SFT profile evidence does not contain both ranks")
    else:
        left, right = profile_rows["r16"], profile_rows["r32"]
        if left.get("git", {}).get("status") or right.get("git", {}).get("status"):
            errors.append("runtime SFT profiles were not run from clean worktrees")
        if left.get("git", {}).get("commit") != right.get("git", {}).get("commit"):
            errors.append("runtime SFT profiles are bound to different commits")
        for field in ("sequences", "tokens", "assistant_loss_tokens"):
            if left.get("optimizer", {}).get(field) != right.get("optimizer", {}).get(field):
                errors.append(f"runtime SFT profile {field} budgets differ")
        if left.get("data") != right.get("data") or left.get("model") != right.get("model"):
            errors.append("runtime SFT profiles do not share model and data lineage")
        if left.get("data", {}).get("benchmark_lock", {}).get("benchmark_manifest_sha256") != manifest_sha256:
            errors.append("runtime SFT profiles are not bound to frozen Benchmark v2")
        for label, row in profile_rows.items():
            if row.get("optimizer", {}).get("updates") != 5:
                errors.append(f"runtime SFT {label} profile did not complete five updates")
            if row.get("lora_update", {}).get("update_observed") is not True:
                errors.append(f"runtime SFT {label} profile does not prove a LoRA update")
            profile_guard = row.get("gpu", {}).get("guard_max_used_mib", 0)
            if any(
                gpu.get("peak_memory_used_mib", profile_guard + 1) > profile_guard
                for gpu in row.get("gpu", {}).get("per_gpu", {}).values()
            ):
                errors.append(f"runtime SFT {label} profile exceeded the GPU guard")
    comparison = sft_profile_evidence.get("comparison", {})
    if comparison.get("selected_engineering_recipe") != "r16" or comparison.get("quality_claim") != (
        "NOT_EVALUATED_BY_PROFILE"
    ):
        errors.append("tracked runtime SFT profile comparison has an invalid selection")
    formal = sft_training.get("formal", {})
    expected_formal = {
        "status": "AUTHORIZED_PENDING_START",
        "authorization_scope": "ONE_R16_PASS_ONLY",
        "training_trial": "formal-r16-seed-20260827",
        "seed": 20260827,
        "rank": 16,
        "alpha": 16,
        "train_rows": 43650,
        "processed_rows": 43648,
        "drop_last_rows": 2,
        "global_batch_size": 8,
        "expected_optimizer_updates": 5456,
        "train_all_tokens": 55554221,
        "train_assistant_loss_tokens": 8152342,
        "dataset_manifest_sha256": sft_data_card.get("artifact_hashes", {}).get("token_manifest_sha256"),
        "data_card_sha256": _sha256(sft_data_card_path),
        "benchmark_manifest_sha256": manifest_sha256,
        "checkpoint_every_updates": 546,
        "recovery_every_updates": 50,
    }
    mismatched_formal = {
        key: {"expected": expected, "actual": formal.get(key)}
        for key, expected in expected_formal.items()
        if formal.get(key) != expected
    }
    if mismatched_formal:
        errors.append(f"formal SFT contract mismatch: {mismatched_formal}")
    if formal.get("estimate_not_measurement") is not True:
        errors.append("formal SFT duration estimate must not be represented as a measured run")
    if "Stable training_trial" not in formal.get("recovery_contract", ""):
        errors.append("formal SFT does not define stable-trial recovery")
    if len(formal.get("post_training_gate", [])) != 4:
        errors.append("formal SFT post-training evaluation gate is incomplete")

    rl = data.get("rl", {})
    if not 12000 <= rl.get("candidate_tasks", 0) <= 20000:
        errors.append("RL candidate pool must be 12k-20k")
    if not 8000 <= rl.get("post_qa_tasks", 0) <= 15000:
        errors.append("RL post-QA pool must be 8k-15k")
    if not 2500 <= rl.get("initial_unique_tasks", 0) <= 5000:
        errors.append("initial RL run must use 2.5k-5k unique tasks")
    if not 6000 <= rl.get("expanded_unique_tasks", 0) <= 10000:
        errors.append("expanded RL run must use 6k-10k unique tasks")
    if not _close(rl.get("studyhub_share", 0) + rl.get("external_share", 0), 1.0):
        errors.append("RL StudyHub/external shares must sum to 1")
    if not _close(sum(rl.get("family_mix", {}).values()), 1.0):
        errors.append("RL family mix must sum to 1")
    forbidden_public = set(rl.get("forbidden_public_fields", []))
    if not {"expected_calls", "gold_query", "gold_source_order", "gold_trajectory"}.issubset(forbidden_public):
        errors.append("v3 public-task gold-path exclusions are incomplete")

    reward = program.get("reward", {})
    grader_paths = {
        reward.get("training_code_path"),
        reward.get("development_evaluator_path"),
        reward.get("sealed_evaluator_path"),
    }
    if len(grader_paths) != 3 or None in grader_paths:
        errors.append("training Reward, Dev evaluator and Sealed evaluator paths must be distinct")
    if reward.get("path_agnostic") is not True or reward.get("gold_path_equality_allowed") is not False:
        errors.append("Reward v3 must be path-agnostic")
    if [layer.get("level") for layer in reward.get("layers", [])] != [1, 2, 3, 4]:
        errors.append("Reward v3 must contain the four ordered layers")
    if not 500 <= reward.get("calibration", {}).get("cases", 0) <= 1000:
        errors.append("Reward v3 calibration must contain 500-1000 cases")

    training = program.get("training", {})
    if training.get("phase_order") != EXPECTED_PHASE_ORDER:
        errors.append("v3 phase order does not match Benchmark-first 9B mainline")
    grpo = training.get("grpo", {})
    update_min, update_max = grpo.get("allowed_initial_update_range", [0, 0])
    if not update_min <= grpo.get("initial_optimizer_updates", 0) <= update_max:
        errors.append("initial GRPO update budget must stay within 300-600")
    if grpo.get("default_group_size") != 4 or grpo.get("high_branch_group_size") != 8:
        errors.append("GRPO group-size contract must be G=4 default and G=8 high-branch")
    if grpo.get("global_max_model_turns", 0) < 20:
        errors.append("v3 must not inherit the global six-turn capability cap")

    algorithm_policy = training.get("algorithm_policy", {})
    if algorithm_policy.get("decision_matrix") != "configs/program-v3/algorithm-decision-matrix-v1.json":
        errors.append("training program does not reference the Algorithm Decision Matrix")
    if algorithm_matrix.get("schema_version") != "studyhub.algorithm-decision-matrix.v1":
        errors.append("unexpected Algorithm Decision Matrix schema version")
    algorithms = algorithm_matrix.get("algorithms", [])
    algorithm_ids = {item.get("id") for item in algorithms}
    if algorithm_ids != EXPECTED_ALGORITHMS:
        missing = sorted(EXPECTED_ALGORITHMS - algorithm_ids)
        extra = sorted(algorithm_ids - EXPECTED_ALGORITHMS)
        errors.append(f"algorithm set mismatch; missing={missing}, extra={extra}")
    invalid_algorithm_statuses = sorted({item.get("status") for item in algorithms} - VALID_ALGORITHM_STATUSES)
    if invalid_algorithm_statuses:
        errors.append(f"invalid algorithm statuses: {invalid_algorithm_statuses}")
    algorithm_by_id = {item.get("id"): item for item in algorithms}
    if algorithm_by_id.get("GRPO", {}).get("status") != "MAIN_BASELINE":
        errors.append("GRPO must remain the only main algorithm baseline")
    if sum(item.get("status") == "MAIN_BASELINE" for item in algorithms) != 1:
        errors.append("the v3 plan must have exactly one main algorithm baseline")
    for algorithm in algorithms:
        required_fields = {
            "objective",
            "advantage_or_baseline",
            "critic",
            "reference_or_kl",
            "group_requirement",
            "policy_regime",
            "long_horizon_credit",
            "zero_variance_behavior",
            "compute_memory",
            "studyhub_trigger",
            "studyhub_decision",
            "sources",
        }
        missing_fields = sorted(field for field in required_fields if not algorithm.get(field))
        if missing_fields:
            errors.append(f"algorithm {algorithm.get('id')} is missing fields: {missing_fields}")
    for offline_id in {"DPO", "KTO", "IPO"}:
        if algorithm_by_id.get(offline_id, {}).get("status") != "OFFLINE_BASELINE_ONLY":
            errors.append(f"{offline_id} must remain an offline baseline")
    for component_id in {"OUTCOME_RM", "PROCESS_RM"}:
        if algorithm_by_id.get(component_id, {}).get("status") != "REWARD_COMPONENT":
            errors.append(f"{component_id} must remain a Reward component, not a policy optimizer")

    layouts = {item.get("id"): item for item in program.get("infrastructure", {}).get("layouts", [])}
    if set(layouts) != {"A", "B", "C"}:
        errors.append("dual-H100 profile must define layouts A, B and C")
    elif layouts["C"].get("status") != "CONDITIONAL":
        errors.append("async layout C must remain conditional")

    cards = defects.get("cards", [])
    if len(cards) != 17 or len(set(cards)) != 17:
        errors.append("the initial systemic audit must contain 17 unique defect cards")
    missing_cards = [card for card in cards if not (project_root / "design-defects" / card).is_file()]
    if missing_cards:
        errors.append(f"missing design defect cards: {missing_cards}")
    defect_sections = [
        "**Defect:**",
        "**Evidence:**",
        "**Competing explanations:**",
        "**Minimal falsification:**",
        "**Fix:**",
        "**Regression:**",
        "**Residual risk:**",
    ]
    malformed_cards = []
    for card in cards:
        card_path = project_root / "design-defects" / card
        if card_path.is_file():
            card_text = card_path.read_text(encoding="utf-8")
            if any(section not in card_text for section in defect_sections):
                malformed_cards.append(card)
    if malformed_cards:
        errors.append(f"design defect cards do not follow the required evidence template: {malformed_cards}")

    research_path = project_root / "research" / "primary-source-review.md"
    if not research_path.is_file():
        errors.append("primary-source research review is missing")
    else:
        research_text = research_path.read_text(encoding="utf-8")
        required_research = [
            "OpenAI Deep Research",
            "Hermes Agent",
            "AReaL and SGLang",
            "BFCL V4",
            "tau3-bench",
            "DeepResearch Bench",
            "BrowseComp",
            "BrowseComp-Plus",
            "GAIA",
            "xbench-DeepSearch",
            "Anthropic",
            "Search-R1",
            "WebAgent-R1",
            "ReTool",
            "WebRL",
            "OpenWebRL",
            "Agent-R1",
            "SkyRL-Agent",
            "OpenResearcher",
            "HermesBench",
            "DAPO",
            "RLOO",
            "REINFORCE++",
            "GSPO",
            "Dr. GRPO",
            "CISPO",
            "SAPO",
            "OPD",
            "KDRL",
            "DPO",
            "KTO",
            "IPO",
            "Process Reward Model",
            "Agent Lightning",
        ]
        missing_research = [name for name in required_research if name not in research_text]
        if missing_research:
            errors.append(f"primary-source review is incomplete: {missing_research}")

    html_path = project_root / "docs" / "StudyHub_9B_Agentic_Post_Training_Program_v3.html"
    if not html_path.is_file():
        errors.append("v3 HTML training program is missing")
    else:
        html = html_path.read_text(encoding="utf-8")
        required_html_tokens = [
            "9B Agentic Post-Training",
            "BENCHMARK v2 FROZEN",
            "12 Regression",
            "51 Dev",
            "13 Sealed-A",
            "12 Sealed-B",
            "35 × 4",
            "105,690 候选",
            "48.5k Runtime-native SFT",
            "10k RL QA Pool",
            "500-update 9B GRPO Main",
            "Algorithm Decision Matrix",
            "SFT GATE PASSED",
            "PROFILE PASSED",
            "5,456 updates",
            "55,554,221 train tokens",
        ]
        missing_html = [token for token in required_html_tokens if token not in html]
        if missing_html:
            errors.append(f"v3 HTML plan is missing contract tokens: {missing_html}")

    model_path = Path(program.get("model", {}).get("local_path", ""))
    if check_local_assets:
        if not model_path.is_dir():
            errors.append(f"9B model directory is missing: {model_path}")
        elif len(list(model_path.glob("model.safetensors-*-of-*.safetensors"))) != 4:
            errors.append("9B model does not have the expected four safetensor shards")
        artifact_paths = {
            "candidate_jsonl_sha256": project_root / "datasets/interim/runtime_sft_v3/candidates.jsonl",
            "candidate_manifest_sha256": project_root / "datasets/interim/runtime_sft_v3/candidates.manifest.json",
            "selected_jsonl_sha256": project_root / "datasets/interim/runtime_sft_v3/selected.jsonl",
            "selected_manifest_sha256": project_root / "datasets/interim/runtime_sft_v3/selected.manifest.json",
            "token_manifest_sha256": project_root / "datasets/processed/runtime_sft_v3_qwen35_9b/manifest.json",
            "final_audit_sha256": project_root / "datasets/processed/runtime_sft_v3_qwen35_9b/audit.json",
        }
        expected_artifact_hashes = sft_data_card.get("artifact_hashes", {})
        for name, path in artifact_paths.items():
            if not path.is_file():
                errors.append(f"runtime SFT artifact is missing: {path}")
            elif _sha256(path) != expected_artifact_hashes.get(name):
                errors.append(f"runtime SFT artifact hash mismatch: {name}")

    summary = {
        "program_id": program.get("program_id"),
        "status": program.get("status"),
        "capabilities": len(capabilities),
        "benchmark_version": benchmark.get("version"),
        "benchmark_manifest_sha256": manifest_sha256,
        "regression_tasks": regression_tasks,
        "development_tasks": development_tasks,
        "sealed_tasks": sealed_tasks,
        "calibration_challenge_tasks": calibration_tasks,
        "base_development_scored": development_evidence.get("episodes_scored"),
        "base_variance_scored": variance_evidence.get("episodes_scored"),
        "sft_final_trajectories": sft.get("final_trajectories"),
        "sft_data_status": sft_data_card.get("status"),
        "sft_all_tokens": card_tokens,
        "sft_gate_status": sft_gate.get("status"),
        "sft_gate_trial": sft_gate.get("trial"),
        "sft_profile_status": profiles.get("status"),
        "sft_profile_selected_recipe": profiles.get("selected_engineering_recipe"),
        "formal_sft": {
            "status": formal.get("status"),
            "training_trial": formal.get("training_trial"),
            "expected_optimizer_updates": formal.get("expected_optimizer_updates"),
            "train_all_tokens": formal.get("train_all_tokens"),
            "train_assistant_loss_tokens": formal.get("train_assistant_loss_tokens"),
        },
        "rl_post_qa_tasks": rl.get("post_qa_tasks"),
        "initial_grpo_updates": grpo.get("initial_optimizer_updates"),
        "algorithms": len(algorithms),
        "design_defects": len(cards),
        "launch_authorized": program.get("launch_authorized"),
    }
    return errors, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--check-local-assets", action="store_true")
    args = parser.parse_args()

    errors, summary = validate_program(args.project_root.resolve(), check_local_assets=args.check_local_assets)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("V3_PROGRAM_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
