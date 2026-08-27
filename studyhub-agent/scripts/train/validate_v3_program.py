#!/usr/bin/env python3
"""Validate the machine-readable StudyHub Agentic Post-Training v3 plan."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRAM_DIR = PROJECT_ROOT / "configs" / "program-v3"
PROGRAM_PATH = PROGRAM_DIR / "training-program-v3.json"
CAPABILITY_PATH = PROGRAM_DIR / "capability-matrix-v1.json"
ALGORITHM_PATH = PROGRAM_DIR / "algorithm-decision-matrix-v1.json"
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
    "CAPABILITY_AND_BENCHMARK_V1",
    "NINE_B_BASE_EVAL",
    "RUNTIME_NATIVE_SFT_DATA",
    "NINE_B_SFT",
    "REWARD_V3_AND_RL_LEARNABILITY",
    "DUAL_H100_PROFILE",
    "NINE_B_GRPO",
    "INDEPENDENT_CONFIRMATION",
]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)


def validate_program(
    project_root: Path = PROJECT_ROOT, *, check_local_assets: bool = False
) -> tuple[list[str], dict[str, Any]]:
    program_path = project_root / "configs" / "program-v3" / "training-program-v3.json"
    capability_path = project_root / "configs" / "program-v3" / "capability-matrix-v1.json"
    algorithm_path = project_root / "configs" / "program-v3" / "algorithm-decision-matrix-v1.json"
    defect_index_path = project_root / "design-defects" / "index.json"

    errors: list[str] = []
    program = _load_json(program_path)
    matrix = _load_json(capability_path)
    algorithm_matrix = _load_json(algorithm_path)
    defects = _load_json(defect_index_path)

    if program.get("schema_version") != "studyhub.training-program.v3":
        errors.append("unexpected training-program schema version")
    if program.get("launch_authorized") is not False:
        errors.append("v3 launch must remain unauthorized until Benchmark and Base gates pass")

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
        errors.append("every capability must have positive Dev and Sealed coverage")

    benchmark = program.get("benchmark", {})
    regression_tasks = benchmark.get("regression", {}).get("tasks", 0)
    development_tasks = benchmark.get("development", {}).get("tasks", 0)
    sealed_tasks = benchmark.get("sealed", {}).get("tasks", 0)
    matrix_development = sum(item.get("development_tasks", 0) for item in capabilities)
    matrix_sealed = sum(item.get("sealed_tasks", 0) for item in capabilities)
    if not 100 <= regression_tasks <= 200:
        errors.append("Regression must contain 100-200 tasks")
    if not 800 <= development_tasks <= 1200:
        errors.append("Development must contain 800-1200 tasks")
    if not 400 <= sealed_tasks <= 600:
        errors.append("Sealed must contain 400-600 tasks")
    if development_tasks != matrix_development:
        errors.append(f"Development task budget mismatch: program={development_tasks}, matrix={matrix_development}")
    if sealed_tasks != matrix_sealed:
        errors.append(f"Sealed task budget mismatch: program={sealed_tasks}, matrix={matrix_sealed}")
    external_names = {item.get("name") for item in benchmark.get("external", [])}
    required_external = {
        "BFCL V4",
        "tau3-bench",
        "DeepResearch Bench",
        "BrowseComp",
        "BrowseComp-Plus",
        "GAIA or xbench-DeepSearch",
        "HermesBench",
    }
    if not required_external.issubset(external_names):
        errors.append("external benchmark stack is incomplete")

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
    invalid_algorithm_statuses = sorted(
        {item.get("status") for item in algorithms} - VALID_ALGORITHM_STATUSES
    )
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
            "160 Regression",
            "1,005 Dev",
            "500 Sealed",
            "45k Runtime-native SFT",
            "10k RL QA Pool",
            "500-update 9B GRPO Main",
            "Algorithm Decision Matrix",
            "GPU TRAINING NOT STARTED",
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

    summary = {
        "program_id": program.get("program_id"),
        "status": program.get("status"),
        "capabilities": len(capabilities),
        "regression_tasks": regression_tasks,
        "development_tasks": development_tasks,
        "sealed_tasks": sealed_tasks,
        "sft_final_trajectories": sft.get("final_trajectories"),
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
