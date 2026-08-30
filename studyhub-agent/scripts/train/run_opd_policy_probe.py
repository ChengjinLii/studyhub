#!/usr/bin/env python3
"""Evaluate one fixed model on the training-only OPD policy probe."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import multiprocessing as mp
import secrets
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.benchmark.run_9b_base_eval import (  # noqa: E402
    git_value,
    launch_server,
    resolve_model_artifact,
    sha256,
    stable_rank,
    wait_for_server,
)
from training.rl.hermes_workflow_v3 import StudyHubHermesWorkflowV3  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()


def latest_reward(path: Path, task_id: str) -> dict[str, Any]:
    rows = read_jsonl(path)
    if not rows or str(rows[-1].get("task_id")) != task_id:
        raise RuntimeError(f"missing Reward v3 row after rollout: {task_id}")
    return rows[-1]


def worker_main(spec: dict[str, Any]) -> None:
    output = Path(spec["output"])
    completed = {str(row["task_id"]) for row in read_jsonl(output)}
    reward_root = Path(spec["reward_root"])
    workflow = StudyHubHermesWorkflowV3(
        environment_root=spec["pool_root"],
        verifier_root=str(Path(spec["pool_root"]) / "verifiers"),
        hermes_checkout=spec["hermes_checkout"],
        reward_artifact_root=str(reward_root),
        experiment_name="studyhub-qwen35-4b-opd-novelty",
        trial_name=spec["trial"],
        run_kind="training_only_novelty_probe",
        seed=int(spec["seed"]),
        max_turns=6,
        tokenizer_path=spec["tokenizer_path"],
        engine_max_tokens=16384,
        context_finalization_ratio=0.80,
        context_safety_margin_tokens=768,
        temperature=float(spec["temperature"]),
        top_p=1.0,
        max_completion_tokens=4096,
    )
    reward_file = reward_root / "reward-v3.jsonl"
    for index, task in enumerate(spec["tasks"], start=1):
        task_id = str(task["task_id"])
        if task_id in completed:
            continue
        started = time.monotonic()
        try:
            scalar = asyncio.run(
                workflow.run(
                    task,
                    base_url=spec["base_url"],
                    api_key=spec["api_key"],
                )
            )
            reward_row = latest_reward(reward_file, task_id)
            reward = dict(reward_row["reward"])
            row = {
                "schema_version": "studyhub.opd-policy-probe-episode.v1",
                "trial": spec["trial"],
                "model_role": spec["model_role"],
                "model": spec["model_identity"],
                "task_id": task_id,
                "family": task["metadata"]["family"],
                "source_group_id": task["metadata"]["source_group_id"],
                "status": reward["status"],
                "strict_success": bool(reward["strict_success"]),
                "diagnostic_score": float(scalar),
                "tool_validity": float(reward["tool_validity"]),
                "hard_gate_triggered": bool(reward["hard_gate_triggered"]),
                "hard_gate_reasons": list(reward["hard_gate_reasons"]),
                "trace": reward_row["trace"],
                "reward": reward,
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "error": None,
            }
        except Exception as error:  # noqa: BLE001 - preserve task-level infra evidence
            row = {
                "schema_version": "studyhub.opd-policy-probe-episode.v1",
                "trial": spec["trial"],
                "model_role": spec["model_role"],
                "model": spec["model_identity"],
                "task_id": task_id,
                "family": task["metadata"]["family"],
                "source_group_id": task["metadata"]["source_group_id"],
                "status": "INFRA_EXCLUDED",
                "strict_success": False,
                "diagnostic_score": 0.0,
                "tool_validity": 0.0,
                "hard_gate_triggered": False,
                "hard_gate_reasons": [],
                "trace": {},
                "reward": {},
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "error": {"type": type(error).__name__, "message": str(error)[:1000]},
            }
        append_jsonl(output, row)
        completed.add(task_id)
        print(
            f"worker={spec['worker_id']} {index}/{len(spec['tasks'])} "
            f"task={task_id} status={row['status']} strict={row['strict_success']}",
            flush=True,
        )


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row["status"] == "SCORED"]
    families: dict[str, dict[str, Any]] = {}
    for family in sorted({str(row["family"]) for row in scored}):
        subset = [row for row in scored if row["family"] == family]
        families[family] = {
            "tasks": len(subset),
            "strict_successes": sum(bool(row["strict_success"]) for row in subset),
            "strict_success_rate": round(
                sum(bool(row["strict_success"]) for row in subset)
                / max(len(subset), 1),
                6,
            ),
            "mean_diagnostic_score": round(
                sum(float(row["diagnostic_score"]) for row in subset)
                / max(len(subset), 1),
                6,
            ),
            "mean_tool_validity": round(
                sum(float(row["tool_validity"]) for row in subset)
                / max(len(subset), 1),
                6,
            ),
        }
    return {
        "tasks": len(rows),
        "scored": len(scored),
        "infra_excluded": len(rows) - len(scored),
        "strict_successes": sum(bool(row["strict_success"]) for row in scored),
        "strict_success_rate": round(
            sum(bool(row["strict_success"]) for row in scored) / max(len(scored), 1), 6
        ),
        "mean_diagnostic_score": round(
            sum(float(row["diagnostic_score"]) for row in scored) / max(len(scored), 1),
            6,
        ),
        "mean_tool_validity": round(
            sum(float(row["tool_validity"]) for row in scored) / max(len(scored), 1), 6
        ),
        "status_counts": dict(Counter(str(row["status"]) for row in rows)),
        "families": families,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-root", type=Path, required=True)
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-role", choices=("teacher", "student"), required=True)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--hermes-checkout", type=Path, default=PROJECT_ROOT / ".vendor/hermes-agent"
    )
    parser.add_argument("--gpus", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--workers-per-gpu", type=int, default=2, choices=(1, 2, 3, 4))
    parser.add_argument("--port-base", type=int, default=30340)
    parser.add_argument("--server-timeout", type=float, default=1200.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    from scripts.train.prepare_sglang_model_overlay import prepare_overlay

    pool = args.pool_root.resolve()
    task_file = (args.task_file or pool / "tasks/novelty_probe.jsonl").resolve()
    tasks = read_jsonl(task_file)
    if args.limit is not None:
        tasks = sorted(
            tasks, key=lambda row: stable_rank(args.seed, str(row["task_id"]))
        )[: args.limit]
    if not tasks or len({str(row["task_id"]) for row in tasks}) != len(tasks):
        raise RuntimeError("policy probe task set is empty or contains duplicate IDs")
    model_identity, model_manifest = resolve_model_artifact(args.model.resolve())
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    api_key = secrets.token_urlsafe(36)
    overlay_key = hashlib.sha256(model_identity.encode()).hexdigest()[:16]
    model_overlay = (
        PROJECT_ROOT / f"artifacts/areal/model-overlays/opd-probe-{overlay_key}"
    )
    prepare_overlay(args.model.resolve(), model_overlay)
    ports = [args.port_base + index for index in range(len(args.gpus))]
    endpoints = [f"http://127.0.0.1:{port}/v1" for port in ports]
    servers: list[subprocess.Popen[str]] = []
    streams: list[Any] = []
    started = time.monotonic()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        for server_id, gpu in enumerate(args.gpus):
            server, stream = launch_server(
                python=sys.executable,
                model=model_overlay,
                gpu=gpu,
                port=ports[server_id],
                api_key=api_key,
                log_path=output_root / f"server-{server_id}.log",
                project=PROJECT_ROOT,
            )
            servers.append(server)
            streams.append(stream)
        for endpoint, server in zip(endpoints, servers, strict=True):
            wait_for_server(endpoint, server, args.server_timeout, api_key)

        worker_count = len(args.gpus) * args.workers_per_gpu
        context = mp.get_context("spawn")
        processes: list[mp.Process] = []
        for worker_id in range(worker_count):
            server_id = worker_id % len(args.gpus)
            shard = tasks[worker_id::worker_count]
            spec = {
                "worker_id": worker_id,
                "tasks": shard,
                "output": str(output_root / f"episodes-worker-{worker_id}.jsonl"),
                "reward_root": str(output_root / f"reward-worker-{worker_id}"),
                "trial": args.trial,
                "model_role": args.model_role,
                "model_identity": model_identity,
                "pool_root": str(pool),
                "hermes_checkout": str(args.hermes_checkout.resolve()),
                "tokenizer_path": str(args.model.resolve()),
                "base_url": endpoints[server_id],
                "api_key": api_key,
                "temperature": args.temperature,
                "seed": args.seed,
            }
            process = context.Process(
                target=worker_main, args=(spec,), name=f"opd-probe-worker-{worker_id}"
            )
            process.start()
            processes.append(process)
        for process in processes:
            process.join()
        failed = [process.name for process in processes if process.exitcode != 0]
        if failed:
            raise RuntimeError(f"OPD policy probe workers failed: {failed}")
    finally:
        for server in servers:
            if server.poll() is None:
                server.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 20
        for server in servers:
            try:
                server.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        for stream in streams:
            stream.close()

    rows = [
        row
        for worker_id in range(len(args.gpus) * args.workers_per_gpu)
        for row in read_jsonl(output_root / f"episodes-worker-{worker_id}.jsonl")
    ]
    by_id = {str(row["task_id"]): row for row in rows}
    expected = {str(row["task_id"]) for row in tasks}
    if set(by_id) != expected:
        raise RuntimeError(
            f"OPD probe completeness mismatch: missing={len(expected - set(by_id))} "
            f"extra={len(set(by_id) - expected)}"
        )
    merged = output_root / "episodes.jsonl"
    merged.write_text(
        "".join(
            json.dumps(by_id[key], ensure_ascii=False, sort_keys=True) + "\n"
            for key in sorted(by_id)
        ),
        encoding="utf-8",
    )
    summary = {
        "schema_version": "studyhub.opd-policy-probe-run.v1",
        "trial": args.trial,
        "model_role": args.model_role,
        "model": model_identity,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "seed": args.seed,
        "temperature": args.temperature,
        "task_file": str(task_file),
        "task_file_sha256": sha256(task_file),
        "pool_manifest_sha256": sha256(pool / "manifest.json"),
        "episodes_sha256": sha256(merged),
        "workers_per_gpu": args.workers_per_gpu,
        "gpus": args.gpus,
        "metrics": aggregate(list(by_id.values())),
        "git_commit": git_value(PROJECT_ROOT, "rev-parse", "HEAD"),
        "model_manifest": model_manifest,
        "sealed_used": False,
        "validation_or_protocol_holdout_used": False,
        "optimizer_updates": 0,
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    args = parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["metrics"]["infra_excluded"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
