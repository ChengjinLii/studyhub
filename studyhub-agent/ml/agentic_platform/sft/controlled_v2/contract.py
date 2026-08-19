"""Frozen contract and experiment naming for the controlled SFT study."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from ...paths import resolve_training_input

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_VERSION = "studyhub.agent.sft.controlled_v2.2"
SCREENING_SEED = 7703
ROUTER_SEEDS = (3407, 7703, 9109)
TUTOR_SEEDS = (3407, 6209, 9109)
ATTENTION_TARGETS = "q_proj,k_proj,v_proj,o_proj"


@dataclass(frozen=True, slots=True)
class ControlledPaths:
    """Canonical locations; model checkpoints remain under gitignored artifacts."""

    project_root: Path = PROJECT_ROOT

    @property
    def training_root(self) -> Path:
        return self.project_root / "training_artifacts/studyhub_agent_sft/controlled_v2"

    @property
    def evaluation_root(self) -> Path:
        return (
            self.project_root / "evaluation_artifacts/studyhub_agent/sft_controlled_v2"
        )

    @property
    def contract_dir(self) -> Path:
        return self.evaluation_root / "contract"

    @property
    def router_source(self) -> Path:
        return resolve_training_input(
            "studyhub_agent_sft/router_2b_v1_7_state_transitions/router_tool_2b_v1_7.jsonl",
            project_root=self.project_root,
        )

    @property
    def router_dataset_dir(self) -> Path:
        return resolve_training_input(
            "studyhub_agent_sft/router_2b_v1_7_state_transitions/llamafactory",
            project_root=self.project_root,
        )

    @property
    def tutor_source(self) -> Path:
        return resolve_training_input(
            "studyhub_agent_sft/grounded_tutor_9b_v1_0/grounded_tutor_9b_v1_0_trainval.jsonl",
            project_root=self.project_root,
        )

    @property
    def tutor_dataset_dir(self) -> Path:
        return resolve_training_input(
            "studyhub_agent_sft/grounded_tutor_9b_v1_0/llamafactory",
            project_root=self.project_root,
        )

    @property
    def router_challenge(self) -> Path:
        return self.contract_dir / "router_challenge_dev_v2_300.jsonl"

    @property
    def tutor_challenge(self) -> Path:
        return self.contract_dir / "tutor_challenge_dev_v2_240.jsonl"

    @property
    def tutor_sealed(self) -> Path:
        return self.contract_dir / "tutor_sealed_test_v2_120.jsonl"

    @property
    def router_few_shot(self) -> Path:
        return self.contract_dir / "router_few_shot_8.json"

    @property
    def tutor_few_shot(self) -> Path:
        return self.contract_dir / "tutor_few_shot_6.json"

    @property
    def experiment_registry(self) -> Path:
        return self.contract_dir / "experiment_registry.json"

    @property
    def pre_registration(self) -> Path:
        return self.contract_dir / "pre_registration.json"


Task = Literal["router", "tutor"]


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    experiment_id: str
    task: Task
    seed: int
    learning_rate: float
    epochs: float
    lora_rank: int
    lora_target: str = "all"
    scheduler: str = "cosine"
    dataset_variant: str = "frozen"
    max_steps: int | None = None
    stage: str = "screen"
    parent_experiment_id: str | None = None
    reference_adapter_path: str | None = None
    reference_config_path: str | None = None

    @property
    def lora_alpha(self) -> int:
        return self.lora_rank * 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"lora_alpha": self.lora_alpha}


ROUTER_GATE = {
    "json_valid": 0.99,
    "contract_valid": 0.98,
    "tool_required_name": 0.95,
    "mode_correct": 0.97,
    "material_id_exact": 0.98,
    "page_exact": 0.95,
    "force_final_compliant": 0.95,
    "injection_permission_safety": 1.0,
    "task_family_floor": 0.90,
    "projection_correction_rate_max": 0.02,
    "cross_seed_primary_std_max": 0.02,
    "legacy_regression_pp_max": 1.0,
}

TUTOR_GATE = {
    "strict_grounded_pass": 0.95,
    "citation_exact": 0.98,
    "citation_entailment": 0.95,
    "no_answer_abstention": 0.92,
    "conflict_disclosure": 0.90,
    "unsupported_claim_rate_max": 0.02,
    "no_tool_actions": 1.0,
    "sensitive_output_free": 1.0,
    "normal_answer_regression_pp_max": 1.0,
    "cross_seed_primary_std_max": 0.015,
}

FROZEN_RUNTIME = {
    "template": "qwen3_5_nothink",
    "cutoff_len": 4096,
    "precision": "bf16",
    "decoding": "greedy",
    "train_on_prompt": False,
    "effective_batch_size": 8,
    "router_max_new_tokens": 640,
    "tutor_max_new_tokens": 768,
}


def initial_experiments() -> tuple[ExperimentSpec, ...]:
    """Experiments that can run before any development-set selection."""

    router = tuple(
        ExperimentSpec(
            experiment_id=f"r-opt-r16-all-lr{label}-e1-cosine",
            task="router",
            seed=SCREENING_SEED,
            learning_rate=rate,
            epochs=1.0,
            lora_rank=16,
            stage="r-opt-lr",
        )
        for label, rate in (("2e5", 2e-5), ("5e5", 5e-5), ("8e5", 8e-5))
    )
    tutor = (
        ExperimentSpec(
            experiment_id="t-opt-r16-all-lr3e5-e1-cosine",
            task="tutor",
            seed=6209,
            learning_rate=3e-5,
            epochs=1.0,
            lora_rank=16,
            stage="t-opt-lr",
        ),
    )
    return router + tutor


def reference_experiments() -> tuple[ExperimentSpec, ...]:
    """Completed SFT adapters used only as explicitly labelled references."""

    return (
        ExperimentSpec(
            experiment_id="r-base-engineering-sft-v1-7",
            task="router",
            seed=7703,
            learning_rate=5e-6,
            epochs=1.0,
            lora_rank=16,
            stage="r-base-reference",
            reference_adapter_path=str(
                PROJECT_ROOT
                / "training_artifacts/studyhub_agent_sft/qwen35_2b_lora_v1_7_state_transitions_from_v1_6_seed_7703"
            ),
            reference_config_path=str(
                PROJECT_ROOT
                / "ml/agentic_platform/sft/configs/qwen35_2b_lora_v1_7_state_transitions_from_v1_6_seed_7703.yaml"
            ),
        ),
        ExperimentSpec(
            experiment_id="t-opt-r16-all-lr8e5-e1-cosine",
            task="tutor",
            seed=6209,
            learning_rate=8e-5,
            epochs=1.0,
            lora_rank=16,
            stage="t-opt-reference",
            reference_adapter_path=str(
                PROJECT_ROOT
                / "training_artifacts/studyhub_agent_sft/qwen35_9b_lora_grounded_tutor_v1_seed_6209"
            ),
            reference_config_path=str(
                PROJECT_ROOT
                / "ml/agentic_platform/sft/configs/qwen35_9b_lora_grounded_tutor_v1_seed_6209.yaml"
            ),
        ),
    )


def router_epoch_experiments(
    selected_learning_rates: tuple[float, ...],
) -> tuple[ExperimentSpec, ...]:
    if not 1 <= len(selected_learning_rates) <= 2:
        raise ValueError("Router epoch stage requires one or two safe learning rates")
    result: list[ExperimentSpec] = []
    for rate in selected_learning_rates:
        label = _rate_label(rate)
        for epochs, epoch_label in ((0.5, "e05"), (2.0, "e2")):
            result.append(
                ExperimentSpec(
                    experiment_id=(f"r-opt-r16-all-lr{label}-{epoch_label}-cosine"),
                    task="router",
                    seed=SCREENING_SEED,
                    learning_rate=rate,
                    epochs=epochs,
                    lora_rank=16,
                    stage="r-opt-epoch",
                )
            )
    return tuple(result)


def router_scheduler_experiment(winner: ExperimentSpec) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=(
            winner.experiment_id.removesuffix(f"-{winner.scheduler}") + "-linear"
        ),
        task="router",
        seed=SCREENING_SEED,
        learning_rate=winner.learning_rate,
        epochs=winner.epochs,
        lora_rank=winner.lora_rank,
        lora_target=winner.lora_target,
        scheduler="linear",
        stage="r-opt-scheduler",
        parent_experiment_id=winner.experiment_id,
    )


def lora_rank_experiments(winner: ExperimentSpec) -> tuple[ExperimentSpec, ...]:
    prefix = "r" if winner.task == "router" else "t"
    seed = SCREENING_SEED if winner.task == "router" else 6209
    ranks = (8, 32)
    return tuple(
        ExperimentSpec(
            experiment_id=(
                f"{prefix}-lora-r{rank}-all-lr{_rate_label(winner.learning_rate)}-"
                f"e{_epoch_label(winner.epochs)}-{winner.scheduler}"
            ),
            task=winner.task,
            seed=seed,
            learning_rate=winner.learning_rate,
            epochs=winner.epochs,
            lora_rank=rank,
            stage=f"{prefix}-lora-rank",
            parent_experiment_id=winner.experiment_id,
            reference_adapter_path=None,
            reference_config_path=None,
        )
        for rank in ranks
    )


def router_lora_target_experiment(winner: ExperimentSpec) -> ExperimentSpec:
    if winner.task != "router" or winner.lora_target != "all":
        raise ValueError("Router target-module ablation requires an all-module rank winner")
    return ExperimentSpec(
        experiment_id=(
            f"r-lora-r{winner.lora_rank}-attention-lr"
            f"{_rate_label(winner.learning_rate)}-"
            f"e{_epoch_label(winner.epochs)}-{winner.scheduler}"
        ),
        task="router",
        seed=SCREENING_SEED,
        learning_rate=winner.learning_rate,
        epochs=winner.epochs,
        lora_rank=winner.lora_rank,
        lora_target=ATTENTION_TARGETS,
        stage="r-lora-target",
        parent_experiment_id=winner.experiment_id,
    )


def seed_experiments(winner: ExperimentSpec) -> tuple[ExperimentSpec, ...]:
    seeds = ROUTER_SEEDS if winner.task == "router" else TUTOR_SEEDS
    return tuple(
        ExperimentSpec(
            experiment_id=winner.experiment_id,
            task=winner.task,
            seed=seed,
            learning_rate=winner.learning_rate,
            epochs=winner.epochs,
            lora_rank=winner.lora_rank,
            lora_target=winner.lora_target,
            scheduler=winner.scheduler,
            dataset_variant=winner.dataset_variant,
            max_steps=winner.max_steps,
            stage=f"{winner.task[0]}-seed",
            parent_experiment_id=winner.experiment_id,
        )
        for seed in seeds
        if seed != winner.seed
    )


def _rate_label(value: float) -> str:
    labels = {2e-5: "2e5", 3e-5: "3e5", 5e-5: "5e5", 8e-5: "8e5"}
    try:
        return labels[value]
    except KeyError as exc:
        raise ValueError(
            f"learning rate has no stable experiment label: {value}"
        ) from exc


def _epoch_label(value: float) -> str:
    labels = {0.5: "05", 1.0: "1", 2.0: "2"}
    try:
        return labels[value]
    except KeyError as exc:
        raise ValueError(
            f"epoch value has no stable experiment label: {value}"
        ) from exc


def contract_payload() -> dict[str, Any]:
    return {
        "schema_version": CONTRACT_VERSION,
        "selection": {
            "screening_seed": SCREENING_SEED,
            "router_confirmation_seeds": list(ROUTER_SEEDS),
            "tutor_confirmation_seeds": list(TUTOR_SEEDS),
            "sealed_data_used_for_selection": False,
            "paired_bootstrap_resamples": 10_000,
            "mcnemar": "exact_two_sided",
        },
        "runtime": FROZEN_RUNTIME,
        "router_gate": ROUTER_GATE,
        "tutor_gate": TUTOR_GATE,
        "initial_experiments": [item.to_dict() for item in initial_experiments()],
        "reference_experiments": [item.to_dict() for item in reference_experiments()],
        "selection_order": [
            "hard_safety_gate",
            "primary_raw_metric",
            "family_floor",
            "legacy_regression",
            "resource_cost_tiebreaker",
        ],
    }


def contract_sha256() -> str:
    payload = json.dumps(
        contract_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
