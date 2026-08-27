#!/usr/bin/env python3
"""Run the frozen Benchmark v1 against Qwen3.5-9B without an optimizer."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import secrets
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.development_evaluator import (
    evaluate_development,
    load_development_graders,
)
from studyhub_agent.benchmark_v1.hermes_runner import BenchmarkHermesRunner
from studyhub_agent.benchmark_v1.schema import BENCHMARK_VERSION, BenchmarkTask, load_jsonl

DEFAULT_SEED = 20260827
VARIANCE_TASKS_PER_CAPABILITY = 5
VARIANCE_SAMPLES = 4


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_rank(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def git_value(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def select_tasks(rows: list[dict[str, Any]], mode: str, seed: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        BenchmarkTask.from_dict(row)
        grouped[str(row["capability_id"])].append(row)
    if mode == "gate":
        return [
            min(values, key=lambda row: stable_rank(seed, str(row["task_id"])))
            for _capability, values in sorted(grouped.items())
        ]
    if mode in {"regression", "development"}:
        return list(rows)
    if mode == "variance":
        selected = []
        for _capability, values in sorted(grouped.items()):
            ordered = sorted(values, key=lambda row: stable_rank(seed, str(row["task_id"])))
            selected.extend(ordered[:VARIANCE_TASKS_PER_CAPABILITY])
        return selected
    raise ValueError(f"unknown mode: {mode}")


def build_work_items(tasks: list[dict[str, Any]], mode: str, seed: int) -> list[dict[str, Any]]:
    samples = VARIANCE_SAMPLES if mode == "variance" else 1
    items = []
    for task in tasks:
        for sample_index in range(samples):
            sample_seed = int(stable_rank(seed + sample_index, str(task["task_id"]))[:8], 16)
            items.append(
                {
                    "task": task,
                    "sample_index": sample_index,
                    "sample_seed": sample_seed,
                    "episode_key": f"{task['task_id']}:{sample_index}",
                }
            )
    return sorted(items, key=lambda row: stable_rank(seed, str(row["episode_key"])))


def wait_for_server(
    base_url: str,
    process: subprocess.Popen[str],
    timeout: float,
    api_key: str,
) -> None:
    deadline = time.monotonic() + timeout
    endpoint = base_url.rstrip("/") + "/models"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"SGLang exited before readiness with code {process.returncode}")
        try:
            request = urllib.request.Request(  # noqa: S310 - fixed localhost URL
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 - fixed localhost URL
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError(f"SGLang readiness timed out: {endpoint}")


def launch_server(
    *,
    python: str,
    model: Path,
    gpu: int,
    port: int,
    api_key: str,
    log_path: Path,
    project: Path,
) -> tuple[subprocess.Popen[str], Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_stream = log_path.open("w", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": str(gpu),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC": "1",
            "STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC": "1",
            "PYTHONPATH": ":".join(
                [
                    str(project / "training/runtime_shims"),
                    str(project),
                    str(project / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ).rstrip(":"),
        }
    )
    command = [
        python,
        "-m",
        "sglang.launch_server",
        "--model-path",
        str(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--served-model-name",
        "default",
        "--api-key",
        api_key,
        "--dtype",
        "bfloat16",
        "--context-length",
        "65536",
        "--mem-fraction-static",
        "0.70",
        "--max-running-requests",
        "4",
        "--tool-call-parser",
        "qwen3_coder",
        "--reasoning-parser",
        "qwen3",
        "--sampling-backend",
        "pytorch",
        "--disable-overlap-schedule",
    ]
    process = subprocess.Popen(
        command,
        cwd=project,
        env=environment,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log_stream


def load_completed(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {str(row["episode_key"]) for row in load_jsonl(path)}


def worker_main(spec: dict[str, Any]) -> None:
    output = Path(spec["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = load_completed(output)
    graders = load_development_graders(Path(spec["grader_path"]))
    runner = BenchmarkHermesRunner(
        hidden_root=spec["hidden_root"],
        hermes_checkout=spec["hermes_checkout"],
        tokenizer_path=spec["tokenizer_path"],
        base_url=spec["base_url"],
        api_key=spec["api_key"],
        model="default",
        temperature=float(spec["temperature"]),
        top_p=1.0,
        max_completion_tokens=int(spec["max_completion_tokens"]),
    )
    with output.open("a", encoding="utf-8") as stream:
        for index, item in enumerate(spec["items"], start=1):
            episode_key = str(item["episode_key"])
            if episode_key in completed:
                continue
            task = item["task"]
            task_id = str(task["task_id"])
            started = time.monotonic()
            try:
                episode = asyncio.run(runner.run(task, sample_seed=int(item["sample_seed"])))
                evaluation = evaluate_development(
                    final_answer=str(episode["final_answer"]),
                    trace=dict(episode["trace"]),
                    final_state=dict(episode["final_state"]),
                    grader=graders[task_id],
                ).to_dict()
                status = "SCORED" if evaluation["status"] == "SCORED" else "INFRA_EXCLUDED"
                error = None
            except Exception as exc:  # noqa: BLE001 - preserve per-episode failure evidence
                episode = {
                    "final_answer": "",
                    "messages": [],
                    "trace": {"runtime_errors": ["episode_exception"]},
                    "final_state": {},
                    "runtime": {"elapsed_seconds": round(time.monotonic() - started, 6)},
                }
                evaluation = {
                    "task_id": task_id,
                    "capability_id": task["capability_id"],
                    "status": "INFRA_EXCLUDED",
                    "strict_success": False,
                    "total": 0.0,
                    "hard_gate_reasons": ["runtime:episode_exception"],
                }
                status = "INFRA_EXCLUDED"
                error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
            row = {
                "schema_version": "studyhub.agentbench-episode.v1",
                "benchmark_version": BENCHMARK_VERSION,
                "run_id": spec["run_id"],
                "model": spec["model_identity"],
                "episode_key": episode_key,
                "task_id": task_id,
                "split": task["split"],
                "capability_id": task["capability_id"],
                "difficulty": task["difficulty"],
                "horizon_tier": task["horizon_tier"],
                "language": task["language"],
                "sample_index": item["sample_index"],
                "sample_seed": item["sample_seed"],
                "status": status,
                "error": error,
                "final_answer": episode["final_answer"],
                "messages": jsonable(episode["messages"]),
                "trace": jsonable(episode["trace"]),
                "final_state": jsonable(episode["final_state"]),
                "runtime": jsonable(episode["runtime"]),
                "evaluation": evaluation,
            }
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            completed.add(episode_key)
            print(
                f"worker={spec['worker_id']} {index}/{len(spec['items'])} "
                f"task={task_id} status={status} success={evaluation.get('strict_success')}",
                flush=True,
            )


def bootstrap_interval(values: list[float], seed: int, samples: int = 5000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choice(values) for _ in values) for _ in range(samples)]
    means.sort()
    return [round(means[int(samples * 0.025)], 6), round(means[int(samples * 0.975)], 6)]


def aggregate(rows: list[dict[str, Any]], *, mode: str, seed: int) -> dict[str, Any]:
    eligible = [row for row in rows if row["status"] == "SCORED"]
    strict = [float(bool(row["evaluation"]["strict_success"])) for row in eligible]
    totals = [float(row["evaluation"]["total"]) for row in eligible]
    capability_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        capability_rows[str(row["capability_id"])].append(row)
    capabilities = {
        capability: {
            "episodes": len(values),
            "strict_success_rate": round(
                statistics.fmean(float(bool(row["evaluation"]["strict_success"])) for row in values),
                6,
            ),
            "mean_score": round(statistics.fmean(float(row["evaluation"]["total"]) for row in values), 6),
        }
        for capability, values in sorted(capability_rows.items())
    }
    summary: dict[str, Any] = {
        "schema_version": "studyhub.agentbench-run-summary.v1",
        "benchmark_version": BENCHMARK_VERSION,
        "mode": mode,
        "episodes_expected": len(rows),
        "episodes_scored": len(eligible),
        "infra_excluded": len(rows) - len(eligible),
        "strict_success_rate": round(statistics.fmean(strict), 6) if strict else 0.0,
        "strict_success_ci95": bootstrap_interval(strict, seed),
        "mean_score": round(statistics.fmean(totals), 6) if totals else 0.0,
        "mean_score_ci95": bootstrap_interval(totals, seed + 1),
        "capabilities": capabilities,
        "status_counts": dict(Counter(str(row["status"]) for row in rows)),
        "tool_calls": {
            "mean": round(
                statistics.fmean(len(row.get("trace", {}).get("tool_calls", [])) for row in eligible),
                6,
            )
            if eligible
            else 0.0,
            "total": sum(len(row.get("trace", {}).get("tool_calls", [])) for row in eligible),
        },
        "latency_seconds": {
            "mean": round(statistics.fmean(float(row["runtime"].get("elapsed_seconds", 0)) for row in eligible), 6)
            if eligible
            else 0.0,
            "p95": 0.0,
        },
    }
    latencies = sorted(float(row["runtime"].get("elapsed_seconds", 0)) for row in eligible)
    if latencies:
        latency_index = min(len(latencies) - 1, math.ceil(len(latencies) * 0.95) - 1)
        summary["latency_seconds"]["p95"] = round(latencies[latency_index], 6)
    if mode == "variance":
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in eligible:
            grouped[str(row["task_id"])].append(row)
        complete = {task_id: values for task_id, values in grouped.items() if len(values) == VARIANCE_SAMPLES}
        expected_task_count = len(rows) // VARIANCE_SAMPLES
        summary["variance_panel"] = {
            "tasks_expected": expected_task_count,
            "tasks_complete": len(complete),
            "tasks_incomplete": expected_task_count - len(complete),
            "pass_at_4": round(
                statistics.fmean(
                    any(bool(row["evaluation"]["strict_success"]) for row in values)
                    for values in complete.values()
                ),
                6,
            )
            if complete
            else 0.0,
            "consistent_at_4": round(
                statistics.fmean(
                    all(bool(row["evaluation"]["strict_success"]) for row in values)
                    for values in complete.values()
                ),
                6,
            )
            if complete
            else 0.0,
            "mixed_outcome_rate": round(
                statistics.fmean(
                    0 < sum(bool(row["evaluation"]["strict_success"]) for row in values) < VARIANCE_SAMPLES
                    for values in complete.values()
                ),
                6,
            )
            if complete
            else 0.0,
        }
    n = len({str(row["task_id"]) for row in eligible})
    p = summary["strict_success_rate"]
    summary["approx_independent_mde_80_power_pp"] = round(
        100 * (1.96 + 0.84) * math.sqrt(max(2 * p * (1 - p), 0.02) / max(n, 1)),
        3,
    )
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    from scripts.train.prepare_sglang_model_overlay import prepare_overlay

    project = args.project.resolve()
    public_root = args.public_root.resolve()
    hidden_root = args.hidden_root.resolve()
    split = "regression" if args.mode in {"gate", "regression"} else "development"
    tasks = load_jsonl(public_root / split / "tasks.jsonl")
    selected = select_tasks(tasks, args.mode, args.seed)
    items = build_work_items(selected, args.mode, args.seed)
    manifest = json.loads((public_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") not in {"FROZEN_FOR_BASELINE", "FROZEN_TRAINING_READY"}:
        raise RuntimeError("Benchmark v1 must be frozen before the 9B Base evaluation")
    trial = args.trial or f"qwen35-9b-base-{args.mode}-seed-{args.seed}-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    output_root = (args.output_root / trial).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    api_key = secrets.token_urlsafe(36)
    model_overlay = project / "artifacts/areal/model-overlays/9b-base-benchmark"
    prepare_overlay(args.model.resolve(), model_overlay)
    ports = [args.port_base + index for index in range(args.workers)]
    endpoints = [f"http://127.0.0.1:{port}/v1" for port in ports]
    servers: list[subprocess.Popen[str]] = []
    streams = []
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    started_monotonic = time.monotonic()
    try:
        for worker_id in range(args.workers):
            server, stream = launch_server(
                python=sys.executable,
                model=model_overlay,
                gpu=args.gpus[worker_id],
                port=ports[worker_id],
                api_key=api_key,
                log_path=output_root / f"server-{worker_id}.log",
                project=project,
            )
            servers.append(server)
            streams.append(stream)
        for endpoint, server in zip(endpoints, servers, strict=True):
            wait_for_server(endpoint, server, args.server_timeout, api_key)

        context = mp.get_context("spawn")
        workers = []
        for worker_id in range(args.workers):
            shard = items[worker_id :: args.workers]
            spec = {
                "worker_id": worker_id,
                "items": shard,
                "output": str(output_root / f"episodes-worker-{worker_id}.jsonl"),
                "run_id": trial,
                "model_identity": "Qwen/Qwen3.5-9B@c202236235762e1c871ad0ccb60c8ee5ba337b9a",
                "hidden_root": str(hidden_root),
                "grader_path": str(hidden_root / f"graders/{split}.jsonl"),
                "hermes_checkout": str(args.hermes_checkout.resolve()),
                "tokenizer_path": str(args.model.resolve()),
                "base_url": endpoints[worker_id],
                "api_key": api_key,
                "temperature": args.temperature,
                "max_completion_tokens": args.max_completion_tokens,
            }
            process = context.Process(target=worker_main, args=(spec,), name=f"benchmark-worker-{worker_id}")
            process.start()
            workers.append(process)
        for process in workers:
            process.join()
        failed_workers = [process.name for process in workers if process.exitcode != 0]
        if failed_workers:
            raise RuntimeError(f"benchmark workers failed: {failed_workers}")
    finally:
        for server in servers:
            if server.poll() is None:
                server.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 20
        for server in servers:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                server.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        for stream in streams:
            stream.close()

    rows = []
    for worker_id in range(args.workers):
        rows.extend(load_jsonl(output_root / f"episodes-worker-{worker_id}.jsonl"))
    by_key = {str(row["episode_key"]): row for row in rows}
    expected_keys = {str(item["episode_key"]) for item in items}
    if set(by_key) != expected_keys:
        missing = len(expected_keys - set(by_key))
        extra = len(set(by_key) - expected_keys)
        raise RuntimeError(
            f"episode completeness mismatch: missing={missing} extra={extra}"
        )
    merged = output_root / "episodes.jsonl"
    merged.write_text(
        "".join(json.dumps(by_key[key], ensure_ascii=False, sort_keys=True) + "\n" for key in sorted(by_key)),
        encoding="utf-8",
    )
    summary = aggregate(list(by_key.values()), mode=args.mode, seed=args.seed)
    summary.update(
        {
            "run_id": trial,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
            "model": "Qwen/Qwen3.5-9B@c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "benchmark_content_sha256": manifest["content_sha256"],
            "benchmark_manifest_sha256": sha256(public_root / "manifest.json"),
            "episodes_sha256": sha256(merged),
            "seed": args.seed,
            "temperature": args.temperature,
            "workers": args.workers,
            "gpus": args.gpus,
        }
    )
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    model_manifest = json.loads((args.model / "studyhub_download_manifest.json").read_text(encoding="utf-8"))
    run_manifest = {
        "schema_version": "studyhub.agentbench-run-manifest.v1",
        "run_id": trial,
        "git": {
            "commit": git_value(project, "rev-parse", "HEAD"),
            "dirty": bool(git_value(project, "status", "--porcelain")),
        },
        "benchmark": {
            "version": BENCHMARK_VERSION,
            "content_sha256": manifest["content_sha256"],
            "manifest_sha256": sha256(public_root / "manifest.json"),
        },
        "model": model_manifest,
        "runtime": {
            "hermes_commit": git_value(args.hermes_checkout.resolve(), "rev-parse", "HEAD"),
            "areal_commit": git_value(project / ".cache/areal-src", "rev-parse", "HEAD"),
            "python": sys.version,
            "sglang": "0.5.10.post1",
            "optimizer_steps": 0,
        },
        "config": {
            "mode": args.mode,
            "seed": args.seed,
            "temperature": args.temperature,
            "max_completion_tokens": args.max_completion_tokens,
            "workers": args.workers,
            "gpus": args.gpus,
        },
        "artifacts": {
            "episodes": {"path": str(merged), "sha256": sha256(merged)},
            "summary": {"path": str(output_root / "summary.json"), "sha256": sha256(output_root / "summary.json")},
        },
    }
    (output_root / "run-manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("gate", "regression", "development", "variance"))
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v1")
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1",
    )
    parser.add_argument("--model", type=Path, default=project.parent / "models/P1/Qwen3.5-9B")
    parser.add_argument("--hermes-checkout", type=Path, default=project / ".vendor/hermes-agent")
    parser.add_argument("--output-root", type=Path, default=project / "artifacts/benchmark-v1/runs")
    parser.add_argument("--trial")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-completion-tokens", type=int, default=1536)
    parser.add_argument("--workers", type=int, default=2, choices=(1, 2))
    parser.add_argument("--gpus", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--port-base", type=int, default=30120)
    parser.add_argument("--server-timeout", type=float, default=1200.0)
    args = parser.parse_args()
    if len(args.gpus) != args.workers:
        parser.error("--gpus must provide exactly one GPU per worker")
    if args.mode == "variance" and args.temperature <= 0:
        args.temperature = 0.7
    return args


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["infra_excluded"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
