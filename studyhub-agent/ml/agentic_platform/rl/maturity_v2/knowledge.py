"""Build the evidence-backed 26-item Router RL maturity ledger."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...paths import BACKEND_ROOT
from ..spec import sha256_file

SEEDS = (3407, 7703, 9109, 6209, 11213)


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    number: int
    title: str
    finding: str
    checks: dict[str, bool]
    evidence: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        missing = [str(path.resolve()) for path in self.evidence if not path.exists()]
        passed = all(self.checks.values()) and not missing
        return {
            "number": self.number,
            "title": self.title,
            "status": "VERIFIED" if passed else "BLOCKED",
            "finding": self.finding,
            "checks": self.checks,
            "missing_evidence": missing,
            "evidence": [
                {
                    "path": str(path.resolve()),
                    "sha256": sha256_file(path) if path.is_file() else None,
                }
                for path in self.evidence
            ],
        }


def build_knowledge_coverage(
    *,
    repo_root: Path,
    artifact_root: Path,
    evaluation_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    paths = _paths(repo_root, artifact_root, evaluation_root)
    values = {name: _read_json(path) for name, path in paths.items() if path.suffix == ".json"}
    formal_runs = [
        _read_json(artifact_root / f"experiments/grpo_formal/seed_{seed}/run_summary.json")
        for seed in SEEDS
    ]
    formal_metrics = [
        artifact_root / f"experiments/grpo_formal/seed_{seed}/trainer_metrics.jsonl"
        for seed in SEEDS
    ]
    formal_trajectories = [
        artifact_root / f"experiments/grpo_formal/seed_{seed}/trajectory_rollouts.jsonl"
        for seed in SEEDS
    ]
    validation_gate = values["validation_gate"]
    test_gate = values["test_gate"]
    sealed_gate = values["sealed_gate"]
    action_audit = values["action_audit"]
    data_audit = values["data_audit"]
    judge = values["judge"]
    hacking = values["hacking"]
    sweep = values["sweep"]
    scale = values["scale"]
    stability = values["stability"]
    robustness = values["robustness"]
    double_ledger = values["double_ledger"]
    package = values["package"]
    reference = values["reference"]
    dpo = values["dpo"]
    dpo_eval = values["dpo_eval"]
    frozen = values["frozen"]
    formal_config = values["formal_config"]

    def all_formal(predicate: Any) -> bool:
        return all(predicate(run) for run in formal_runs)

    items = [
        KnowledgeItem(
            1,
            "RL 目标与边界",
            "目标为提升 Router 语义动作与终止决策；硬安全采用独立 Gate，不参与 Reward 权重折中。",
            {
                "formal_algorithm": all_formal(
                    lambda run: run.get("algorithm") == "trajectory_constrained_token_grpo_v2"
                ),
                "production_disabled": package.get("production_deployment_attempted") is False,
            },
            (paths["acceptance"], paths["formal_config"], paths["package"]),
        ),
        KnowledgeItem(
            2,
            "状态 State",
            "状态显式包含请求、预算、上下文、搜索历史、工具观察和 contract-gold rubric。",
            {"dataset_audit": data_audit.get("passed") is True, "states": data_audit.get("states") == 4032},
            (repo_root / "ml/agentic_platform/rl/maturity_v2/spec.py", paths["data_audit"]),
        ),
        KnowledgeItem(
            3,
            "动作 Action",
            "六类只读语义动作采用单 token 选择，安全参数由确定性 decoder 生成。",
            {
                "action_audit": action_audit.get("passed") is True,
                "candidate_actions": int(action_audit.get("candidate_actions", 0)) >= 10_000,
            },
            (repo_root / "ml/agentic_platform/rl/maturity_v2/actions.py", paths["action_audit"]),
        ),
        KnowledgeItem(
            4,
            "状态转移 Transition",
            "完整 episode 按成功动作进入 next state，错误动作提前终止，轨迹日志保留逐步 transition。",
            {
                "trajectory_logs": all(path.is_file() for path in formal_trajectories),
                "formal_runs": len(formal_runs) == 5,
            },
            (
                repo_root / "ml/agentic_platform/rl/maturity_v2/train_grpo.py",
                *formal_trajectories,
            ),
        ),
        KnowledgeItem(
            5,
            "Episode 与终止",
            "数据包含 1,908 个 episode，训练同时覆盖四步资料轨迹和单步边界轨迹。",
            {
                "episodes": data_audit.get("episodes") == 1908,
                "trajectory_success_recorded": all("trajectory_success_rate" in run for run in formal_runs),
            },
            (paths["data_audit"], *(artifact_root / f"experiments/grpo_formal/seed_{seed}/run_summary.json" for seed in SEEDS)),
        ),
        KnowledgeItem(
            6,
            "初始策略与参考策略",
            "Qwen3.5-2B SFT v1.7 为共同起点；batch=1 的冻结 reference cache 覆盖全部 Train state。",
            {
                "reference_states": reference.get("states") == 2028,
                "batch_one": reference.get("batch_size") == 1,
                "test_unread": reference.get("test_read") is False,
            },
            (paths["reference"], repo_root / "training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged/studyhub_export_manifest.json"),
        ),
        KnowledgeItem(
            7,
            "Rollout 构造",
            "五个正式 seed 均达到至少 10,000 条多步轨迹，按 group 采样并记录逐动作 rollout。",
            {
                "five_seeds": len(formal_runs) == 5,
                "minimum_rollouts": all(int(run.get("trajectory_rollouts", 0)) >= 10_000 for run in formal_runs),
            },
            tuple(artifact_root / f"experiments/grpo_formal/seed_{seed}/run_summary.json" for seed in SEEDS),
        ),
        KnowledgeItem(
            8,
            "数据划分与防泄漏",
            "Train/Validation/Test/Sealed 在 material、query、template 和 exact prompt 四维零交叉。",
            {
                "audit_passed": data_audit.get("passed") is True,
                "all_leaks_zero": all(not value for value in (data_audit.get("leaks") or {}).values()),
                "eval_not_exported": data_audit.get("training_export_allowed") == 2028,
            },
            (paths["manifest"], paths["data_audit"], paths["test_access"], paths["sealed_access"]),
        ),
        KnowledgeItem(
            9,
            "Reward 设计",
            "六项策略 Reward、终局 bonus/penalty、限幅和攻击惩罚均由可审计实现产生。",
            {"judge_passed": judge.get("passed") is True, "hacking_passed": hacking.get("passed") is True},
            (repo_root / "ml/agentic_platform/rl/reward.py", repo_root / "ml/agentic_platform/rl/maturity_v2/trajectory.py", paths["hacking"]),
        ),
        KnowledgeItem(
            10,
            "硬约束与权限边界",
            "只读工具、预算、可信 ID、页码、敏感输出和权限拒绝在 Raw ledger 中全部通过。",
            {
                "candidate_hard_gates": action_audit.get("checks", {}).get("all_raw_candidates_pass_hard_gates") is True,
                "test_hard_gates": test_gate.get("checks", {}).get("all_raw_hard_gates") is True,
                "sealed_hard_gates": sealed_gate.get("checks", {}).get("all_raw_hard_gates") is True,
            },
            (BACKEND_ROOT / "app/services/agent_router_constraint_service.py", paths["action_audit"], paths["test_gate"], paths["sealed_gate"]),
        ),
        KnowledgeItem(
            11,
            "Reward 来源与标注层级",
            "route/stop/argument 为 deterministic contract gold；开放式 utility 仅为不可覆盖 contract 的 teacher Silver。",
            {
                "contract_gold": judge.get("contract_label_tier") == "deterministic_gold",
                "silver_non_overriding": judge.get("open_ended_label_tier") == "teacher_silver_non_overriding",
            },
            (paths["judge"], paths["manifest"]),
        ),
        KnowledgeItem(
            12,
            "Judge 校准",
            "420 对 contract-gold 校准达到 100% pairwise、顺序和序列化不变，长度偏差为零。",
            {
                "passed": judge.get("passed") is True,
                "pairs": int(judge.get("cases", 0)) >= 400,
                "pairwise": float(judge.get("pairwise_accuracy", 0)) >= 0.98,
                "ordering": float(judge.get("ordering_invariance", 0)) >= 0.99,
            },
            (paths["judge"], artifact_root / "calibration/contract_gold_pairs.jsonl"),
        ),
        KnowledgeItem(
            13,
            "算法选择与对照",
            "同一起点完成 frozen SFT、DPO preference baseline 与 trajectory GRPO 三方 Validation 对照。",
            {
                "dpo_trained": dpo.get("training_succeeded") is True,
                "dpo_evaluated": dpo_eval.get("split") == "validation",
                "grpo_sweep": len(sweep.get("trials") or []) >= 11,
                "grpo_scale_sweep": len(scale.get("trials") or []) >= 5,
                "grpo_stability_sweep": len(stability.get("trials") or []) >= 7,
                "failed_scale_rejected": scale.get("gate_passed") is False
                and scale.get("selected_config") is None,
                "stability_selected": stability.get("gate_passed") is True,
            },
            (
                paths["baseline"],
                paths["dpo"],
                paths["dpo_eval"],
                paths["sweep"],
                paths["scale"],
                paths["stability"],
            ),
        ),
        KnowledgeItem(
            14,
            "Credit assignment",
            "discounted return-to-go 将 terminal 成败传回前序动作，并使用轨迹组内相对 advantage。",
            {
                "trajectory_return": all_formal(lambda run: run.get("objective", {}).get("trajectory_return_to_go") is True),
                "credit_signal": all_formal(lambda run: run.get("stability", {}).get("trajectory_credit_signal_observed") is True),
            },
            (repo_root / "ml/agentic_platform/rl/maturity_v2/trajectory.py", repo_root / "ml/agentic_platform/rl/maturity_v2/train_grpo.py"),
        ),
        KnowledgeItem(
            15,
            "KL、Entropy 与探索",
            "训练使用冻结参考策略 KL、真实全词表 entropy、动作 entropy、采样温度和更新后 policy ratio。",
            {
                "reference_kl": all_formal(lambda run: run.get("objective", {}).get("frozen_reference_kl") is True),
                "true_entropy": all_formal(lambda run: run.get("stability", {}).get("true_token_entropy_observed") is True),
                "post_ratio": all_formal(lambda run: run.get("stability", {}).get("post_update_policy_ratio_observed") is True),
            },
            (paths["formal_config"], *formal_metrics),
        ),
        KnowledgeItem(
            16,
            "Reward scaling 与 advantage",
            "Reward 分项归一、[-1,1] 限幅、终局 shaping 和组内标准化均有实现与测试。",
            {
                "group_relative": all_formal(lambda run: run.get("objective", {}).get("group_relative_advantage") is True),
                "finite": all_formal(lambda run: run.get("stability", {}).get("finite") is True),
            },
            (repo_root / "ml/agentic_platform/rl/reward.py", repo_root / "ml/agentic_platform/rl/maturity_v2/trajectory.py", BACKEND_ROOT / "tests/agentic_platform/test_router_rl_maturity_v2.py"),
        ),
        KnowledgeItem(
            17,
            "采样策略与超参数",
            "temperature、group size、LoRA、LR、KL、discount、clip 与 episode mixture 均在哈希配置中锁定。",
            {
                "rank_screen": sweep.get("required_lora_ranks_compared") is True,
                "axes_screen": sweep.get("required_hyperparameter_axes_compared") is True,
                "group_scale": scale.get("required_group_scale_compared") is True,
                "entropy_scale": scale.get("required_entropy_scale_compared") is True,
                "failed_scale_not_selected": scale.get("gate_passed") is False
                and scale.get("selected_trial") is None,
                "mixture_control": stability.get(
                    "required_mixture_control_compared"
                )
                is True,
                "decay_horizons": stability.get(
                    "required_decay_horizons_compared"
                )
                is True,
                "schedule_shapes": stability.get(
                    "required_schedule_shapes_compared"
                )
                is True,
                "stability_gate": stability.get("gate_passed") is True,
                "formal_config_matches_stability_selection": all(
                    formal_config.get(name)
                    == stability.get("selected_config", {}).get(name)
                    for name in (
                        "lora_rank",
                        "learning_rate",
                        "learning_rate_schedule",
                        "learning_rate_min_ratio",
                        "reference_kl_beta",
                        "trajectory_discount",
                        "group_size",
                        "material_episodes_per_update",
                        "boundary_episodes_per_update",
                        "entropy_beta",
                        "action_temperature",
                    )
                ),
                "formal_decay_scaled_from_screen": formal_config.get(
                    "selection_evidence", {}
                ).get("stability_trial")
                == stability.get("selected_trial")
                and formal_config.get("selection_evidence", {}).get(
                    "formal_decay_optimizer_updates"
                )
                == formal_config.get("learning_rate_decay_optimizer_updates")
                and 0
                < float(
                    formal_config.get("selection_evidence", {}).get(
                        "decay_fraction_of_screen_optimizer_updates", 0
                    )
                )
                <= 1,
            },
            (
                paths["sweep"],
                paths["scale"],
                paths["stability"],
                paths["formal_config"],
            ),
        ),
        KnowledgeItem(
            18,
            "训练稳定性",
            "五个正式 seed 均通过 500-update run Gate，记录 KL、梯度、ratio、clip、entropy、显存和 resume。",
            {
                "formal_gate": validation_gate.get("passed") is True,
                "all_training_gates": all(row.get("training_gate", {}).get("passed") is True for row in validation_gate.get("seeds") or []),
                "all_run_locks": all(
                    row.get("run_lock", {}).get("passed") is True
                    for row in validation_gate.get("seeds") or []
                ),
            },
            (paths["validation_gate"], *formal_metrics),
        ),
        KnowledgeItem(
            19,
            "Reward hacking 与策略坍缩",
            "360 条六类攻击全部识别；冻结候选通过奖励作弊率和扰动不变性 Gate。",
            {
                "hacking_suite": hacking.get("passed") is True,
                "robustness": robustness.get("passed") is True,
                "candidate_hacking_zero": test_gate.get("checks", {}).get("reward_hacking_rate") is True,
            },
            (paths["hacking"], paths["robustness"], paths["test_gate"]),
        ),
        KnowledgeItem(
            20,
            "Raw / Executable 双账本",
            "首次扰动 Gate 记录 70 条约束改路由分歧；修复后训练梯度仅使用 Raw ledger，560 条扰动及 Validation、Test、Sealed gap 均为零。",
            {
                "raw_only": all_formal(lambda run: run.get("objective", {}).get("raw_policy_reward_only") is True),
                "fix_audit": double_ledger.get("passed") is True,
                "failure_reproduced": double_ledger.get("before", {}).get(
                    "choice_divergence_cases"
                )
                == 70,
                "gap_closed": double_ledger.get("before", {}).get(
                    "raw_executable_choice_gap"
                )
                == 0.125
                and double_ledger.get("after", {}).get(
                    "raw_executable_choice_gap"
                )
                == 0.0,
                "oracle_gap_zero": action_audit.get("checks", {}).get("oracle_raw_executable_gap_zero") is True,
                "test_gap": test_gate.get("checks", {}).get("raw_executable_choice_gap") is True,
                "sealed_gap": sealed_gate.get("checks", {}).get("raw_executable_choice_gap") is True,
            },
            (
                paths["double_ledger"],
                paths["action_audit"],
                paths["validation_gate"],
                paths["test_gate"],
                paths["sealed_gate"],
            ),
        ),
        KnowledgeItem(
            21,
            "业务 Gate 与候选冻结",
            "Validation 和五种子方差用于锁定候选，随后依次执行一次 Test 和一次 Sealed 评测。",
            {
                "validation": validation_gate.get("passed") is True,
                "frozen": frozen.get("status") == "frozen_before_test",
                "test": test_gate.get("passed") is True,
                "sealed": sealed_gate.get("passed") is True,
            },
            (paths["validation_gate"], paths["frozen"], paths["test_gate"], paths["sealed_gate"]),
        ),
        KnowledgeItem(
            22,
            "鲁棒性与边界覆盖",
            "每个评测 split 的十个关键 family 各至少 30 条；冻结候选通过四类语义扰动。",
            {
                "dataset_boundaries": data_audit.get("acceptance_checks", {}).get("boundary:sealed:untrusted_observation") is True,
                "robustness": robustness.get("passed") is True,
                "family_floor": robustness.get("checks", {}).get("family_route_success") is True,
            },
            (paths["data_audit"], paths["robustness"]),
        ),
        KnowledgeItem(
            23,
            "多 Seed 与统计置信度",
            "五个独立 adapter 均通过 Validation Gate；Validation、Test 和 Sealed 使用 5,000 次 paired bootstrap。",
            {
                "five_seed": validation_gate.get("multi_seed", {}).get("passed") is True,
                "validation_bootstrap": all(
                    row.get("validation_gate", {})
                    .get("paired_bootstrap", {})
                    .get("resamples")
                    == 5000
                    for row in validation_gate.get("seeds") or []
                ),
                "test_bootstrap": test_gate.get("paired_bootstrap", {}).get("resamples") == 5000,
                "sealed_bootstrap": sealed_gate.get("paired_bootstrap", {}).get("resamples") == 5000,
            },
            (paths["validation_gate"], paths["test_gate"], paths["sealed_gate"]),
        ),
        KnowledgeItem(
            24,
            "LoRA 与显存",
            "r8/r16/r32 均完成对照；正式五 seed 记录可训练参数和 H100 峰值显存。",
            {
                "ranks": sweep.get("required_lora_ranks_compared") is True,
                "memory": all(float(run.get("gpu", {}).get("peak_memory_mib", 0)) > 0 for run in formal_runs),
                "lora": all(int(run.get("lora", {}).get("trainable_parameters", 0)) > 0 for run in formal_runs),
            },
            (paths["sweep"], *(artifact_root / f"experiments/grpo_formal/seed_{seed}/run_summary.json" for seed in SEEDS)),
        ),
        KnowledgeItem(
            25,
            "复现、哈希与治理",
            "数据、基座、reference、配置、实现、adapter、预测和 Gate 均有 SHA-256 与不可覆盖约束。",
            {
                "dataset_manifest": bool(values["manifest"].get("audit_sha256")),
                "frozen_hashes": bool(frozen.get("training_summary_sha256")) and bool(frozen.get("config_sha256")),
                "formal_config_hash": validation_gate.get("formal_config_sha256")
                == sha256_file(paths["formal_config"]),
                "acceptance_hash": validation_gate.get("acceptance_sha256")
                == sha256_file(paths["acceptance"]),
                "all_run_locks": all(
                    row.get("run_lock", {}).get("passed") is True
                    for row in validation_gate.get("seeds") or []
                ),
                "one_shot": values["test_access"].get("evaluation_runs") == 1 and values["sealed_access"].get("evaluation_runs") == 1,
            },
            (paths["manifest"], paths["reference"], paths["frozen"], paths["test_access"], paths["sealed_access"]),
        ),
        KnowledgeItem(
            26,
            "离线装载与回滚",
            "冻结 LoRA 包已本地加载，随后回滚加载 SFT v1.7；生产开关和配置哈希保持不变且从未部署。",
            {
                "package": package.get("passed") is True,
                "candidate_loaded": package.get("checks", {}).get("candidate_package_loaded") is True,
                "rollback_loaded": package.get("checks", {}).get("rollback_sft_loaded") is True,
                "config_unchanged": package.get("checks", {}).get("production_configuration_unchanged") is True,
                "not_deployed": package.get("production_deployment_attempted") is False,
            },
            (paths["package"], artifact_root / "offline_package/package_manifest.json", BACKEND_ROOT / "app/core/config.py"),
        ),
    ]
    if [item.number for item in items] != list(range(1, 27)):
        raise AssertionError("knowledge ledger must contain items 1 through 26")
    serialized = [item.to_dict() for item in items]
    result = {
        "schema_version": "studyhub.agent.router_rl.knowledge_coverage.v2",
        "passed": all(item["status"] == "VERIFIED" for item in serialized),
        "verified_items": sum(item["status"] == "VERIFIED" for item in serialized),
        "total_items": 26,
        "items": serialized,
        "production_deployment_attempted": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _paths(repo_root: Path, artifact_root: Path, evaluation_root: Path) -> dict[str, Path]:
    gate = evaluation_root / "gate"
    return {
        "acceptance": repo_root / "ml/agentic_platform/rl/configs/router_rl_maturity_v2_acceptance.json",
        "formal_config": repo_root / "ml/agentic_platform/rl/configs/router_grpo_maturity_v2_formal.json",
        "manifest": artifact_root / "manifest.json",
        "data_audit": artifact_root / "audit.json",
        "action_audit": artifact_root / "action_space_audit.json",
        "reference": artifact_root / "reference/summary.json",
        "judge": artifact_root / "calibration/judge_calibration.json",
        "hacking": artifact_root / "calibration/reward_hacking_summary.json",
        "dpo": artifact_root / "experiments/dpo_rank16/run_summary.json",
        "dpo_eval": evaluation_root / "validation/dpo_rank16/summary.json",
        "baseline": evaluation_root / "validation/baseline_sft/summary.json",
        "sweep": evaluation_root / "validation/grpo_sweep/sweep_results.json",
        "scale": evaluation_root
        / "validation/grpo_scale_sweep/scale_sweep_results.json",
        "stability": evaluation_root
        / "validation/grpo_stability_sweep/stability_sweep_results.json",
        "validation_gate": gate / "formal_validation_gate.json",
        "frozen": gate / "frozen_candidate.json",
        "robustness": evaluation_root / "validation/robustness/frozen_candidate/summary.json",
        "double_ledger": gate / "double_ledger_fix_audit.json",
        "test_gate": gate / "test_gate.json",
        "sealed_gate": gate / "sealed_gate.json",
        "test_access": gate / "test_access.json",
        "sealed_access": gate / "sealed_access.json",
        "package": artifact_root / "offline_package/load_rollback_exercise.json",
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_knowledge_coverage(
        repo_root=args.repo_root.resolve(),
        artifact_root=args.artifact_root.resolve(),
        evaluation_root=args.evaluation_root.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
