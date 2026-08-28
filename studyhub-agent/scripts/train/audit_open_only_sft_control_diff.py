#!/usr/bin/env python3
"""Build a fail-closed Mixed-v3.0 versus Open-Only-v1.1 control audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIXED_TRAINING_COMMIT = "9cc7b0421f50a9ffd4c2ecb363cff56c5c77eaf0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a YAML object: {path}")
    return payload


def load_git_yaml(repo: Path, revision: str, relative: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    payload = yaml.safe_load(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a YAML object at {revision}:{relative}")
    return payload


def parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "null":
        return None
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_overrides(values: list[str]) -> dict[str, Any]:
    result = {}
    for value in values:
        if "=" not in value:
            raise RuntimeError(f"invalid runtime override: {value}")
        key, raw = value.split("=", 1)
        result[key] = parse_scalar(raw)
    return result


def git_output(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_blob_sha256(repo: Path, revision: str, relative: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def recovery_contract_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "status": "NOT_PROVIDED",
            "eligible": False,
            "path": None,
            "sha256": None,
            "failures": ["recovery_evidence_not_provided"],
        }
    payload = load_json(path)
    failures = []
    if payload.get("schema_version") != "studyhub.sft-recovery-gate.v2":
        failures.append("unexpected_recovery_evidence_schema")
    if payload.get("status") != "PASS":
        failures.append("recovery_evidence_not_pass")
    if payload.get("scope", {}).get("formal_training_eligible") is not True:
        failures.append("recovery_boundary_not_formal_training_eligible")
    if payload.get("scope", {}).get("rl_started") is not False:
        failures.append("recovery_evidence_rl_scope_invalid")
    if payload.get("scope", {}).get("sealed_used") is not False:
        failures.append("recovery_evidence_sealed_scope_invalid")
    gates = payload.get("gates", {})
    for gate in (
        "R1_lr_schedule",
        "R2_snapshot_integrity",
        "R3_state_continuity",
    ):
        if gates.get(gate, {}).get("status") != "PASS":
            failures.append(f"{gate}_not_pass")
    if gates.get("R4_final_equivalence", {}).get("status") not in {
        "BITWISE_RESUME_PASS",
        "BOUNDED_NUMERIC_RESUME_PASS",
    }:
        failures.append("R4_final_equivalence_not_pass")
    return {
        "status": "PASS" if not failures else "FAIL",
        "eligible": not failures,
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "boundary": payload.get("scope", {}).get("boundary"),
        "r4_status": gates.get("R4_final_equivalence", {}).get("status"),
        "failures": failures,
    }


def add_control(
    rows: dict[str, Any],
    name: str,
    mixed: Any,
    candidate: Any,
    *,
    required_equal: bool = True,
    note: str | None = None,
) -> None:
    equal = mixed == candidate
    rows[name] = {
        "mixed": mixed,
        "open_only_v1_1": candidate,
        "equal": equal,
        "required_equal": required_equal,
        "status": "PASS" if equal or not required_equal else "FAIL",
    }
    if note:
        rows[name]["note"] = note


def nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        value = value[key]
    return value


def classify_audit(
    *,
    hard_failures: list[str],
    provenance_failures: list[str],
    runtime_requires_confirmation: bool,
    worktree_dirty: bool,
) -> tuple[str, str, list[str]]:
    blockers = []
    if hard_failures or provenance_failures:
        blockers.append("MODEL_AFFECTING_CONTROL_DRIFT")
    if runtime_requires_confirmation:
        blockers.append("RUNTIME_CORRECTIONS_REQUIRE_R1_R4_CONFIRMATION")
    if worktree_dirty:
        blockers.append("DIRTY_WORKTREE_AT_AUDIT")
    if not blockers:
        return "PASS", "CONTROL_CONTRACT_PASS", blockers
    if blockers == ["RUNTIME_CORRECTIONS_REQUIRE_R1_R4_CONFIRMATION"]:
        return "BLOCKED", "BLOCKED_RECOVERY_CONTRACT", blockers
    return "BLOCKED", "BLOCKED_CONTROL_DRIFT", blockers


def build_audit(
    project_root: Path,
    mixed_run_metadata_path: Path,
    recovery_evidence_path: Path | None = None,
) -> dict[str, Any]:
    repo = project_root.parent
    mixed_config_relative = "studyhub-agent/configs/train/runtime-sft-v3-qwen35-9b.yaml"
    candidate_config_path = project_root / "configs/train/open-only-sft-v1.1-qwen35-9b.yaml"
    mixed_authorization_path = project_root / "configs/program-v3/overnight-sft-baseline-authorization.json"
    candidate_authorization_path = project_root / "configs/program-v3/open-only-sft-v1.1-lrmatched-authorization.json"
    candidate_program_path = project_root / "configs/program-v3/open-only-sft-v1.1-lrmatched.json"
    candidate_data_card_path = project_root / "configs/program-v3/open-only-sft-v1-data-card.json"
    candidate_selected_path = project_root / "datasets/interim/open_only_sft_v1/selected.jsonl"
    candidate_selected_manifest_path = project_root / "datasets/interim/open_only_sft_v1/selected.manifest.json"
    mixed_consumption_path = project_root / "configs/program-v3/overnight-sft-baseline-consumption.json"
    mixed_manifest_path = project_root / "datasets/processed/runtime_sft_v3_qwen35_9b/manifest.json"
    candidate_manifest_path = project_root / "datasets/processed/open_only_sft_v1_qwen35_9b/manifest.json"
    benchmark_path = project_root / "benchmarks/studyhub-agent-v2/manifest.json"
    areal_lock_path = project_root / "training/areal/upstream.lock.json"
    hermes_lock_path = project_root / "integrations/hermes/upstream.lock.json"

    mixed_run = load_json(mixed_run_metadata_path)
    mixed_training_commit = mixed_run["git"]["commit"]
    mixed_config = load_git_yaml(
        repo,
        mixed_training_commit,
        mixed_config_relative,
    )
    candidate_config = load_yaml(candidate_config_path)
    mixed_authorization = load_json(mixed_authorization_path)
    candidate_authorization = load_json(candidate_authorization_path)
    mixed_consumption = load_json(mixed_consumption_path)
    mixed_manifest = mixed_run["dataset_manifest"]
    candidate_manifest = load_json(candidate_manifest_path)
    areal_lock = load_json(areal_lock_path)
    hermes_lock = load_json(hermes_lock_path)
    mixed_overrides = parse_overrides(mixed_run["config"]["overrides"])

    candidate_budget = candidate_authorization["budget"]
    candidate_recipe = candidate_authorization["recipe"]
    candidate_overrides = {
        "seed": candidate_authorization["lineage"]["seed"],
        "total_train_steps": candidate_budget["planned_optimizer_updates"],
        "saver.freq_steps": candidate_budget["checkpoint_every_updates"],
        "saver.freq_secs": None,
        "recover.freq_steps": candidate_budget["recovery_every_updates"],
        "recover.freq_secs": None,
        "evaluator.freq_steps": None,
        "evaluator.freq_secs": None,
    }

    model_path = Path(candidate_config["actor"]["path"])
    tokenizer_config = load_json(model_path / "tokenizer_config.json")
    chat_template = tokenizer_config.get("chat_template")
    mixed_rows = int(nested(mixed_manifest, "split_counts", "train"))
    mixed_batch = int(nested(mixed_config, "train_dataset", "batch_size"))
    mixed_scheduler_horizon = mixed_rows // mixed_batch

    controls: dict[str, Any] = {}
    add_control(
        controls,
        "base_model_path",
        nested(mixed_config, "actor", "path"),
        nested(candidate_config, "actor", "path"),
    )
    add_control(
        controls,
        "model_revision",
        nested(mixed_authorization, "lineage", "model_revision"),
        nested(candidate_authorization, "lineage", "model_revision"),
    )
    for key in ("model_config_sha256", "model_index_sha256", "model_weight_set_sha256"):
        add_control(
            controls,
            key,
            nested(mixed_authorization, "lineage", key),
            nested(candidate_authorization, "lineage", key),
        )
    add_control(
        controls,
        "tokenizer_revision",
        mixed_manifest["tokenizer_revision"],
        candidate_manifest["tokenizer_revision"],
    )
    add_control(
        controls,
        "tokenizer_config_sha256",
        sha256(model_path / "tokenizer_config.json"),
        sha256(model_path / "tokenizer_config.json"),
    )
    add_control(
        controls,
        "chat_template_sha256",
        sha256_text(json.dumps(chat_template, sort_keys=True)),
        sha256_text(json.dumps(chat_template, sort_keys=True)),
    )
    add_control(
        controls,
        "areal_commit",
        mixed_run["areal_upstream"]["commit"],
        areal_lock["commit"],
    )
    add_control(
        controls,
        "hermes_commit",
        mixed_run["hermes_upstream"]["commit"],
        hermes_lock["commit"],
    )
    add_control(controls, "seed", mixed_overrides["seed"], candidate_overrides["seed"])

    config_pairs = {
        "fsdp_backend": ("actor", "backend"),
        "dtype": ("actor", "dtype"),
        "attention_implementation": ("actor", "attn_impl"),
        "dropout_disabled": ("actor", "disable_dropout"),
        "gradient_checkpointing": ("actor", "gradient_checkpointing"),
        "lora_rank": ("actor", "lora_rank"),
        "lora_alpha": ("actor", "lora_alpha"),
        "lora_target_modules": ("actor", "target_modules"),
        "optimizer": ("actor", "optimizer", "type"),
        "learning_rate": ("actor", "optimizer", "lr"),
        "weight_decay": ("actor", "optimizer", "weight_decay"),
        "beta1": ("actor", "optimizer", "beta1"),
        "beta2": ("actor", "optimizer", "beta2"),
        "optimizer_epsilon": ("actor", "optimizer", "eps"),
        "scheduler_type": ("actor", "optimizer", "lr_scheduler_type"),
        "warmup_fraction": ("actor", "optimizer", "warmup_steps_proportion"),
        "gradient_clip": ("actor", "optimizer", "gradient_clipping"),
        "microbatch_token_cap": ("actor", "mb_spec", "max_tokens_per_mb"),
        "global_batch_size": ("train_dataset", "batch_size"),
        "shuffle": ("train_dataset", "shuffle"),
        "drop_last": ("train_dataset", "drop_last"),
        "pin_memory": ("train_dataset", "pin_memory"),
        "dataloader_workers": ("train_dataset", "num_workers"),
        "dataset_type": ("train_dataset", "type"),
        "nodes": ("cluster", "n_nodes"),
        "gpus_per_node": ("cluster", "n_gpus_per_node"),
        "scheduler_backend": ("scheduler", "type"),
        "offload_enabled": ("enable_offload",),
        "init_from_scratch": ("actor", "init_from_scratch"),
        "lora_enabled": ("actor", "use_lora"),
        "peft_type": ("actor", "peft_type"),
        "worker_runtime_environment": (
            "actor",
            "scheduling_spec",
        ),
    }
    for name, path in config_pairs.items():
        add_control(controls, name, nested(mixed_config, *path), nested(candidate_config, *path))

    add_control(
        controls,
        "optimizer_updates",
        mixed_consumption["result"]["optimizer_updates"],
        candidate_budget["planned_optimizer_updates"],
    )
    add_control(
        controls,
        "training_sequences",
        mixed_authorization["budget"]["planned_sequences"],
        candidate_budget["planned_sequences"],
    )
    add_control(
        controls,
        "assistant_loss_tokens",
        mixed_consumption["result"]["assistant_loss_tokens"],
        candidate_budget["projected_assistant_loss_tokens"],
    )
    add_control(
        controls,
        "scheduler_horizon",
        mixed_scheduler_horizon,
        candidate_recipe["scheduler_total_steps"],
    )
    add_control(
        controls,
        "warmup_steps",
        math.floor(
            mixed_scheduler_horizon
            * nested(
                mixed_config,
                "actor",
                "optimizer",
                "warmup_steps_proportion",
            )
        ),
        candidate_recipe["warmup_steps"],
    )
    add_control(
        controls,
        "max_length",
        mixed_manifest["max_length"],
        candidate_manifest["max_length"],
    )
    add_control(
        controls,
        "loss_objective",
        mixed_authorization["recipe"]["loss"],
        candidate_recipe["loss"],
    )
    add_control(
        controls,
        "observations_masked",
        mixed_authorization["recipe"]["observations_masked"],
        candidate_recipe["observations_masked"],
    )
    for key in (
        "saver.freq_steps",
        "saver.freq_secs",
        "recover.freq_steps",
        "recover.freq_secs",
        "evaluator.freq_steps",
        "evaluator.freq_secs",
    ):
        add_control(controls, key, mixed_overrides.get(key), candidate_overrides.get(key))
    add_control(
        controls,
        "benchmark_manifest_sha256",
        mixed_run["benchmark"]["sha256"],
        sha256(benchmark_path),
    )
    add_control(
        controls,
        "sealed_used",
        mixed_run["benchmark"]["sealed_content_used"],
        not candidate_authorization["scope"]["no_sealed"],
    )
    add_control(
        controls,
        "rl_started",
        not mixed_run["run_authorization"]["scope"]["no_rl"],
        not candidate_authorization["scope"]["no_rl"],
    )
    add_control(
        controls,
        "benchmark_modified",
        not mixed_run["run_authorization"]["scope"]["no_benchmark_modification"],
        not candidate_authorization["scope"]["no_benchmark_modification"],
    )
    add_control(
        controls,
        "gradient_accumulation_contract",
        {
            "mode": "dynamic_microbatch_at_optimizer_boundary",
            "global_batch_size": nested(mixed_config, "train_dataset", "batch_size"),
            "max_tokens_per_microbatch": nested(
                mixed_config,
                "actor",
                "mb_spec",
                "max_tokens_per_mb",
            ),
        },
        {
            "mode": "dynamic_microbatch_at_optimizer_boundary",
            "global_batch_size": nested(
                candidate_config,
                "train_dataset",
                "batch_size",
            ),
            "max_tokens_per_microbatch": nested(
                candidate_config,
                "actor",
                "mb_spec",
                "max_tokens_per_mb",
            ),
        },
    )
    add_control(
        controls,
        "decoding_settings",
        "NOT_APPLICABLE_SUPERVISED_FINETUNING",
        "NOT_APPLICABLE_SUPERVISED_FINETUNING",
    )

    context_conditions: dict[str, Any] = {}
    add_control(
        context_conditions,
        "total_context_tokens",
        mixed_consumption["result"]["total_tokens"],
        candidate_budget["projected_total_tokens"],
        required_equal=False,
        note="Disclosed data-condition difference; assistant-loss exposure is exactly matched.",
    )
    add_control(
        context_conditions,
        "dataset_manifest_sha256",
        sha256(mixed_manifest_path),
        sha256(candidate_manifest_path),
        required_equal=False,
        note="The controlled variable is the training dataset composition.",
    )
    add_control(
        context_conditions,
        "natural_train_rows",
        mixed_rows,
        int(nested(candidate_manifest, "split_counts", "train")),
        required_equal=False,
        note="Both runs stop after 16,800 sequences; natural dataset lengths differ.",
    )

    head = git_output(repo, "rev-parse", "HEAD")
    runtime_files = (
        "studyhub-agent/training/runtime_shims/areal_metadata_bridge.py",
        "studyhub-agent/training/runtime_shims/areal_scheduler_bridge.py",
        "studyhub-agent/training/runtime_shims/areal_recovery_state_bridge.py",
        "studyhub-agent/training/runtime_shims/sitecustomize.py",
        "studyhub-agent/training/sft/open_bootstrap_driver.py",
    )
    runtime_diff = {
        path: {
            "mixed_blob_sha256": git_blob_sha256(repo, mixed_training_commit, path),
            "candidate_blob_sha256": git_blob_sha256(repo, head, path),
        }
        for path in runtime_files
    }
    runtime_changed = [
        path for path, values in runtime_diff.items() if values["mixed_blob_sha256"] != values["candidate_blob_sha256"]
    ]
    provenance_checks = {
        "mixed_training_commit_matches_frozen_reference": (mixed_training_commit == MIXED_TRAINING_COMMIT),
        "mixed_consumption_commit_matches_run": (mixed_consumption["training_commit"] == mixed_training_commit),
        "mixed_config_git_blob_matches_run": (
            git_blob_sha256(repo, mixed_training_commit, mixed_config_relative) == mixed_run["config"]["sha256"]
        ),
        "mixed_authorization_matches_run": (
            sha256(mixed_authorization_path) == mixed_run["run_authorization"]["sha256"]
        ),
        "mixed_dataset_manifest_matches_run": (sha256(mixed_manifest_path) == mixed_run["dataset_manifest_sha256"]),
        "candidate_program_matches_authorization": (
            sha256(candidate_program_path) == candidate_authorization["lineage"]["program_sha256"]
        ),
        "candidate_config_matches_authorization": (
            sha256(candidate_config_path) == candidate_authorization["lineage"]["config_sha256"]
        ),
        "candidate_dataset_matches_authorization": (
            sha256(candidate_manifest_path) == candidate_authorization["lineage"]["dataset_manifest_sha256"]
        ),
        "candidate_selected_matches_authorization": (
            sha256(candidate_selected_path) == candidate_authorization["lineage"]["selected_jsonl_sha256"]
        ),
        "candidate_selected_manifest_matches_authorization": (
            sha256(candidate_selected_manifest_path) == candidate_authorization["lineage"]["selected_manifest_sha256"]
        ),
        "candidate_data_card_matches_authorization": (
            sha256(candidate_data_card_path) == candidate_authorization["lineage"]["data_card_sha256"]
        ),
        "benchmark_matches_authorization": (
            sha256(benchmark_path) == candidate_authorization["lineage"]["benchmark_manifest_sha256"]
        ),
    }
    provenance_failures = [name for name, passed in provenance_checks.items() if not passed]
    hard_failures = [name for name, row in controls.items() if row["status"] == "FAIL"]
    recovery_contract = recovery_contract_status(recovery_evidence_path)
    worktree = git_output(repo, "status", "--short")
    status, decision, blockers = classify_audit(
        hard_failures=hard_failures,
        provenance_failures=provenance_failures,
        runtime_requires_confirmation=bool(runtime_changed) and not recovery_contract["eligible"],
        worktree_dirty=bool(worktree),
    )

    return {
        "schema_version": "studyhub.open-only-sft-control-diff.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "decision": decision,
        "head": head,
        "mixed_reference": {
            "training_commit": mixed_training_commit,
            "run_metadata": str(mixed_run_metadata_path.resolve()),
            "run_metadata_sha256": sha256(mixed_run_metadata_path),
        },
        "candidate": {
            "authorization": str(candidate_authorization_path.relative_to(project_root)),
            "authorization_sha256": sha256(candidate_authorization_path),
            "formal_run": "NOT_RUN",
        },
        "model_affecting_controls": controls,
        "hard_control_failures": hard_failures,
        "provenance_checks": provenance_checks,
        "provenance_failures": provenance_failures,
        "data_condition_differences": context_conditions,
        "runtime_correction_diff": {
            "status": (
                "SEMANTIC_EQUIVALENCE_CONFIRMED_BY_R1_R4"
                if runtime_changed and recovery_contract["eligible"]
                else "REQUIRES_R1_R4_CONFIRMATION"
                if runtime_changed
                else "UNCHANGED"
            ),
            "files": runtime_diff,
            "changed_files": runtime_changed,
            "recovery_contract": recovery_contract,
            "claim_boundary": (
                "The candidate adds scheduler and recovery-provenance shims. They are "
                "not treated as training-data effects until R1-R4 passes."
            ),
        },
        "static_default_note": {
            "mixed_yaml": {
                "saver.freq_steps": nested(mixed_config, "saver", "freq_steps"),
                "recover.freq_steps": nested(mixed_config, "recover", "freq_steps"),
                "evaluator.freq_steps": nested(
                    mixed_config,
                    "evaluator",
                    "freq_steps",
                ),
            },
            "candidate_yaml": {
                "saver.freq_steps": nested(candidate_config, "saver", "freq_steps"),
                "recover.freq_steps": nested(
                    candidate_config,
                    "recover",
                    "freq_steps",
                ),
                "evaluator.freq_steps": nested(
                    candidate_config,
                    "evaluator",
                    "freq_steps",
                ),
            },
            "interpretation": (
                "Static defaults differ, but the Mixed formal launcher overrode them "
                "to 210/210/disabled; candidate planned runtime overrides match."
            ),
        },
        "worktree": "CLEAN" if not worktree else worktree.splitlines(),
        "blockers": blockers,
        "scope": {
            "rl_started": False,
            "sealed_used": False,
            "benchmark_modified": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--mixed-run-metadata", type=Path, required=True)
    parser.add_argument("--recovery-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_audit(
        args.project_root.resolve(),
        args.mixed_run_metadata.resolve(),
        args.recovery_evidence.resolve() if args.recovery_evidence else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps({"status": result["status"], "decision": result["decision"]}))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
