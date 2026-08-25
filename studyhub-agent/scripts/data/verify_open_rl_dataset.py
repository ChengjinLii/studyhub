#!/usr/bin/env python3
"""Audit the isolated Agent RL package without starting a model or trainer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

FORBIDDEN_PUBLIC_KEYS = {
    "answer",
    "answers",
    "expected_answer",
    "expected_answers",
    "expected_calls",
    "gold_answer",
    "gold_evidence",
    "gold_source_ids",
    "gold_tool_sequence",
    "supporting_facts",
}
TOOL_CALL_SHAPED_ANSWER = re.compile(r"^\s*\[?[A-Za-z_][A-Za-z0-9_]*\s*\(")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect_keys(value: Any) -> set[str]:
    keys = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(collect_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(collect_keys(item))
    return keys


def load_sft_groups(metadata_root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    ids: dict[str, set[str]] = defaultdict(set)
    groups: dict[str, set[str]] = defaultdict(set)
    for path in sorted(metadata_root.glob("*.jsonl")):
        for row in read_jsonl(path):
            source = row["source_dataset"]
            ids[source].add(str(row["source_id"]))
            groups[source].add(str(row.get("group_id", row["source_id"])))
    return ids, groups


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=project / "datasets/processed/open_agent_rl_v1")
    parser.add_argument(
        "--sft-metadata", type=Path, default=project / "datasets/processed/open_sft_bootstrap_v2/metadata"
    )
    parser.add_argument("--output", type=Path, default=project / "artifacts/areal/open-rl-dataset-audit-v1.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from datasets import load_from_disk
    from studyhub_agent.runtime import TaskSpec

    manifest_path = args.dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = load_from_disk(args.dataset / "hf_dataset")
    environment_index = {row["task_id"]: row for row in read_jsonl(args.dataset / "environment_manifest.jsonl")}
    sft_ids, sft_groups = load_sft_groups(args.sft_metadata)
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    observed_ids = set()
    split_groups: dict[str, set[tuple[str, str]]] = {}
    split_details = {}
    for split in ("train", "validation"):
        tasks_path = args.dataset / "tasks" / f"{split}.jsonl"
        verifiers_path = args.dataset / "verifiers" / f"{split}.jsonl"
        tasks = read_jsonl(tasks_path)
        verifiers = read_jsonl(verifiers_path)
        verifier_index = {row["verifier_id"]: row for row in verifiers}
        tensor_rows = dataset[split]
        check(len(tasks) == manifest["split_counts"][split], f"{split}: manifest count mismatch")
        check(len(tasks) == len(tensor_rows), f"{split}: HF/task count mismatch")
        check(len(verifiers) == len(tasks), f"{split}: verifier/task count mismatch")
        check(sha256(tasks_path) == manifest["task_sha256"][split], f"{split}: task hash mismatch")
        check(sha256(verifiers_path) == manifest["verifier_sha256"][split], f"{split}: verifier hash mismatch")

        family_counts = Counter()
        source_counts = Counter()
        groups = set()
        for index, task in enumerate(tasks):
            task_id = task.get("task_id", "")
            check(task_id not in observed_ids, f"duplicate task_id: {task_id}")
            observed_ids.add(task_id)
            try:
                TaskSpec.from_dict(task)
            except Exception as exc:
                failures.append(f"{split}[{index}]: invalid TaskSpec: {exc}")
                continue
            check(task["verifier"] == {}, f"{task_id}: verifier leaked into public task")
            leaked_keys = collect_keys(task) & FORBIDDEN_PUBLIC_KEYS
            check(not leaked_keys, f"{task_id}: public oracle keys {sorted(leaked_keys)}")
            metadata = task["metadata"]
            check(metadata.get("oracle_fields_exposed") is False, f"{task_id}: oracle policy flag")
            check(metadata.get("split") == split, f"{task_id}: split metadata mismatch")
            source = metadata["source_dataset"]
            source_id = metadata["source_id"]
            group_id = metadata["group_id"]
            check(source != "coig_exam", f"{task_id}: COIG is not allowed in phase-one RL")
            check(source_id not in sft_ids[source], f"{task_id}: overlaps SFT source_id")
            check(group_id not in sft_groups[source], f"{task_id}: overlaps SFT group")
            groups.add((source, group_id))
            source_counts[source] += 1
            family_counts[task["family"]] += 1

            check(task_id in environment_index, f"{task_id}: missing environment manifest row")
            environment_path = args.dataset / "environments" / f"{task_id}.json"
            check(environment_path.is_file(), f"{task_id}: missing frozen environment")
            if not environment_path.is_file():
                continue
            environment = json.loads(environment_path.read_text(encoding="utf-8"))
            check(
                sha256(environment_path) == environment_index[task_id]["environment_sha256"],
                f"{task_id}: environment hash mismatch",
            )
            check(environment.get("environment_id") == task_id, f"{task_id}: environment ID mismatch")
            tool_names = {tool["name"] for tool in environment.get("tools", [])}
            check(tool_names == set(task["allowed_tools"]), f"{task_id}: allowed tool mismatch")
            check(not (collect_keys(environment) & FORBIDDEN_PUBLIC_KEYS), f"{task_id}: oracle in environment")
            document_ids = {document["source_id"] for document in environment.get("documents", [])}

            verifier = verifier_index.get(task_id)
            check(verifier is not None, f"{task_id}: hidden verifier missing")
            if verifier is None:
                continue
            check(verifier.get("task_id") == task_id, f"{task_id}: verifier task mismatch")
            check(
                set(verifier.get("gold_source_ids", [])).issubset(document_ids),
                f"{task_id}: verifier references unknown document",
            )
            for expected_call in verifier.get("expected_calls", []):
                check(expected_call.get("name") in tool_names, f"{task_id}: unknown expected tool")

            fixture_path = args.dataset / "fixtures" / f"{task_id}.json"
            fixture_hash = environment_index[task_id].get("fixture_sha256")
            if task["family"] == "function_calling":
                expected_calls = verifier.get("expected_calls", [])
                check(
                    len(expected_calls) <= task["max_tool_calls"],
                    f"{task_id}: expected calls exceed tool budget",
                )
                if source == "toolace":
                    for answer in verifier.get("expected_answers", []):
                        check(
                            not TOOL_CALL_SHAPED_ANSWER.match(str(answer)),
                            f"{task_id}: expected final answer is an unexecuted tool call",
                        )
                check(fixture_path.is_file(), f"{task_id}: function fixture missing")
                if fixture_path.is_file():
                    check(sha256(fixture_path) == fixture_hash, f"{task_id}: fixture hash mismatch")
                    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                    routes = {(row["name"], json.dumps(row["arguments"], sort_keys=True)) for row in fixture["routes"]}
                    expected = {
                        (row["name"], json.dumps(row["arguments"], sort_keys=True))
                        for row in verifier.get("expected_calls", [])
                    }
                    check(expected.issubset(routes), f"{task_id}: expected call has no fixture route")
            else:
                check(not fixture_path.exists() and fixture_hash is None, f"{task_id}: unexpected fixture")

        split_groups[split] = groups
        check(dict(source_counts) == manifest["source_split_counts_by_split"][split], f"{split}: source counts")
        check(dict(family_counts) == manifest["family_counts"][split], f"{split}: family counts")
        split_details[split] = {
            "tasks": len(tasks),
            "groups": len(groups),
            "source_counts": dict(sorted(source_counts.items())),
            "family_counts": dict(sorted(family_counts.items())),
        }

    group_overlap = len(split_groups["train"] & split_groups["validation"])
    check(group_overlap == 0, f"train/validation group overlap: {group_overlap}")
    check(len(environment_index) == len(observed_ids), "environment/task cardinality mismatch")
    check(
        sha256(args.dataset / "environment_manifest.jsonl") == manifest["environment_manifest_sha256"],
        "environment manifest hash mismatch",
    )
    result = {
        "schema_version": "studyhub.open-rl-dataset-audit.v1",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": str(args.dataset.resolve()),
        "dataset_manifest_sha256": sha256(manifest_path),
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "split_details": split_details,
        "group_overlap": group_overlap,
        "unique_tasks": len(observed_ids),
        "oracle_separation": "passed" if not any("oracle" in item for item in failures) else "failed",
        "sft_overlap": "passed" if not any("overlaps SFT" in item for item in failures) else "failed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
