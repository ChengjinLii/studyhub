#!/usr/bin/env python3
"""Collect resumable Teacher-to-Hermes trajectories without exposing hidden verifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.data.verify_teacher_trajectories import verify_root, verify_run  # noqa: E402
from training.teacher.hermes_controller import collect_trajectory  # noqa: E402
from training.teacher.providers import TeacherProviderError, build_provider  # noqa: E402

TEACHERS = ("codex-spark", "responses-api", "authorized-openai-compatible", "local-best-of-n")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _git_head() -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _hermes_commit() -> str:
    return str(_read_json(PROJECT_ROOT / "integrations/hermes/upstream.lock.json")["commit"])


def _load_tasks(root: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in (root / "task_specs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return sorted(
        rows,
        key=lambda row: hashlib.sha256(f"teacher-collection:{row['task_id']}".encode()).hexdigest(),
    )


def _run_id(
    task: dict[str, Any],
    teacher: str,
    model: str,
    candidate_index: int,
    collector_git_commit: str,
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "task_id": task["task_id"],
                "teacher": teacher,
                "model": model,
                "candidate_index": candidate_index,
                "collector_git_commit": collector_git_commit,
                "task": task,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return f"{task['task_id']}-{teacher}-{candidate_index:02d}-{digest}"


def _provider_failure_action(
    provider: Any,
    task: dict[str, Any],
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    turn: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return provider.choose_action(task, tools, messages, turn)
    except TeacherProviderError as exc:
        return (
            {"type": "provider_failure", "name": "", "arguments": {}, "content": ""},
            {**exc.event, "error_code": exc.code},
        )
    except Exception as exc:  # A raw run is still required for offline failure analysis.
        return (
            {"type": "provider_failure", "name": "", "arguments": {}, "content": ""},
            {"error_code": "unexpected_provider_error", "exception_type": type(exc).__name__},
        )


def _collect_job(job: dict[str, Any]) -> dict[str, Any]:
    root = Path(job["root"])
    task = job["task"]
    provider = build_provider(
        job["teacher"],
        model=job["model"],
        timeout_seconds=int(job["request_timeout"]),
    )
    started = time.time()

    def choose_action(
        current_task: dict[str, Any],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        turn: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return _provider_failure_action(provider, current_task, tools, messages, turn)

    run = collect_trajectory(
        task=task,
        root=root,
        hermes_checkout=Path(job["hermes_checkout"]),
        hermes_commit=job["hermes_commit"],
        choose_action=choose_action,
    )
    run.update(
        {
            "run_id": job["run_id"],
            "candidate_index": job["candidate_index"],
            "collection_mode": (
                "dagger_repair" if run.get("controller", {}).get("policy_corrections") else "teacher_rollout"
            ),
            "provider": {
                "interface": provider.interface,
                "model": provider.model,
                "requested_teacher": job["teacher"],
            },
            "collector_git_commit": job["collector_git_commit"],
            "raw_run_path": f"raw_runs/{job['run_id']}.json",
            "started_at_unix": started,
            "completed_at_unix": time.time(),
        }
    )
    verifier = _read_json(root / "verifiers" / f"{task['task_id']}.json")
    failures, diagnostics = verify_run(run, task, verifier)
    return {"run": run, "accepted": not failures, "failures": failures, "diagnostics": diagnostics}


def _jobs(
    tasks: Iterable[dict[str, Any]],
    *,
    root: Path,
    teacher: str,
    model: str,
    candidates_per_task: int,
    request_timeout: int,
    collector_git_commit: str,
    hermes_commit: str,
) -> list[dict[str, Any]]:
    result = []
    for task in tasks:
        for candidate_index in range(candidates_per_task):
            run_id = _run_id(task, teacher, model, candidate_index, collector_git_commit)
            result.append(
                {
                    "root": str(root),
                    "task": task,
                    "teacher": teacher,
                    "model": model,
                    "candidate_index": candidate_index,
                    "run_id": run_id,
                    "request_timeout": request_timeout,
                    "collector_git_commit": collector_git_commit,
                    "hermes_checkout": str(PROJECT_ROOT / ".vendor/hermes-agent"),
                    "hermes_commit": hermes_commit,
                }
            )
    return result


def _existing_result(root: Path, job: dict[str, Any]) -> dict[str, Any] | None:
    path = root / "raw_runs" / f"{job['run_id']}.json"
    if not path.is_file():
        return None
    run = _read_json(path)
    task = job["task"]
    verifier = _read_json(root / "verifiers" / f"{task['task_id']}.json")
    failures, diagnostics = verify_run(run, task, verifier)
    return {"run": run, "accepted": not failures, "failures": failures, "diagnostics": diagnostics}


def _write_run(root: Path, result: dict[str, Any]) -> None:
    run = result["run"]
    _write_json(root / "raw_runs" / f"{run['run_id']}.json", run)


def _terminal_provider_stop(result: dict[str, Any]) -> str | None:
    failures = set(result.get("failures", []))
    if "provider:codex_usage_limit" in failures:
        return "PROVIDER_USAGE_LIMIT"
    if "provider:codex_rate_limit" in failures:
        return "PROVIDER_RATE_LIMIT"
    return None


def _stratified_tasks(tasks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        by_family.setdefault(str(task.get("family", "unknown")), []).append(task)
    selected: list[dict[str, Any]] = []
    offsets = {family: 0 for family in by_family}
    families = sorted(by_family)
    while families and len(selected) < limit:
        next_families = []
        for family in families:
            offset = offsets[family]
            rows = by_family[family]
            if offset >= len(rows):
                continue
            selected.append(rows[offset])
            offsets[family] += 1
            if offsets[family] < len(rows):
                next_families.append(family)
            if len(selected) == limit:
                break
        families = next_families
    return selected


def _progress_manifest(
    *,
    root: Path,
    teacher: str,
    model: str,
    requested: int,
    completed: int,
    accepted: int,
    rejected: int,
    started: float,
    status: str,
) -> None:
    _write_json(
        root / "collection-progress.json",
        {
            "schema_version": "studyhub.teacher-collection-progress.v1",
            "status": status,
            "teacher": teacher,
            "model": model,
            "requested_jobs": requested,
            "completed_rollouts": completed,
            "accepted": accepted,
            "rejected": rejected,
            "acceptance_rate": round(accepted / max(completed, 1), 6),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        },
    )


def _collect_sequential(
    jobs: list[dict[str, Any]],
    *,
    root: Path,
    max_accepted: int,
    deadline: float,
    resume: bool,
) -> tuple[int, int, int, str | None]:
    completed = accepted = rejected = 0
    stop_reason: str | None = None
    for job in jobs:
        if accepted >= max_accepted or time.monotonic() >= deadline:
            break
        existing = _existing_result(root, job)
        if existing is not None:
            if not resume:
                raise FileExistsError(f"raw run exists; use --resume: {job['run_id']}")
            result = existing
        else:
            remaining = max(1, int(deadline - time.monotonic()))
            job = {**job, "request_timeout": min(int(job["request_timeout"]), remaining)}
            result = _collect_job(job)
            _write_run(root, result)
        completed += 1
        if result["accepted"]:
            accepted += 1
        else:
            rejected += 1
        stop_reason = _terminal_provider_stop(result)
        if stop_reason:
            break
    return completed, accepted, rejected, stop_reason


def _collect_parallel(
    jobs: list[dict[str, Any]],
    *,
    root: Path,
    max_accepted: int,
    deadline: float,
    resume: bool,
    concurrency: int,
) -> tuple[int, int, int, str | None]:
    completed = accepted = rejected = 0
    stop_reason: str | None = None
    remaining_jobs = iter(jobs)
    pending: dict[Any, dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=concurrency) as executor:
        while time.monotonic() < deadline and accepted < max_accepted:
            slots = min(concurrency - len(pending), max_accepted - accepted - len(pending))
            for _ in range(max(0, slots)):
                try:
                    job = next(remaining_jobs)
                except StopIteration:
                    break
                existing = _existing_result(root, job)
                if existing is not None:
                    if not resume:
                        raise FileExistsError(f"raw run exists; use --resume: {job['run_id']}")
                    completed += 1
                    if existing["accepted"]:
                        accepted += 1
                    else:
                        rejected += 1
                    continue
                remaining = max(1, int(deadline - time.monotonic()))
                prepared = {**job, "request_timeout": min(int(job["request_timeout"]), remaining)}
                pending[executor.submit(_collect_job, prepared)] = prepared
            if not pending:
                break
            done, _ = wait(pending, timeout=max(0.1, deadline - time.monotonic()), return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                pending.pop(future)
                result = future.result()
                _write_run(root, result)
                completed += 1
                if result["accepted"]:
                    accepted += 1
                else:
                    rejected += 1
                stop_reason = _terminal_provider_stop(result)
                if stop_reason:
                    break
            if stop_reason:
                break
        for future in pending:
            future.cancel()
    return completed, accepted, rejected, stop_reason


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "datasets/interim/studyhub_teacher_v2_3")
    parser.add_argument("--teacher", choices=TEACHERS, default="codex-spark")
    parser.add_argument("--teacher-model")
    parser.add_argument("--max-accepted", type=int, default=500)
    parser.add_argument("--max-wall-time", type=int, default=6 * 60 * 60)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--candidates-per-task", type=int, default=2)
    parser.add_argument("--max-tasks", type=int)
    parser.add_argument("--request-timeout", type=int, default=300)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--offline-verify", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.offline_verify:
        print(json.dumps(verify_root(args.root), ensure_ascii=False, indent=2))
        return 0
    if not 1 <= args.max_accepted <= 4_000:
        raise ValueError("--max-accepted must be in [1, 4000]")
    if not 1 <= args.max_wall_time <= 6 * 60 * 60:
        raise ValueError("--max-wall-time must be in [1, 21600]")
    if not 1 <= args.concurrency <= 16:
        raise ValueError("--concurrency must be in [1, 16]")
    if not 2 <= args.candidates_per_task <= 4:
        raise ValueError("--candidates-per-task must be in [2, 4]")
    if not (args.root / "task_specs.jsonl").is_file():
        raise FileNotFoundError("teacher task specs are missing")

    provider = build_provider(args.teacher, model=args.teacher_model, timeout_seconds=args.request_timeout)
    availability = provider.availability()
    _write_json(
        args.root / "teacher_interface.json",
        {
            "schema_version": "studyhub.teacher-interface.v1",
            "requested_teacher": args.teacher,
            "interface": provider.interface,
            "model": provider.model,
            "availability": availability,
            "hidden_oracle_available": False,
            "secrets_recorded": False,
        },
    )
    if not availability["available"]:
        print(json.dumps(availability, ensure_ascii=False, indent=2))
        return 2

    tasks = _load_tasks(args.root)
    if args.max_tasks is not None:
        if args.max_tasks < 1:
            raise ValueError("--max-tasks must be positive")
        tasks = _stratified_tasks(tasks, args.max_tasks)
    commit = _git_head()
    jobs = _jobs(
        tasks,
        root=args.root,
        teacher=args.teacher,
        model=provider.model,
        candidates_per_task=args.candidates_per_task,
        request_timeout=args.request_timeout,
        collector_git_commit=commit,
        hermes_commit=_hermes_commit(),
    )
    started = time.monotonic()
    _progress_manifest(
        root=args.root,
        teacher=args.teacher,
        model=provider.model,
        requested=len(jobs),
        completed=0,
        accepted=0,
        rejected=0,
        started=started,
        status="RUNNING",
    )
    deadline = started + args.max_wall_time
    if args.concurrency == 1:
        completed, accepted, rejected, stop_reason = _collect_sequential(
            jobs,
            root=args.root,
            max_accepted=args.max_accepted,
            deadline=deadline,
            resume=args.resume,
        )
    else:
        completed, accepted, rejected, stop_reason = _collect_parallel(
            jobs,
            root=args.root,
            max_accepted=args.max_accepted,
            deadline=deadline,
            resume=args.resume,
            concurrency=args.concurrency,
        )
    status = "TARGET_REACHED" if accepted >= args.max_accepted else stop_reason or "WALL_TIME_OR_TASKS_EXHAUSTED"
    _progress_manifest(
        root=args.root,
        teacher=args.teacher,
        model=provider.model,
        requested=len(jobs),
        completed=completed,
        accepted=accepted,
        rejected=rejected,
        started=started,
        status=status,
    )
    audit = verify_root(args.root)
    print(json.dumps({"collection_status": status, "verification": audit}, ensure_ascii=False, indent=2))
    return 0 if accepted else 3


if __name__ == "__main__":
    raise SystemExit(main())
