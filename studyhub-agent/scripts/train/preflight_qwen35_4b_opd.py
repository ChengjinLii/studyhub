#!/usr/bin/env python3
"""Fail-closed preflight for strict two-H100 Qwen3.5 4B <- 9B OPD."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def inventory_sha256(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def gpu_state(gpus: str) -> dict[str, Any]:
    rows = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            gpus,
            "--query-gpu=index,memory.free,memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    processes = subprocess.run(
        [
            "nvidia-smi",
            "-i",
            gpus,
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {
        "gpus": [
            {
                "index": int(values[0]),
                "memory_free_mib": int(values[1]),
                "memory_used_mib": int(values[2]),
                "utilization_gpu_pct": int(values[3]),
            }
            for row in rows
            if (values := [part.strip() for part in row.split(",")])
        ],
        "compute_pids": [int(value.strip()) for value in processes if value.strip().isdigit()],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("lr1e6", "lr3e6", "pilot", "formal"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--learning-rate", type=float, required=True)
    parser.add_argument("--updates", type=int, required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--lr-selection", type=Path)
    parser.add_argument("--pilot-marker", type=Path)
    parser.add_argument("--gpus", default="0,1")
    parser.add_argument("--min-free-mib", type=int, default=76000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from areal.api.cli_args import load_expr_config

    from datasets import load_from_disk
    from training.opd.config import StudyHubOPDConfig

    authorization = load_json(args.authorization)
    if authorization.get("status") != "AUTHORIZED_PENDING_LR_PILOTS":
        raise RuntimeError("OPD is not authorized")
    if authorization.get("scope", {}).get("no_spark") is not True:
        raise RuntimeError("OPD authorization does not exclude Spark")
    expected_lr = {"lr1e6": 1.0e-6, "lr3e6": 3.0e-6}
    if args.mode in expected_lr and args.learning_rate != expected_lr[args.mode]:
        raise RuntimeError("LR pilot learning rate drift")
    expected_updates = {
        "lr1e6": 16,
        "lr3e6": 16,
        "pilot": 64,
        "formal": 300,
    }
    expected_batch = {"lr1e6": 2, "lr3e6": 2, "pilot": 4, "formal": 8}
    if args.updates != expected_updates[args.mode] or args.batch_size != expected_batch[args.mode]:
        raise RuntimeError("OPD mode budget drift")

    overrides = [
        "--config",
        str(args.config),
        f"actor.optimizer.lr={args.learning_rate}",
        f"total_train_steps={args.updates}",
        f"train_dataset.batch_size={args.batch_size}",
        f"rollout.consumer_batch_size={args.batch_size}",
    ]
    config, _ = load_expr_config(overrides, StudyHubOPDConfig)
    pool = Path(config.environment_root).resolve()
    sglang_overlay = Path(config.sglang.model_path).resolve()
    paths = {
        "program_sha256": args.program,
        "config_sha256": args.config,
        "opd_upstream_lock_sha256": PROJECT_ROOT / "training/opd/upstream.lock.json",
        "opd_runtime_sha256": PROJECT_ROOT / "training/opd/areal_runtime.py",
        "runtime_sitecustomize_sha256": PROJECT_ROOT / "training/runtime_shims/sitecustomize.py",
        "opd_parity_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-opd-token-reward-parity.json",
        "prompt_pool_manifest_sha256": pool / "manifest.json",
        "prompt_pool_train_sha256": pool / "tasks/train.jsonl",
        "prompt_pool_dev_sha256": pool / "tasks/validation.jsonl",
        "prompt_pool_train_verifiers_sha256": pool / "verifiers/train.jsonl",
        "prompt_pool_dev_verifiers_sha256": pool / "verifiers/validation.jsonl",
        "teacher_novelty_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-opd-teacher-novelty.json",
        "tokenizer_parity_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-9b-tokenizer-parity.json",
        "thinking_contract_sha256": PROJECT_ROOT / "docs/training/evidence/qwen35-4b-9b-thinking-contract.json",
        "benchmark_manifest_sha256": PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json",
        "areal_lock_sha256": PROJECT_ROOT / "training/areal/upstream.lock.json",
        "hermes_lock_sha256": PROJECT_ROOT / "integrations/hermes/upstream.lock.json",
        "m2_completion_sha256": Path(
            authorization["lineage"].get(
                "m2_completion_path",
                "/data/chengjin/studyhub/studyhub-agent/artifacts/areal/checkpoints/"
                "chengjin/studyhub-qwen35-4b-codex-sft2/"
                "qwen35-4b-sft2-formal-r32-seed-20260827/"
                "QWEN35_4B_SFT2_COMPLETE.json",
            )
        ),
        "teacher_download_manifest_sha256": Path(config.teacher.path) / "studyhub_download_manifest.json",
        "teacher_config_sha256": Path(config.teacher.path) / "config.json",
        "teacher_index_sha256": Path(config.teacher.path) / "model.safetensors.index.json",
        "sglang_overlay_config_sha256": sglang_overlay / "config.json",
        "sglang_overlay_manifest_sha256": sglang_overlay / "studyhub_sglang_overlay_manifest.json",
    }
    lineage = authorization["lineage"]
    drift = {
        key: {
            "authorized": lineage.get(key),
            "actual": sha256(path) if path.is_file() else "MISSING",
        }
        for key, path in paths.items()
        if not path.is_file() or lineage.get(key) != sha256(path)
    }
    if drift:
        raise RuntimeError(f"OPD lineage drift: {drift}")
    parity = load_json(paths["opd_parity_sha256"])
    pool_manifest = load_json(paths["prompt_pool_manifest_sha256"])
    novelty = load_json(paths["teacher_novelty_sha256"])
    tokenizer = load_json(paths["tokenizer_parity_sha256"])
    thinking = load_json(paths["thinking_contract_sha256"])
    m2 = load_json(paths["m2_completion_sha256"])
    overlay_manifest = load_json(paths["sglang_overlay_manifest_sha256"])
    if parity.get("status") != "PASS_OPD_COMPATIBILITY_SPIKE":
        raise RuntimeError("OPD mathematical parity drift")
    if pool_manifest.get("status") != "PASS_TEACHER_ALIGNED_SELECTION":
        raise RuntimeError("OPD prompt pool is not teacher-aligned")
    if novelty.get("status") != "PASS_TEACHER_NOVELTY":
        raise RuntimeError("teacher novelty gate drift")
    if tokenizer.get("canonical_opd_allowed") is not True or thinking.get("enable_thinking") is not False:
        raise RuntimeError("tokenizer/thinking compatibility drift")
    if m2.get("status") != "COMPLETE":
        raise RuntimeError("M2 completion drift")
    if Path(str(overlay_manifest.get("base_model", ""))).resolve() != Path(config.actor.path).resolve() or lineage.get(
        "sglang_overlay_path"
    ) != str(sglang_overlay):
        raise RuntimeError("SGLang overlay base-model lineage drift")
    expected_overlay_fields = {
        "vocab_size",
        "hidden_size",
        "num_hidden_layers",
        "intermediate_size",
        "num_attention_heads",
        "num_key_value_heads",
        "head_dim",
    }
    if set(overlay_manifest.get("mapped_text_config_fields", {})) != expected_overlay_fields:
        raise RuntimeError("SGLang overlay LoRA config contract drift")
    m2_adapter = Path(lineage["m2_adapter_path"]).resolve()
    if (
        os.environ.get("STUDYHUB_AREAL_OPD_BRIDGE") != "1"
        or Path(os.environ.get("STUDYHUB_OPD_STUDENT_ADAPTER", "")).resolve() != m2_adapter
        or sha256(m2_adapter / "adapter_model.safetensors") != lineage["m2_adapter_sha256"]
    ):
        raise RuntimeError("OPD student is not initialized from the locked M2 adapter")

    recipe = authorization["recipe"]
    actual_recipe = {
        "algorithm": config.opd_algorithm,
        "top_k": config.opd_top_k,
        "top_k_strategy": config.opd_top_k_strategy,
        "reward_weight": config.opd_reward_weight_mode,
        "loss_aggregation": config.opd_loss_aggregation,
        "student_temperature": config.opd_student_temperature,
        "teacher_temperature": config.opd_teacher_temperature,
        "reference_kl": config.actor.kl_ctl,
        "responses_per_prompt": config.gconfig.n_samples,
        "student_backend": config.actor.backend,
        "rollout_backend": config.rollout.backend,
        "teacher_backend": config.teacher.train.backend,
        "lora_rank": config.actor.lora_rank,
        "lora_alpha": config.actor.lora_alpha,
        "target_modules": list(config.actor.target_modules),
        "max_context_tokens": config.gconfig.max_tokens,
        "max_assistant_tokens": config.gconfig.max_new_tokens,
        "max_turns": config.max_turns,
        "seed": config.seed,
    }
    mismatch = {
        key: {"expected": recipe[key], "actual": actual}
        for key, actual in actual_recipe.items()
        if recipe.get(key) != actual
    }
    if mismatch:
        raise RuntimeError(f"strict OPD recipe drift: {mismatch}")
    if config.ref is not None or config.teacher.rl_loss_weight != 0.0:
        raise RuntimeError("OPD teacher/reference role isolation failed")
    if config.environment_root != str(pool) or Path(config.verifier_root).resolve() != (pool / "verifiers"):
        raise RuntimeError("OPD Hermes environment path drift")
    dataset = load_from_disk(Path(config.train_dataset.path))
    if len(dataset["train"]) != int(pool_manifest["train_rows"]) or len(dataset["validation"]) != int(
        pool_manifest["validation_rows"]
    ):
        raise RuntimeError("OPD DatasetDict differs from its prompt-pool manifest")
    tasks_by_split = {
        "train": load_jsonl(pool / "tasks/train.jsonl"),
        "validation": load_jsonl(pool / "tasks/validation.jsonl"),
    }
    verifiers_by_split = {
        "train": load_jsonl(pool / "verifiers/train.jsonl"),
        "validation": load_jsonl(pool / "verifiers/validation.jsonl"),
    }
    environment_paths: set[Path] = set()
    for split, tasks in tasks_by_split.items():
        verifiers = {str(row["task_id"]): row for row in verifiers_by_split[split]}
        if len(verifiers) != len(tasks):
            raise RuntimeError(f"OPD {split} task/verifier cardinality mismatch")
        for task in tasks:
            task_id = str(task["task_id"])
            verifier_id = str(task["metadata"]["verifier_id"])
            verifier = verifiers.get(task_id)
            environment_path = pool / "environments" / f"{task['environment_id']}.json"
            if verifier is None or str(verifier.get("verifier_id")) != verifier_id or not environment_path.is_file():
                raise RuntimeError(f"OPD runtime fixture mapping failed: {task_id}")
            environment = load_json(environment_path)
            if str(environment.get("task_id")) != task_id:
                raise RuntimeError(f"OPD environment identity mismatch: {task_id}")
            environment_paths.add(environment_path)
    pool_lineage = pool_manifest.get("lineage", {})
    runtime_packaging = pool_manifest.get("runtime_packaging", {})
    if (
        runtime_packaging.get("task_verifier_environment_mapping_complete") is not True
        or int(runtime_packaging.get("train_verifiers", -1)) != len(tasks_by_split["train"])
        or int(runtime_packaging.get("validation_verifiers", -1)) != len(tasks_by_split["validation"])
        or int(runtime_packaging.get("environments", -1)) != len(environment_paths)
        or pool_lineage.get("train_verifiers_sha256") != sha256(pool / "verifiers/train.jsonl")
        or pool_lineage.get("validation_verifiers_sha256") != sha256(pool / "verifiers/validation.jsonl")
        or pool_lineage.get("environment_inventory_sha256") != inventory_sha256(list(environment_paths), pool)
    ):
        raise RuntimeError("OPD runtime packaging lineage drift")

    if args.mode in {"pilot", "formal"}:
        if args.lr_selection is None or not args.lr_selection.is_file():
            raise RuntimeError("OPD pilot/formal requires frozen LR selection evidence")
        selection = load_json(args.lr_selection)
        if (
            selection.get("status") != "PASS_OPD_LR_SELECTION"
            or float(selection["selected_learning_rate"]) != args.learning_rate
        ):
            raise RuntimeError("OPD learning rate differs from pilot selection")
    if args.mode == "formal":
        if args.pilot_marker is None or not args.pilot_marker.is_file():
            raise RuntimeError("formal OPD requires a passing 64-update pilot")
        marker = load_json(args.pilot_marker)
        if (
            marker.get("status") != "OPD_PILOT_PASS"
            or marker.get("authorization_sha256") != sha256(args.authorization)
            or float(marker.get("learning_rate", -1)) != args.learning_rate
        ):
            raise RuntimeError("OPD pilot marker drift")

    state = gpu_state(args.gpus)
    if len(state["gpus"]) != 2 or state["compute_pids"]:
        raise RuntimeError(f"strict OPD requires two idle GPUs: {state}")
    low_memory = [row for row in state["gpus"] if row["memory_free_mib"] < args.min_free_mib]
    if low_memory:
        raise RuntimeError(f"requested GPUs do not meet memory gate: {low_memory}")
    print(
        json.dumps(
            {
                "schema_version": "studyhub.qwen35-4b-opd-preflight.v1",
                "status": "PASS",
                "mode": args.mode,
                "learning_rate": args.learning_rate,
                "updates": args.updates,
                "batch_size": args.batch_size,
                "student": "M2",
                "teacher": "Qwen3.5-9B frozen token scorer",
                "prompt_pool": {
                    "train": len(dataset["train"]),
                    "validation": len(dataset["validation"]),
                },
                "sealed_used": False,
                "gpu_state": state,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
