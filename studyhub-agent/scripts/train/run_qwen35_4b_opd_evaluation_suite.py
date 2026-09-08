#!/usr/bin/env python3
"""Evaluate a completed formal OPD checkpoint and M2 using existing fixed panels."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT), str(PROJECT / "src")]

from scripts.train.merge_sft_lora import completion_lineage, sha256  # noqa: E402

MAX_OWN_GPU_MIB = 64000
RESERVED_GPU_MIB = 12000
ADMISSION_FREE_MIB = MAX_OWN_GPU_MIB + RESERVED_GPU_MIB


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def paired_agentbench(left: Path, right: Path):
    def rows(path):
        values = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        keyed = {value["task_id"]: value for value in values}
        if len(values) != len(keyed) or len(values) != 51:
            raise RuntimeError("AgentBench comparison requires exactly 51 unique tasks per model")
        return keyed

    a, b = rows(left), rows(right)
    if a.keys() != b.keys():
        raise RuntimeError("AgentBench paired task mismatch")
    counts = dict(wins=0, losses=0, ties=0, infra_excluded=0)
    for task in a:
        x, y = a[task], b[task]
        if x["sample_seed"] != y["sample_seed"] or x["split"] != y["split"]:
            raise RuntimeError("AgentBench sampling/split mismatch")
        if x["status"] != "SCORED" or y["status"] != "SCORED":
            counts["infra_excluded"] += 1
            continue
        old, new = x["evaluation"]["strict_success"], y["evaluation"]["strict_success"]
        counts["wins" if new > old else "losses" if new < old else "ties"] += 1
    return counts


def gpu_ready():
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    )
    free = {int(line.split(",")[0]): int(line.split(",")[1]) for line in result.stdout.splitlines()}
    return all(free.get(gpu, 0) >= ADMISSION_FREE_MIB for gpu in (0, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--training-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=75600)
    parser.add_argument("--closeout-audit", type=Path)
    args = parser.parse_args()
    root, output = args.artifact_root.resolve(), args.output.resolve()
    if output.exists():
        raise RuntimeError("refusing to overwrite evaluation evidence")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=PROJECT.parent).strip():
        raise RuntimeError("evaluation requires a clean worktree")
    output.mkdir(parents=True)
    manifest = {
        "status": "WAITING_FOR_FORMAL_OPD",
        "sealed_used": False,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT.parent).decode().strip(),
        "training_run": str(args.training_run.resolve()),
        "stages": {},
        "claim_boundary": "Fixed public subsets, not full external leaderboards; tau2 uses a local 9B user simulator.",
    }
    state = output / "suite.json"
    write(state, manifest)
    python = root / ".venv-train/bin/python"
    trial = "qwen35-4b-opd-formal-seed-20260827"
    marker = (
        root / f"artifacts/areal/checkpoints/chengjin/studyhub-qwen35-4b-strict-opd/{trial}/QWEN35_4B_OPD_COMPLETE.json"
    )
    deadline = time.monotonic() + args.wait_seconds
    try:
        while True:
            if args.closeout_audit:
                from scripts.train.recover_opd_closeout import verify_closeout

                verify_closeout(args.closeout_audit, args.training_run, marker)
                manifest["recovered_closeout"] = {
                    "path": str(args.closeout_audit.resolve()),
                    "sha256": sha256(args.closeout_audit),
                    "launcher_exit_assumed_success": False,
                }
                break
            run = read(args.training_run)
            if run.get("finished_at"):
                if run.get("exit_status") != 0:
                    raise RuntimeError(f"formal OPD exited with status {run.get('exit_status')}; no evaluation")
                # The launcher finishes run metadata before writing its evidence marker.
                if marker.exists():
                    break
            if time.monotonic() > deadline:
                raise RuntimeError("timed out waiting for completed formal OPD evidence")
            time.sleep(30)
        lineage = completion_lineage(marker, "opd")
        authorization = PROJECT / "configs/program-v4/qwen35-4b-opd-formal-authorization.json"
        if lineage["authorization_sha256"] != sha256(authorization):
            raise RuntimeError("OPD authorization drift")
        auth = read(authorization)
        benchmark = PROJECT / "benchmarks/studyhub-agent-v2/manifest.json"
        if sha256(benchmark) != auth["lineage"]["benchmark_manifest_sha256"]:
            raise RuntimeError("frozen benchmark drift")
        manifest.update(status="EVALUATING", training_run_sha256=sha256(args.training_run), lineage=lineage)
        write(state, manifest)
        env = os.environ.copy()
        for key in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "PYTHONHOME"):
            env.pop(key, None)
        env.update(
            PYTHONPATH=f"{PROJECT}/training/runtime_shims:{PROJECT}:{PROJECT}/src",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            TOKENIZERS_PARALLELISM="false",
            STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC="1",
            STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC="1",
            OMP_NUM_THREADS="2",
        )

        def execute(name, command, gpu=True):
            if gpu:
                admission_deadline = time.monotonic() + 43200
                while not gpu_ready():
                    if time.monotonic() > admission_deadline:
                        raise RuntimeError("GPU headroom wait expired; no other user's process was stopped")
                    time.sleep(60)
                command = [
                    str(python),
                    str(PROJECT / "scripts/train/guarded_gpu_launch.py"),
                    "--gpus",
                    "0,1",
                    "--min-free-mib",
                    str(ADMISSION_FREE_MIB),
                    "--max-used-mib",
                    "68000",
                    "--allow-shared-gpu",
                    "--max-own-used-mib",
                    str(MAX_OWN_GPU_MIB),
                    "--min-runtime-free-mib",
                    str(RESERVED_GPU_MIB),
                    "--max-wall-seconds",
                    "10800",
                    "--log",
                    str(output / f"{name}.gpu.log"),
                    "--gpu-csv",
                    str(output / f"{name}.gpu.csv"),
                    "--",
                    *command,
                ]
            manifest["stages"][name] = {"status": "RUNNING", "command": command}
            write(state, manifest)
            with (output / f"{name}.log").open("w") as log:
                code = subprocess.run(command, cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
            manifest["stages"][name].update(status="PROCESS_EXITED", exit_code=code)
            write(state, manifest)
            return code

        model = root / "artifacts/areal/merged/qwen35-4b-opd-formal-300-seed-20260827"
        if model.exists():
            merged = read(model / "studyhub_merged_manifest.json")
            if (
                merged.get("training_lineage") != lineage
                or merged.get("adapter_sha256") != lineage["checkpoint_sha256"]
            ):
                raise RuntimeError("existing OPD merged model lineage mismatch")
        else:
            code = execute(
                "merge",
                [
                    str(python),
                    str(PROJECT / "scripts/train/merge_sft_lora.py"),
                    "--base",
                    str(root / "artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer"),
                    "--adapter",
                    str(Path(read(marker)["checkpoint"]["path"]).parent),
                    "--output",
                    str(model),
                    "--stage",
                    "opd",
                    "--completion-lineage",
                    str(marker),
                ],
                gpu=False,
            )
            if code:
                raise RuntimeError("OPD merge failed")

        from scripts.benchmark.run_9b_base_eval import resolve_model_artifact

        models = {"m2": root / "artifacts/areal/merged/qwen35-4b-sft2-compact-v1", "opd": model}
        _, m2_manifest = resolve_model_artifact(models["m2"])
        if m2_manifest["adapter_sha256"] != auth["lineage"]["m2_adapter_sha256"]:
            raise RuntimeError("M2 baseline adapter drift")
        manifest["models"] = {key: resolve_model_artifact(path)[1] for key, path in models.items()}
        manifest["summaries"] = {}
        for label, path in models.items():
            common = ["--model", str(path), "--output-root", str(output / label)]
            commands = {
                "protocol": [
                    str(python),
                    str(PROJECT / "scripts/train/evaluate_qwen35_4b_protocol_holdout.py"),
                    *common,
                    "--artifact-root",
                    str(root),
                    "--max-rows",
                    "128",
                    "--run-id",
                    "protocol",
                ],
                "agentbench": [
                    str(python),
                    str(PROJECT / "scripts/benchmark/run_9b_base_eval.py"),
                    "development",
                    *common,
                    "--artifact-root",
                    str(root),
                    "--benchmark-version",
                    "v2",
                    "--hermes-checkout",
                    str(root / ".vendor/hermes-agent"),
                    "--trial",
                    "agentbench",
                ],
                "bfcl": [
                    str(python),
                    str(PROJECT / "scripts/benchmark/external/run_bfcl_replication.py"),
                    *common,
                    "--run-id",
                    "bfcl",
                    "--registry-name",
                    f"StudyHub/Qwen3.5-4B-{label.upper()}-FC",
                    "--display-name",
                    f"StudyHub Qwen3.5-4B {label.upper()} (FC)",
                ],
                "tau2": [
                    str(python),
                    str(PROJECT / "scripts/benchmark/external/run_tau2_replication.py"),
                    *common,
                    "--run-id",
                    "tau2",
                ],
            }
            for benchmark_name, command in commands.items():
                name = f"{label}-{benchmark_name}"
                code = execute(name, command)
                summary = output / label / benchmark_name / "summary.json"
                if summary.is_file():
                    manifest["summaries"][name] = {
                        "path": str(summary),
                        "sha256": sha256(summary),
                        "result": read(summary),
                    }
                manifest["stages"][name]["status"] = (
                    "COMPLETED" if code == 0 and summary.is_file() else "FAILED_OR_INCOMPLETE"
                )
                write(state, manifest)
        if all(manifest["stages"].get(f"{label}-agentbench", {}).get("status") == "COMPLETED" for label in models):
            manifest["agentbench_paired"] = paired_agentbench(
                output / "m2/agentbench/episodes.jsonl",
                output / "opd/agentbench/episodes.jsonl",
            )
        manifest["status"] = (
            "COMPLETED"
            if all(
                manifest["stages"].get(f"{label}-{bench}", {}).get("status") == "COMPLETED"
                for label in models
                for bench in ("protocol", "agentbench", "bfcl", "tau2")
            )
            else "PARTIAL_EVALUATION"
        )
        inventory = {str(p.relative_to(output)): sha256(p) for p in output.rglob("*") if p.is_file() and p != state}
        write(output / "artifact-hashes.json", inventory)
        write(state, manifest)
        return 0 if manifest["status"] == "COMPLETED" else 1
    except Exception as exc:
        manifest.update(status="STOPPED", error=f"{type(exc).__name__}: {exc}")
        write(state, manifest)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
