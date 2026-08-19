"""Generate fresh-base LLaMA-Factory configs for controlled-v2 arms."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .contract import ControlledPaths, ExperimentSpec, initial_experiments

ROUTER_MODEL = Path("/data/chengjin/studyhub/models/P0/Qwen3.5-2B")
TUTOR_MODEL = Path("/data/chengjin/studyhub/models/P1/Qwen3.5-9B")


def config_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return (
        paths.project_root
        / "ml/agentic_platform/sft/configs/controlled_v2"
        / spec.task
        / spec.experiment_id
        / f"seed_{spec.seed}.yaml"
    )


def output_dir(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return paths.training_root / spec.task / spec.experiment_id / str(spec.seed)


def _config(paths: ControlledPaths, spec: ExperimentSpec) -> dict[str, Any]:
    is_router = spec.task == "router"
    if spec.dataset_variant == "frozen":
        dataset_dir = paths.router_dataset_dir if is_router else paths.tutor_dataset_dir
    else:
        dataset_dir = (
            paths.training_root
            / "datasets"
            / spec.task
            / spec.dataset_variant
            / "llamafactory"
        )
    model = ROUTER_MODEL if is_router else TUTOR_MODEL
    dataset_prefix = "studyhub_router_2b" if is_router else "studyhub_grounded_tutor_9b"
    config: dict[str, Any] = {
        "model_name_or_path": str(model),
        "trust_remote_code": True,
        "use_v1_kernels": False,
        "stage": "sft",
        "do_train": True,
        "finetuning_type": "lora",
        "lora_rank": spec.lora_rank,
        "lora_alpha": spec.lora_alpha,
        "lora_dropout": 0.05,
        "lora_target": spec.lora_target,
        "freeze_vision_tower": True,
        "freeze_multi_modal_projector": True,
        "dataset": f"{dataset_prefix}_train",
        "eval_dataset": f"{dataset_prefix}_validation",
        "dataset_dir": str(dataset_dir),
        "template": "qwen3_5_nothink",
        "cutoff_len": 4096,
        "overwrite_cache": True,
        "preprocessing_num_workers": 8,
        "dataloader_num_workers": 4,
        "train_on_prompt": False,
        "mask_history": False,
        "packing": False,
        "output_dir": str(output_dir(paths, spec)),
        "logging_steps": 5 if is_router else 2,
        "save_strategy": "epoch",
        "save_total_limit": 3,
        "plot_loss": True,
        "overwrite_output_dir": False,
        "save_only_model": False,
        "report_to": "none",
        "per_device_train_batch_size": 2 if is_router else 1,
        "gradient_accumulation_steps": 4 if is_router else 8,
        "learning_rate": spec.learning_rate,
        "num_train_epochs": spec.epochs,
        "lr_scheduler_type": spec.scheduler,
        "warmup_ratio": 0.05,
        "bf16": True,
        "gradient_checkpointing": True,
        "ddp_timeout": 1800,
        "seed": spec.seed,
        "data_seed": spec.seed,
        "resume_from_checkpoint": None,
        "per_device_eval_batch_size": 4 if is_router else 1,
        "eval_strategy": "epoch",
        "compute_accuracy": True,
    }
    if spec.max_steps is not None:
        config["max_steps"] = spec.max_steps
    return config


def generate_configs(
    specs: Iterable[ExperimentSpec],
    *,
    paths: ControlledPaths | None = None,
) -> list[dict[str, Any]]:
    paths = paths or ControlledPaths()
    generated: list[dict[str, Any]] = []
    for spec in specs:
        if spec.reference_adapter_path is not None:
            raise ValueError(
                "reference experiments do not generate new training configs"
            )
        destination = config_path(paths, spec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = _config(paths, spec)
        rendered = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        if destination.exists() and destination.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(
                f"frozen config differs from requested spec: {destination}"
            )
        destination.write_text(rendered, encoding="utf-8")
        generated.append(
            {
                "spec": spec.to_dict(),
                "config_path": str(destination),
                "output_dir": str(output_dir(paths, spec)),
            }
        )
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=ControlledPaths().project_root
    )
    parser.add_argument(
        "--initial", action="store_true", help="generate Batch 02/04 initial arms"
    )
    args = parser.parse_args()
    if not args.initial:
        parser.error("select an explicit config set, currently: --initial")
    result = generate_configs(
        initial_experiments(),
        paths=ControlledPaths(project_root=args.project_root),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
