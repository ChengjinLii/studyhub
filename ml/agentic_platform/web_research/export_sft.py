from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.agentic_platform.domain.hashing import canonical_hash, canonical_json

from .dataset import build_web_router_eval_cases
from .local_policy import build_research_decision_messages
from .policy import DeterministicWebRouterPolicy
from .rl_environment import (
    FrozenWebResearchEnvironment,
    WebRLPilotScenario,
    build_web_rl_pilot_scenarios,
)


DATASET_NAMES = {
    "train": "studyhub_web_router_train",
    "validation": "studyhub_web_router_validation",
    "test": "studyhub_web_router_test",
}


def export_web_router_sft(
    dataset_dir: Path,
    *,
    include_multi_turn: bool = False,
) -> dict[str, object]:
    """Export frozen, production-prompt-aligned SFT records for LLaMA-Factory."""

    if dataset_dir.exists():
        raise FileExistsError(
            f"Web Router SFT dataset directory already exists: {dataset_dir}"
        )
    cases = build_web_router_eval_cases()
    policy = DeterministicWebRouterPolicy()
    by_split: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    family_counts: dict[str, Counter[str]] = {split: Counter() for split in by_split}
    for case in cases:
        decision = asyncio.run(policy.decide(case.state))
        row = {
            "messages": [
                *build_research_decision_messages(case.state),
                {
                    "role": "assistant",
                    "content": canonical_json(decision),
                },
            ],
            "case_id": case.case_id,
            "task_family": case.family,
            "state_hash": case.content_hash,
        }
        by_split[case.split].append(row)
        family_counts[case.split][case.family] += 1
    if include_multi_turn:
        for row in asyncio.run(_build_multi_turn_rows(policy)):
            split = str(row.pop("split"))
            by_split[split].append(row)
            family_counts[split][str(row["task_family"])] += 1

    dataset_dir.mkdir(parents=True, exist_ok=False)
    dataset_info: dict[str, object] = {}
    files: dict[str, object] = {}
    for split, rows in by_split.items():
        filename = f"web_router_{split}.jsonl"
        path = dataset_dir / filename
        _write_jsonl(path, rows)
        dataset_info[DATASET_NAMES[split]] = {
            "file_name": filename,
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
            },
        }
        files[filename] = {
            "records": len(rows),
            "sha256": _sha256_file(path),
        }

    dataset_info_path = dataset_dir / "dataset_info.json"
    dataset_info_path.write_text(
        json.dumps(dataset_info, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": (
            "studyhub.deepresearch.web_router_sft_manifest.v2"
            if include_multi_turn
            else "studyhub.deepresearch.web_router_sft_manifest.v1"
        ),
        "source_suites": [
            "studyhub.deepresearch.web_router_eval.v1",
            *(
                ["studyhub.deepresearch.search_r1_multiturn_pilot.v1"]
                if include_multi_turn
                else []
            ),
        ],
        "multi_turn_transition_examples": include_multi_turn,
        "counts": {split: len(rows) for split, rows in by_split.items()},
        "family_counts": {
            split: dict(sorted(counts.items()))
            for split, counts in family_counts.items()
        },
        "files": files,
        "dataset_info_sha256": _sha256_file(dataset_info_path),
        "assistant_only_loss": True,
        "template": "qwen3_5_nothink",
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "live_web_called": False,
            "paid_material_used": False,
        },
    }
    manifest_path = dataset_dir / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


async def _build_multi_turn_rows(
    policy: DeterministicWebRouterPolicy,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in build_web_rl_pilot_scenarios():
        rows.extend(await _scenario_transition_rows(scenario, policy))
    return rows


async def _scenario_transition_rows(
    scenario: WebRLPilotScenario,
    policy: DeterministicWebRouterPolicy,
) -> list[dict[str, Any]]:
    environment = FrozenWebResearchEnvironment()
    state = await environment.reset(scenario, seed=7703)
    rows: list[dict[str, Any]] = []
    for turn_index, _transition in enumerate(scenario.transitions):
        decision = await policy.decide(state)
        rows.append(
            {
                "messages": [
                    *build_research_decision_messages(state),
                    {
                        "role": "assistant",
                        "content": canonical_json(decision),
                    },
                ],
                "case_id": f"{scenario.scenario_id}:turn:{turn_index}",
                "task_family": f"trajectory_{scenario.family}",
                "state_hash": canonical_hash(state),
                "split": scenario.split,
            }
        )
        result = await environment.step(decision)
        if not result.action_correct:
            raise AssertionError(
                f"teacher policy failed frozen transition: {scenario.scenario_id}/{turn_index}"
            )
        state = result.state
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--include-multi-turn", action="store_true")
    args = parser.parse_args()
    manifest = export_web_router_sft(
        args.dataset_dir.resolve(),
        include_multi_turn=args.include_multi_turn,
    )
    print(canonical_json(manifest))


if __name__ == "__main__":
    main()


__all__ = ["DATASET_NAMES", "export_web_router_sft"]
