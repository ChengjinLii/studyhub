#!/usr/bin/env python3
"""Teacher-forced protocol evaluation for the frozen M1 holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for import_root in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.benchmark.run_9b_base_eval import (  # noqa: E402
    launch_server,
    resolve_model_artifact,
    wait_for_server,
)
from studyhub_agent.eval.protocol_holdout import (  # noqa: E402
    ProtocolItem,
    build_protocol_items,
    canonical_json,
    classify_chat_completion,
    item_manifest,
    score_protocol_item,
    select_protocol_rows,
    stable_rank,
    summarize_protocol_results,
    wire_messages,
)

DEFAULT_SEED = 20260827


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise RuntimeError(f"expected JSON objects: {path}")
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def validate_contract(project: Path, config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = read_json(config_path)
    if contract.get("status") != "FROZEN_BEFORE_M1_COMPLETION":
        raise RuntimeError("protocol holdout contract is not frozen")
    dataset = contract["dataset"]
    for relative_key, hash_key in (
        ("selected_relative_path", "selected_sha256"),
        ("tokenized_manifest_relative_path", "tokenized_manifest_sha256"),
        ("data_audit_relative_path", "data_audit_sha256"),
    ):
        path = project / str(dataset[relative_key])
        if not path.is_file() or sha256(path) != dataset[hash_key]:
            raise RuntimeError(f"protocol holdout lineage drift: {path}")
    audit = read_json(project / str(dataset["data_audit_relative_path"]))
    expected_rows = int(contract["expected_rows"])
    if int(audit.get("rows", {}).get("protocol_holdout", -1)) != expected_rows:
        raise RuntimeError("protocol holdout row count drift")
    isolation = audit.get("isolation", {})
    if isolation.get("sealed_content_read") is not False:
        raise RuntimeError("protocol holdout audit does not prove sealed isolation")
    if isolation.get("split_group_overlap", {}).get("train_protocol_holdout") != 0:
        raise RuntimeError("training and protocol holdout groups overlap")
    loss_mask = audit.get("loss_mask", {})
    if loss_mask.get("system_user_tool_tokens_masked") is not True:
        raise RuntimeError("tool-observation masking audit did not pass")
    return contract, audit


def _tool_names(item: ProtocolItem) -> set[str]:
    return {
        str(tool.get("function", {}).get("name", ""))
        for tool in item.tools
        if isinstance(tool.get("function"), dict)
    }


def request_body(item: ProtocolItem, contract: dict[str, Any], *, seed: int) -> dict[str, Any]:
    evaluation = contract["evaluation"]
    body: dict[str, Any] = {
        "model": "default",
        "messages": wire_messages(item.prefix_messages),
        "temperature": float(evaluation["temperature"]),
        "top_p": float(evaluation["top_p"]),
        "max_completion_tokens": int(evaluation["max_completion_tokens"]),
        "seed": int(stable_rank(seed, item.item_id)[:8], 16),
        "parallel_tool_calls": True,
        "chat_template_kwargs": {"enable_thinking": bool(evaluation["enable_thinking"])},
    }
    if item.tools:
        body["tools"] = list(item.tools)
        body["tool_choice"] = "auto"
    return body


def post_completion(
    base_url: str,
    api_key: str,
    body: dict[str, Any],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - caller supplies fixed localhost endpoint
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode())
            if not isinstance(payload, dict):
                raise RuntimeError("chat completion returned a non-object payload")
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == 2:
                detail = exc.read().decode(errors="replace")[:1000]
                raise RuntimeError(f"chat completion HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt == 2:
                raise RuntimeError(f"chat completion transport failure: {exc}") from exc
        time.sleep(2**attempt)
    raise AssertionError("unreachable completion retry state")


def _completed(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        str(row["item_id"])
        for row in read_jsonl(path)
        if row.get("status") == "SCORED"
    }


def evaluate_shard(
    *,
    worker_id: int,
    items: list[ProtocolItem],
    output: Path,
    base_url: str,
    api_key: str,
    contract: dict[str, Any],
    seed: int,
    timeout_seconds: int,
) -> None:
    completed = _completed(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as stream:
        for index, item in enumerate(items, 1):
            if item.item_id in completed:
                continue
            body = request_body(item, contract, seed=seed)
            started = time.monotonic()
            try:
                payload = post_completion(base_url, api_key, body, timeout_seconds=timeout_seconds)
                response = classify_chat_completion(payload, allowed_tool_names=_tool_names(item))
                choices = payload.get("choices") or []
                first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                row = {
                    **score_protocol_item(item, response),
                    "status": "SCORED",
                    "error": None,
                    "request_sha256": hashlib.sha256(canonical_json(body).encode()).hexdigest(),
                    "request_messages": len(body["messages"]),
                    "tool_schema_count": len(item.tools),
                    "latency_seconds": round(time.monotonic() - started, 6),
                    "finish_reason": first_choice.get("finish_reason"),
                    "usage": payload.get("usage", {}),
                }
            except Exception as exc:  # noqa: BLE001 - preserve resumable per-item infra evidence
                row = {
                    **item_manifest(item),
                    "status": "INFRA_EXCLUDED",
                    "error": {"type": type(exc).__name__, "message": str(exc)[:1000]},
                    "latency_seconds": round(time.monotonic() - started, 6),
                }
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            print(
                f"worker={worker_id} item={index}/{len(items)} kind={item.expected_kind} "
                f"status={row['status']} pass={row.get('target_pass')}",
                flush=True,
            )


def merge_worker_rows(paths: list[Path], output: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.is_file():
            continue
        for row in read_jsonl(path):
            item_id = str(row["item_id"])
            previous = latest.get(item_id)
            if previous is None or row.get("status") == "SCORED":
                latest[item_id] = row
    rows = [latest[item_id] for item_id in sorted(latest)]
    temporary = output.with_suffix(output.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, output)
    return rows


def _terminate(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
    deadline = time.monotonic() + 30
    for process in processes:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.5)
        if process.poll() is None:
            process.terminate()


def git_value(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=project.parent,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def parse_args() -> argparse.Namespace:
    project = PROJECT_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=project / "configs/eval/qwen35-4b-sft1-protocol-holdout-v1.json",
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--gpus", default="0,1")
    parser.add_argument("--ports", default="30310,30311")
    parser.add_argument("--python", default=str(project / ".venv-train/bin/python"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--server-timeout", type=int, default=1200)
    parser.add_argument("--request-timeout", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = PROJECT_ROOT
    contract, data_audit = validate_contract(project, args.config.resolve())
    dataset_path = project / contract["dataset"]["selected_relative_path"]
    selected_rows = select_protocol_rows(read_jsonl(dataset_path), max_rows=args.max_rows, seed=args.seed)
    if not args.max_rows and len(selected_rows) != int(contract["expected_rows"]):
        raise RuntimeError("formal protocol holdout did not select all frozen rows")
    items = build_protocol_items(selected_rows)
    if not items:
        raise RuntimeError("protocol holdout produced no assistant-turn items")
    if not args.max_rows:
        kinds = Counter(item.expected_kind for item in items)
        observation_items = sum(item.observation_conditioned for item in items)
        if len(items) != int(contract["expected_assistant_turn_items"]):
            raise RuntimeError("formal protocol holdout assistant-turn count drift")
        if dict(sorted(kinds.items())) != dict(sorted(contract["expected_kinds"].items())):
            raise RuntimeError("formal protocol holdout target-kind distribution drift")
        if observation_items != int(contract["expected_observation_conditioned_items"]):
            raise RuntimeError("formal protocol holdout observation-conditioned count drift")

    model_identity, model_manifest = resolve_model_artifact(args.model)
    repository_clean = not bool(git_value(project, "status", "--porcelain"))
    if not repository_clean:
        raise RuntimeError("protocol holdout requires a clean Git worktree")
    gpus = [int(value) for value in args.gpus.split(",") if value.strip()]
    ports = [int(value) for value in args.ports.split(",") if value.strip()]
    if not gpus or len(gpus) != len(ports):
        raise ValueError("gpus and ports must contain the same non-zero number of values")
    run_id = args.run_id or f"qwen35-4b-sft1-protocol-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_root = args.output_root.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    api_key = secrets.token_urlsafe(24)
    processes: list[subprocess.Popen[str]] = []
    streams: list[Any] = []
    base_urls: list[str] = []
    started = time.monotonic()
    manifest = {
        "schema_version": "studyhub.sft1-protocol-holdout-run.v1",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": git_value(project, "rev-parse", "HEAD"),
        "git_status_clean": repository_clean,
        "config_sha256": sha256(args.config.resolve()),
        "dataset_sha256": sha256(dataset_path),
        "data_audit_sha256": sha256(project / contract["dataset"]["data_audit_relative_path"]),
        "model": model_identity,
        "model_manifest": model_manifest,
        "selected_rows": len(selected_rows),
        "assistant_turn_items": len(items),
        "formal_gate": args.max_rows == 0,
        "seed": args.seed,
        "gpus": gpus,
        "ports": ports,
        "claim_boundary": contract["claim_boundary"],
    }
    write_json(run_root / "run-manifest.json", manifest)

    try:
        for worker_id, (gpu, port) in enumerate(zip(gpus, ports, strict=True)):
            base_url = f"http://127.0.0.1:{port}/v1"
            process, stream = launch_server(
                python=args.python,
                model=args.model.resolve(),
                gpu=gpu,
                port=port,
                api_key=api_key,
                log_path=run_root / f"server-{worker_id}.log",
                project=project,
            )
            processes.append(process)
            streams.append(stream)
            base_urls.append(base_url)
        for base_url, process in zip(base_urls, processes, strict=True):
            wait_for_server(base_url, process, args.server_timeout, api_key)

        shards: list[list[ProtocolItem]] = [[] for _ in base_urls]
        for item in items:
            shard = int(stable_rank(args.seed, item.item_id)[:8], 16) % len(shards)
            shards[shard].append(item)
        worker_paths = [run_root / f"episodes-worker-{index}.jsonl" for index in range(len(shards))]
        with ThreadPoolExecutor(max_workers=len(shards)) as executor:
            futures = [
                executor.submit(
                    evaluate_shard,
                    worker_id=index,
                    items=shard,
                    output=worker_paths[index],
                    base_url=base_urls[index],
                    api_key=api_key,
                    contract=contract,
                    seed=args.seed,
                    timeout_seconds=args.request_timeout,
                )
                for index, shard in enumerate(shards)
            ]
            for future in futures:
                future.result()
    finally:
        _terminate(processes)
        for stream in streams:
            stream.close()

    episodes_path = run_root / "episodes.jsonl"
    rows = merge_worker_rows(worker_paths, episodes_path)
    thresholds = contract["thresholds"]
    summary = summarize_protocol_results(
        rows,
        expected_items=len(items),
        expected_rows=len(selected_rows),
        tool_call_parse_minimum=float(thresholds["tool_call_parse_minimum"]),
        final_nonempty_minimum=float(thresholds["final_nonempty_minimum"]),
        observation_mask_pass=bool(data_audit["loss_mask"]["system_user_tool_tokens_masked"]),
    )
    if args.max_rows:
        summary["formal_gate_evaluated"] = False
        summary["formal_status_if_full"] = summary["status"]
        summary["status"] = (
            "PASS_PROTOCOL_HOLDOUT_SMOKE"
            if summary["gates"]["all_items_scored"]
            else "INCOMPLETE_PROTOCOL_HOLDOUT_SMOKE"
        )
    else:
        summary["formal_gate_evaluated"] = True
    summary.update(
        {
            "run_id": run_id,
            "model": model_identity,
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "episodes_sha256": sha256(episodes_path),
            "config_sha256": manifest["config_sha256"],
            "dataset_sha256": manifest["dataset_sha256"],
            "data_audit_sha256": manifest["data_audit_sha256"],
        }
    )
    write_json(run_root / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
