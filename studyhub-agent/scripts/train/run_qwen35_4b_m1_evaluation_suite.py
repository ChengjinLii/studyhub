#!/usr/bin/env python3
"""Run the preregistered M1 merge and evaluation sequence exactly once per stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parent
for import_root in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

DEFAULT_CHECKPOINT_ROOT = (
    PROJECT_ROOT
    / "artifacts/areal/checkpoints"
    / os.environ.get("USER", "chengjin")
    / "studyhub-qwen35-4b-open-agentic-sft1"
    / "qwen35-4b-sft1-formal-r32-seed-20260827"
)
DEFAULT_MODEL = PROJECT_ROOT / "artifacts/areal/merged/qwen35-4b-sft1-r32-seed-20260827"
DEFAULT_STATE_ROOT = PROJECT_ROOT / "artifacts/evaluation-suite/qwen35-4b-m1"
STAGES = ("merge", "protocol", "agentbench", "bfcl", "tau2")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def git_value(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_completion_marker(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if value.get("status") != "COMPLETE" or value.get("mode") != "formal":
        raise RuntimeError("M1 completion marker is not a completed formal run")
    if value.get("expected_optimizer_updates") != 2100 or value.get("final_global_step") != 2099:
        raise RuntimeError("M1 completion marker does not cover the frozen 2100-update run")
    if value.get("sealed_used") is not False or value.get("rl_started") is not False:
        raise RuntimeError("M1 completion marker does not prove SFT-only sealed isolation")
    checkpoint = Path(str(value.get("checkpoint", {}).get("path", "")))
    if not checkpoint.is_file() or sha256(checkpoint) != value.get("checkpoint", {}).get("sha256"):
        raise RuntimeError("M1 final adapter is missing or has hash drift")
    return value


def validate_merged_model(model: Path, completion_marker: Path) -> tuple[str, dict[str, Any]]:
    from scripts.benchmark.run_9b_base_eval import resolve_model_artifact

    identity, manifest = resolve_model_artifact(model)
    if manifest.get("training_stage") != "sft1":
        raise RuntimeError("merged M1 artifact has the wrong training stage")
    lineage = manifest.get("training_lineage", {})
    if lineage.get("completion_marker_sha256") != sha256(completion_marker):
        raise RuntimeError("merged M1 artifact is not bound to the completed formal run")
    if lineage.get("expected_optimizer_updates") != 2100 or lineage.get("final_global_step") != 2099:
        raise RuntimeError("merged M1 artifact has incomplete optimizer lineage")
    return identity, manifest


def validate_protocol(summary: dict[str, Any], model_identity: str) -> None:
    if summary.get("status") != "PASS_SFT1_PROTOCOL_HOLDOUT":
        raise RuntimeError("M1 protocol holdout did not pass its preregistered thresholds")
    if summary.get("formal_gate_evaluated") is not True or summary.get("model") != model_identity:
        raise RuntimeError("M1 protocol holdout summary has incompatible lineage")
    if summary.get("expected_items") != 3022 or summary.get("scored_items") != 3022:
        raise RuntimeError("M1 protocol holdout did not score all 3,022 assistant turns")


def validate_agentbench(summary: dict[str, Any], model_identity: str) -> None:
    expected = {
        "schema_version": "studyhub.agentbench-run-summary.v2",
        "benchmark_version": "studyhub-agentbench-v2",
        "mode": "development",
        "episodes_expected": 51,
        "episodes_scored": 51,
        "infra_excluded": 0,
        "model": model_identity,
    }
    mismatches = {key: (summary.get(key), value) for key, value in expected.items() if summary.get(key) != value}
    if mismatches:
        raise RuntimeError(f"M1 AgentBench summary failed its completeness contract: {mismatches}")


def validate_bfcl(summary: dict[str, Any], model_identity: str) -> None:
    if summary.get("status") != "COMPLETED_BFCL_PUBLIC_PARTIAL_REPLICATION":
        raise RuntimeError("M1 BFCL public replication is incomplete")
    if summary.get("model") != model_identity or summary.get("scores", {}).get("total_count") != 70:
        raise RuntimeError("M1 BFCL public replication has incompatible model or case count")
    if summary.get("scores", {}).get("official_full_leaderboard_score") is not False:
        raise RuntimeError("M1 BFCL partial replication was mislabeled as a full leaderboard score")


def validate_tau2(summary: dict[str, Any], model_identity: str) -> None:
    if summary.get("status") != "COMPLETED_TAU2_PUBLIC_PARTIAL_REPLICATION":
        raise RuntimeError("M1 tau2 public replication is incomplete")
    if summary.get("model") != model_identity or summary.get("scores", {}).get("tasks") != 15:
        raise RuntimeError("M1 tau2 public replication has incompatible model or task count")
    if summary.get("scores", {}).get("official_full_leaderboard_score") is not False:
        raise RuntimeError("M1 tau2 partial replication was mislabeled as a full leaderboard score")


def run_command(command: list[str], *, environment: dict[str, str]) -> None:
    print(f"[M1 suite] running: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=REPOSITORY_ROOT, env=environment, check=True)


def summary_paths(root: Path) -> set[Path]:
    return set(root.glob("*/summary.json")) if root.is_dir() else set()


def new_summary(root: Path, before: set[Path]) -> Path:
    candidates = sorted(summary_paths(root) - before, key=lambda path: path.stat().st_mtime_ns)
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one new summary under {root}, found {len(candidates)}")
    return candidates[0]


def receipt_path(state_root: Path, stage: str) -> Path:
    return state_root / f"{stage}.json"


def validate_receipt(
    state_root: Path,
    stage: str,
    validator: Callable[[dict[str, Any], str], None],
    model_identity: str,
) -> bool:
    path = receipt_path(state_root, stage)
    if not path.is_file():
        return False
    receipt = read_json(path)
    artifact = Path(str(receipt.get("artifact", "")))
    if (
        receipt.get("status") != "COMPLETE"
        or receipt.get("stage") != stage
        or receipt.get("model") != model_identity
        or not artifact.is_file()
        or sha256(artifact) != receipt.get("artifact_sha256")
    ):
        raise RuntimeError(f"M1 evaluation receipt has drifted: {path}")
    validator(read_json(artifact), model_identity)
    return True


def record_receipt(
    state_root: Path,
    stage: str,
    artifact: Path,
    model_identity: str,
    command: list[str],
) -> None:
    write_json(
        receipt_path(state_root, stage),
        {
            "schema_version": "studyhub.qwen35-4b-m1-evaluation-receipt.v1",
            "status": "COMPLETE",
            "stage": stage,
            "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": git_value("rev-parse", "HEAD"),
            "model": model_identity,
            "artifact": str(artifact.resolve()),
            "artifact_sha256": sha256(artifact),
            "command": command,
            "fresh_holdout_used": False,
            "sealed_used": False,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--checkpoint-root", type=Path, default=DEFAULT_CHECKPOINT_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--gpus", default="0,1")
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.seed != 20260827:
        raise RuntimeError("M1 evaluation is frozen to seed 20260827")
    if git_value("status", "--porcelain"):
        raise RuntimeError("M1 evaluation suite requires a clean Git worktree")
    completion_marker = args.checkpoint_root.resolve() / "QWEN35_4B_SFT1_COMPLETE.json"
    if not completion_marker.is_file():
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "status": "WAITING_M1_COMPLETION",
                        "completion_marker": str(completion_marker),
                        "stages": list(STAGES),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        raise RuntimeError(f"M1 completion marker is missing: {completion_marker}")
    validate_completion_marker(completion_marker)
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "status": "READY_M1_EVALUATION_SUITE",
                    "completion_marker_sha256": sha256(completion_marker),
                    "stages": list(STAGES),
                    "fresh_holdout_used": False,
                    "sealed_used": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if os.environ.get("STUDYHUB_ALLOW_M1_EVALUATION") != "YES":
        raise RuntimeError("set STUDYHUB_ALLOW_M1_EVALUATION=YES to execute the frozen suite")

    environment = os.environ.copy()
    environment.update(
        {
            "STUDYHUB_ALLOW_EVALUATION": "YES",
            "STUDYHUB_EVAL_GPUS": args.gpus,
            "STUDYHUB_EVAL_MODEL": str(args.model.resolve()),
            "STUDYHUB_EVAL_MODEL_ROLE": "m1-sft1",
            "STUDYHUB_EVAL_MODEL_RUN_PREFIX": "qwen35-4b",
            "STUDYHUB_PROTOCOL_MAX_ROWS": "0",
        }
    )
    args.state_root.mkdir(parents=True, exist_ok=True)

    if not args.model.exists():
        run_command([str(PROJECT_ROOT / "scripts/train/merge_qwen35_4b_sft1.sh")], environment=environment)
    model_identity, _manifest = validate_merged_model(args.model.resolve(), completion_marker)
    merge_receipt = receipt_path(args.state_root, "merge")
    merged_manifest = args.model.resolve() / "studyhub_merged_manifest.json"
    if merge_receipt.is_file():
        receipt = read_json(merge_receipt)
        if (
            receipt.get("status") != "COMPLETE"
            or receipt.get("stage") != "merge"
            or receipt.get("model") != model_identity
            or Path(str(receipt.get("artifact", ""))).resolve() != merged_manifest
            or receipt.get("artifact_sha256") != sha256(merged_manifest)
        ):
            raise RuntimeError("M1 merge receipt has drifted")
    else:
        record_receipt(
            args.state_root,
            "merge",
            merged_manifest,
            model_identity,
            [str(PROJECT_ROOT / "scripts/train/merge_qwen35_4b_sft1.sh")],
        )

    gpu_ids = [value.strip() for value in args.gpus.split(",") if value.strip()]
    if len(gpu_ids) != 2:
        raise RuntimeError("M1 evaluation suite requires exactly two GPUs")
    stage_specs: list[tuple[str, Path, list[str], Callable[[dict[str, Any], str], None]]] = [
        (
            "protocol",
            PROJECT_ROOT / "artifacts/protocol-holdout/qwen35-4b-sft1",
            [str(PROJECT_ROOT / "scripts/train/run_qwen35_4b_sft1_protocol_holdout.sh")],
            validate_protocol,
        ),
        (
            "agentbench",
            PROJECT_ROOT / "artifacts/benchmark-v2/runs",
            [str(PROJECT_ROOT / "scripts/benchmark/run_qwen35_4b_model_eval_v2.sh"), "development", str(args.seed)],
            validate_agentbench,
        ),
        (
            "bfcl",
            PROJECT_ROOT / "artifacts/external-benchmarks/runs",
            [
                str(PROJECT_ROOT / ".venv/bin/python"),
                str(PROJECT_ROOT / "scripts/benchmark/external/run_bfcl_replication.py"),
                "--model",
                str(args.model.resolve()),
                "--gpu",
                gpu_ids[0],
            ],
            validate_bfcl,
        ),
        (
            "tau2",
            PROJECT_ROOT / "artifacts/external-benchmarks/runs",
            [
                str(PROJECT_ROOT / ".venv/bin/python"),
                str(PROJECT_ROOT / "scripts/benchmark/external/run_tau2_replication.py"),
                "--model",
                str(args.model.resolve()),
                "--agent-gpu",
                gpu_ids[0],
                "--user-gpu",
                gpu_ids[1],
            ],
            validate_tau2,
        ),
    ]
    for stage, output_root, command, validator in stage_specs:
        if validate_receipt(args.state_root, stage, validator, model_identity):
            print(f"[M1 suite] {stage}: receipt already complete", flush=True)
            continue
        before = summary_paths(output_root)
        run_command(command, environment=environment)
        summary_path = new_summary(output_root, before)
        summary = read_json(summary_path)
        validator(summary, model_identity)
        record_receipt(args.state_root, stage, summary_path, model_identity, command)

    final = {
        "schema_version": "studyhub.qwen35-4b-m1-evaluation-suite.v1",
        "status": "COMPLETE",
        "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_value("rev-parse", "HEAD"),
        "model": model_identity,
        "stages": {stage: str(receipt_path(args.state_root, stage)) for stage in STAGES},
        "fresh_holdout_used": False,
        "sealed_used": False,
        "claim_boundary": "M1_PROTOCOL_AND_PUBLIC_REPLICATION_ONLY_NOT_FRESH_HOLDOUT_OR_SEALED",
    }
    write_json(args.state_root / "suite.json", final)
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
