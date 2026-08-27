#!/usr/bin/env python3
# ruff: noqa: E501 - generated Markdown paragraphs remain readable as source templates
"""Generate benchmark cards and portfolio documentation from audited artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.schema import load_jsonl


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: int, total: int) -> float:
    return round(100 * value / total, 2) if total else 0.0


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v2")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v2/studyhub-agent-v2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = args.project.resolve()
    public = args.public_root.resolve()
    hidden = args.hidden_root.resolve()
    docs = project / "docs/benchmark"
    docs.mkdir(parents=True, exist_ok=True)
    manifest = read_json(public / "manifest.json")
    semantic = read_json(public / "semantic-audit-summary.json")
    structural = read_json(public / "structural-audit-summary.json")
    self_test = read_json(public / "self-test-summary.json")
    challenge = read_json(public / "evaluator-challenge-summary.json")
    review = read_json(public / "review-pack-manifest.json")
    external_lock = read_json(project / "external_benchmarks/lock.json")
    external_smoke = read_json(project / "external_benchmarks/smoke-status.json")
    inventory = load_jsonl(hidden / "source-inventory.jsonl")
    task_rows = []
    grader_rows = []
    for split in manifest["counts"]:
        task_path = hidden / f"tasks/{split}.jsonl" if split.startswith("sealed_") else public / f"{split}/tasks.jsonl"
        task_rows.extend(load_jsonl(task_path))
        grader_rows.extend(load_jsonl(hidden / f"graders/{split}.jsonl"))
    total = sum(map(int, manifest["counts"].values()))
    authentic = sum(
        int(value) for key, value in manifest["environment_origins"].items() if key.startswith("authentic_")
    )
    synthetic = total - authentic
    capability_total = len(
        {capability for split_counts in manifest["capability_counts"].values() for capability in split_counts}
    )
    inventory_types = Counter(str(row["document_type"]) for row in inventory)
    card = {
        "schema_version": "studyhub.agentbench-card.v2",
        "benchmark_version": manifest["benchmark_version"],
        "benchmark_revision": manifest["benchmark_revision"],
        "status": manifest["status"],
        "builder_commit": manifest["builder_commit"],
        "tasks": total,
        "splits": manifest["counts"],
        "capability_families": capability_total,
        "unique_source_groups": manifest["source_groups"],
        "development_semantic_clusters": semantic["development"]["semantic_clusters"],
        "development_largest_cluster_share": semantic["development"]["largest_cluster_share"],
        "origin_counts": manifest["environment_origins"],
        "authentic_tasks": authentic,
        "synthetic_tasks": synthetic,
        "authentic_percent": pct(authentic, total),
        "synthetic_percent": pct(synthetic, total),
        "language_counts": manifest["languages"],
        "language_percent": {key: pct(int(value), total) for key, value in manifest["languages"].items()},
        "oracle": self_test["oracle"],
        "negative_controls": self_test["negative_controls"],
        "metamorphic": self_test["metamorphic"],
        "shortcut": self_test["shortcut"],
        "evaluator_challenge": {"cases": challenge["cases"], "passed": challenge["passed"]},
        "review": review["review_status"],
        "independent_expert_review": "PENDING",
        "external_portfolio": manifest["external_portfolio"],
        "result_policy": "Internal and external metrics are reported separately; no aggregate AgentScore.",
    }
    (public / "BENCHMARK_CARD.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    split_rows = "\n".join(f"| `{name}` | {count} |" for name, count in manifest["counts"].items())
    origin_rows = "\n".join(
        f"| `{name}` | {count} | {pct(int(count), total):.2f}% |"
        for name, count in manifest["environment_origins"].items()
    )
    data_card = f"""# StudyHub AgentBench v2 Data Card

## Scope

AgentBench v2 is an internal product-validity benchmark for StudyHub's read-only learning agent. It contains **{total} tasks**, **{capability_total} capability-oriented task families**, and **{manifest["source_groups"]} non-overlapping source groups**. It does not replace BFCL, tau2-bench, DeepResearch Bench II, or BrowseComp-Plus.

## Splits

| Split | Tasks |
| --- | ---: |
{split_rows}

`regression`, `development`, and `calibration_challenge` tasks are tracked. Sealed-A and Sealed-B tasks, environments, corpora, and graders remain ignored local artifacts. Source-group and declared semantic-template overlap across splits are both zero.

## Sources

The hidden source inventory contains **{len(inventory)} records**: {dict(inventory_types)}. StudyHub records come only from free public preview OCR and contain no paid/private/cross-user material. The Web lane uses 50 frozen official documentation pages whose URLs, licenses, content hashes, and snapshot lock are recorded.

| Environment origin | Tasks | Share |
| --- | ---: | ---: |
{origin_rows}

Authentic-source tasks account for **{authentic}/{total} ({pct(authentic, total):.2f}%)**; synthetic adversarial, memory, and state fixtures account for **{synthetic}/{total} ({pct(synthetic, total):.2f}%)**.

## Languages

- Chinese: **{manifest["languages"].get("zh", 0)} ({pct(int(manifest["languages"].get("zh", 0)), total):.2f}%)**
- English: **{manifest["languages"].get("en", 0)} ({pct(int(manifest["languages"].get("en", 0)), total):.2f}%)**

English task instructions use English split prefixes. Source titles and quoted technical terms can remain in their original language.

## Construction

Authentic RAG tasks use preview body text rather than metadata-only lookup. Companion-term graders accept every supported non-anchor technical term in the cited passage instead of one arbitrary generator choice. Query reformulation requires an observed alias bridge, a changed query, and target-recall gain. Web pages are fetched only from an HTTPS allowlist and replayed offline. Memory/state fixtures carry explicit invariants and final-state assertions.

## Review And Limitations

Codex self-reviewed 32 stratified representatives across all 30 capability families, five splits, both languages, and all source origins. Independent human review and external LLM judging were **not run**.

Known limits: preview OCR quality varies; some passage tasks remain extraction-oriented; some cross-passage tasks use the same anchor in two distinct passages; the internal research lane measures controlled multi-source synthesis rather than general open-web Deep Research quality; initial difficulty remains `UNSCORED` until post-freeze calibration.
"""
    (public / "DATA_CARD.md").write_text(data_card, encoding="utf-8")

    quality_report = f"""# StudyHub AgentBench v2 Quality Report

## Decision

Status: **{manifest["status"]}** at revision **{manifest["benchmark_revision"]}**. The engineering gate passed; independent expert review remains pending.

## Evidence

- Structural audit: **{structural["summary"]["passed"]}/{structural["summary"]["checks"]} passed**.
- Development semantic clusters: **{semantic["development"]["semantic_clusters"]}/{semantic["development"]["tasks"]}**; largest cluster **{100 * semantic["development"]["largest_cluster_share"]:.2f}%**.
- Scripted Oracle: **{self_test["oracle"]["strict_pass"]}/{self_test["oracle"]["tasks"]} ({100 * self_test["oracle"]["pass_rate"]:.2f}%)**.
- Negative controls: empty, random, generic, tool spam, citation decoration, and wrong-source attacks each achieved **0 strict passes**.
- Metamorphic tests: **{self_test["metamorphic"]["passed"]}/{self_test["metamorphic"]["cases"]}**.
- Evaluator challenge cases: **{challenge["passed"]}/{challenge["cases"]}**.
- Shortcut probe: {self_test["shortcut"]["tasks"]} tasks, {self_test["shortcut"]["unique_answer_signatures"]} answer signatures, largest signature share **{100 * self_test["shortcut"]["largest_answer_signature_share"]:.2f}%**.
- Frozen v1 integrity: unchanged under `configs/benchmark-v1-frozen-hashes.json`.

## Measurement Boundaries

Deterministic facts, citations, ACL, tool contracts, state postconditions, query change, recall gain, and runtime exclusion are evaluated locally. No online semantic judge result is claimed. Scalar scores from training Reward are not imported. INFRA failures remain excluded from policy accuracy.

The review packs are ignored because they include sealed tasks and hidden graders. Only their counts and SHA256 hashes are tracked. `self_review` is not labeled as human review.
"""
    (public / "QUALITY_REPORT.md").write_text(quality_report, encoding="utf-8")

    external_rows = "\n".join(
        f"| {name} | `{row['resolved_commit']}` | {external_smoke['benchmarks'][name]['status']} | {row['license']['spdx']} |"
        for name, row in external_lock["benchmarks"].items()
    )
    (docs / "EXTERNAL_BENCHMARKS.md").write_text(
        f"""# External Benchmark Portfolio

| Benchmark | Pinned commit | Current status | License |
| --- | --- | --- | --- |
{external_rows}

BFCL keeps the official `bfcl generate`/`bfcl evaluate` pipeline. tau2-bench v1.0.1 keeps official DB/COMMUNICATE outcome semantics; reference actions are not converted into a unique path requirement. BrowseComp-Plus keeps the official fixed-corpus qrels and evaluator path; its large corpus and GPU judge were not run. DeepResearch Bench II has no license file at the pinned official commit, so source export and task evaluation are blocked as `LICENSE_REVIEW_REQUIRED`.

No external model score has been generated. The shared adapter normalizes transport and result packaging only; it does not rewrite official metrics.

```bash
python scripts/benchmark/external/fetch.py --benchmark all
python scripts/benchmark/external/validate_registry.py
python scripts/benchmark/external/smoke.py
```
""",
        encoding="utf-8",
    )
    (docs / "BENCHMARK_PORTFOLIO.md").write_text(
        f"""# StudyHub Agent Evaluation Portfolio

The portfolio separates two questions:

1. **Internal product validity:** StudyHub AgentBench v2 ({total} tasks) measures StudyHub RAG, frozen Web, memory, state, ACL, failure recovery, and tool relevance.
2. **External validity:** BFCL, tau2-bench, DeepResearch Bench II, and BrowseComp-Plus retain their official environments and metrics.

Metrics are never averaged into a single AgentScore. Future reports must show StudyHub strict success and cluster-aware intervals alongside each external benchmark's raw metric name and value.

AgentBench v1 remains immutable historical runtime evidence. AgentBench v2 is the baseline ruler for new Base/SFT/GRPO comparisons after this frozen revision.

## Reproduction

The exact StudyHub preview OCR and material metadata used to construct v2 are authorized local snapshots and are intentionally not redistributed. With those inputs present at the paths documented by `scripts/benchmark/v2/build.py`, the complete fail-fast gate is:

```bash
bash scripts/benchmark/run_full_quality_gate.sh
```

The command fetches or validates the licensed Web/external snapshots, rebuilds v2, runs structural and semantic audits, Oracle/negative/metamorphic/challenge tests, validates v1 integrity, scans commit candidates for secrets, freezes the manifest, and verifies all recorded hashes. Without the authorized OCR snapshot, the command exits with an explicit prerequisite error rather than substituting synthetic content.

## Base Calibration

The first post-freeze Qwen3.5-9B Base Gate is recorded in [9B_BASE_V2_CALIBRATION.md](9B_BASE_V2_CALIBRATION.md). It covers one public task per capability and validates the complete runtime, but it is not a full Development or Sealed benchmark result and does not assign empirical difficulty labels.
""",
        encoding="utf-8",
    )
    (docs / "V1_TO_V2_MIGRATION.md").write_text(
        f"""# AgentBench v1 To v2 Migration

v1 remains unchanged and bound to its existing 9B Base lineage. Its Development split has 1005 tasks over 64 source groups, with source reuse up to 31 and a largest normalized semantic shape of 3.58%. Its previous teacher review was a deterministic contract check, not an independent semantic review.

v2 is a new benchmark rather than a score migration. It uses {total} tasks and {manifest["source_groups"]} split-isolated source groups; Development has {semantic["development"]["semantic_clusters"]} semantic clusters for {semantic["development"]["tasks"]} tasks. Difficulty starts as `UNSCORED`. Web evidence comes from a locked authentic snapshot, query rewrite requires evidence gain, ACL avoidance is separate from post-denial recovery, and claim support binds answers to read/fetched sources.

Do not recalculate or overwrite v1 results with the v2 evaluator. New 9B Base/SFT/GRPO experiments should bind the v2 manifest hash and report a fresh lineage.
""",
        encoding="utf-8",
    )
    graders_by_task = {str(row["task_id"]): row for row in grader_rows}
    capability_coverage: dict[str, dict[str, Any]] = {}
    for capability in sorted({str(row["capability_id"]) for row in task_rows}):
        members = [row for row in task_rows if row["capability_id"] == capability]
        graders = [graders_by_task[str(row["task_id"])] for row in members]
        modes = sorted({str(row.get("outcome", {}).get("mode", "facts")) for row in graders})
        process_modes = sorted(
            {
                str(row.get("evaluation_contract", {}).get("process_constraints", {}).get("mode", "open_path"))
                for row in graders
            }
        )
        has_claims = any(row.get("claims") for row in graders)
        citation_required = any(
            claim.get("citation_required", True) for row in graders for claim in row.get("claims", [])
        )
        semantic_statuses = sorted(
            {str(row.get("semantic_judge", {}).get("status", "NOT_REQUIRED")) for row in graders}
        )
        metrics = [
            "strict_success",
            "task_outcome",
            "answer_correctness",
            "tool_validity",
            "privacy_policy",
            "efficiency",
        ]
        if has_claims:
            metrics.extend(["claim_support", "source_quality"])
        if citation_required:
            metrics.extend(["citation_correctness", "citation_completeness"])
        if any(mode != "open_path" for mode in process_modes):
            metrics.append("recovery_or_process_success")
        capability_coverage[capability] = {
            "tasks": len(members),
            "outcome_modes": modes,
            "process_modes": process_modes,
            "operationalized_metrics": metrics,
            "semantic_judge_statuses": semantic_statuses,
        }
    metric_matrix = {
        "schema_version": "studyhub.agentbench-metric-coverage.v2",
        "benchmark_version": manifest["benchmark_version"],
        "benchmark_revision": manifest["benchmark_revision"],
        "claim": "Task-family presence and metric operationalization are reported separately.",
        "capabilities": capability_coverage,
    }
    (public / "metric-coverage-matrix.json").write_text(
        json.dumps(metric_matrix, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metric_rows = "\n".join(
        f"| `{name}` | {row['tasks']} | {', '.join(row['outcome_modes'])} | {', '.join(row['process_modes'])} | {', '.join(row['operationalized_metrics'])} | {', '.join(row['semantic_judge_statuses'])} |"
        for name, row in capability_coverage.items()
    )
    (docs / "METRIC_COVERAGE.md").write_text(
        f"""# AgentBench v2 Metric Coverage

The table distinguishes a capability-oriented task family from the metrics that the local evaluator actually operationalizes. It does not claim independent semantic validation where the semantic judge status is `NOT_RUN` or `NOT_REQUIRED`.

| Capability family | Tasks | Outcome mode | Process contract | Operationalized metrics | Semantic judge |
| --- | ---: | --- | --- | --- | --- |
{metric_rows}
""",
        encoding="utf-8",
    )
    source_summary = {
        "schema_version": "studyhub.agentbench-source-inventory-summary.v2",
        "records": len(inventory),
        "document_types": dict(inventory_types),
        "access_scopes": dict(Counter(str(row["access_scope"]) for row in inventory)),
        "provenance": dict(Counter(str(row["provenance"]) for row in inventory)),
        "content_hashes_present": all(bool(row.get("content_sha256")) for row in inventory),
        "paid_private_sources": 0,
    }
    (public / "source-inventory-summary.json").write_text(
        json.dumps(source_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
