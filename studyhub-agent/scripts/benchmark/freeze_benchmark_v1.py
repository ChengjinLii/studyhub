#!/usr/bin/env python3
# ruff: noqa: E501 - embedded HTML is kept readable as a single template
"""Freeze an audited Benchmark v1 snapshot for the 9B Base evaluation."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.schema import BENCHMARK_VERSION


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def head_commit(project: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def render_card(card: dict[str, Any]) -> str:
    counts = card["task_counts"]
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in card["known_limits"])
    changes = "".join(f"<li>{html.escape(item)}</li>" for item in card["change_log"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyHub Agent Benchmark v1 Card</title>
<style>
:root{{--ink:#17211d;--muted:#65726b;--paper:#f4f2e9;--green:#2e6a57;--gold:#d3a73c;--line:#cbd2ca}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Sans SC","Source Han Sans SC",sans-serif}}
main{{max-width:1080px;margin:auto;padding:64px 36px 80px}} h1{{font:700 clamp(36px,6vw,70px)/1.03 Georgia,serif;margin:0 0 18px}}
.eyebrow{{color:var(--green);font-weight:800;letter-spacing:.14em;text-transform:uppercase}} .status{{display:inline-block;padding:8px 13px;border:1px solid var(--green);border-radius:999px;color:var(--green);font-weight:800}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:38px 0}} .metric,.panel{{border-top:3px solid var(--gold);background:#fff9;padding:22px}}
.metric b{{display:block;font:700 42px/1 Georgia,serif;margin-bottom:8px}} .metric span,p,li{{color:var(--muted);line-height:1.65}}
.panels{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} h2{{font-size:20px;margin:0 0 12px}} code{{font-family:"IBM Plex Mono",monospace;color:var(--green);word-break:break-all}}
@media(max-width:720px){{main{{padding:38px 20px}}.grid,.panels{{grid-template-columns:1fr}}}}
</style>
</head>
<body><main>
<div class="eyebrow">Benchmark Card / {html.escape(card['version'])}</div>
<h1>先固定尺子，<br>再训练模型。</h1>
<p><span class="status">{html.escape(card['status'])}</span></p>
<p>{html.escape(card['purpose'])}</p>
<section class="grid">
<div class="metric"><b>{counts['regression']}</b><span>Regression</span></div>
<div class="metric"><b>{counts['development']}</b><span>Development</span></div>
<div class="metric"><b>{counts['sealed']}</b><span>Sealed Final</span></div>
</section>
<section class="panels">
<article class="panel"><h2>质量门禁</h2><p>结构审计 <strong>{card['quality']['structural_checks']}</strong>；教师主审 <strong>{card['quality']['teacher_primary']}</strong> 条；对抗复核 <strong>{card['quality']['teacher_adversarial']}</strong> 条；阻塞缺陷为 0。</p></article>
<article class="panel"><h2>隔离</h2><p>Training Reward、Development evaluator、Sealed evaluator 独立实现。Sealed tasks、环境、grader 和资料语料只保存在 Git ignored artifact。</p></article>
<article class="panel"><h2>已知限制</h2><ul>{limits}</ul></article>
<article class="panel"><h2>变更记录</h2><ul>{changes}</ul></article>
</section>
<p>内容指纹：<code>{html.escape(card['content_sha256'])}</code></p>
<p>基线状态：{html.escape(card['baseline_models']['qwen3_5_9b'])}。当前卡片不包含任何模型能力提升结论。</p>
</main></body></html>"""


def freeze(args: argparse.Namespace) -> dict[str, Any]:
    public_root = args.public_root.resolve()
    hidden_root = args.hidden_root.resolve()
    manifest_path = public_root / "manifest.json"
    manifest = load(manifest_path)
    structural = load(public_root / "structural-audit-summary.json")
    quality = load(public_root / "quality-review-summary.json")
    hidden_review = hidden_root / "quality/teacher-reviews.jsonl"
    if manifest.get("benchmark_version") != BENCHMARK_VERSION:
        raise RuntimeError("benchmark version mismatch")
    if structural.get("status") != "PASS" or structural.get("summary", {}).get("failed") != 0:
        raise RuntimeError("structural audit has not passed")
    if quality.get("status") != "PASS" or quality.get("blocking_failures") != 0:
        raise RuntimeError("teacher quality review has not passed")
    if not hidden_review.is_file() or sha256(hidden_review) != quality.get("hidden_review_sha256"):
        raise RuntimeError("teacher review evidence is missing or stale")

    core_hashes = {
        **{f"public:{name}": value for name, value in manifest["public_files"].items()},
        **{f"hidden:{name}": value for name, value in manifest["hidden_files"].items()},
        "structural_audit": structural["audit_sha256"],
        "teacher_review": quality["hidden_review_sha256"],
    }
    content_sha = hashlib.sha256(json.dumps(core_hashes, sort_keys=True).encode()).hexdigest()
    frozen_at = datetime.now(UTC).isoformat(timespec="seconds")
    card = {
        "schema_version": "studyhub.agentbench-card.v1",
        "version": BENCHMARK_VERSION,
        "status": "FROZEN_FOR_BASELINE",
        "frozen_at": frozen_at,
        "build_base_commit": head_commit(args.project.resolve()),
        "license": {
            "code_and_public_task_metadata": "MIT",
            "hidden_source_material": "local evaluation only; governed by StudyHub source terms",
        },
        "purpose": "Internal product-aligned benchmark for autonomous StudyHub Agent behavior under replayable tools.",
        "task_counts": manifest["counts"],
        "capability_count": len(manifest["capability_counts"]["development"]),
        "environment": "replayable StudyHub RAG, Web, Memory, ACL, failure, and state-transition sandbox",
        "grader": {
            "development": "independent claim/state/process evaluator",
            "sealed": "separate sealed evaluator implementation",
            "training_reward": "not used by this benchmark",
        },
        "quality": {
            "structural_checks": f"{structural['summary']['passed']}/{structural['summary']['checks']} PASS",
            "teacher_primary": quality["sample"]["primary"],
            "teacher_adversarial": quality["sample"]["double_reviewed"],
            "teacher_verdicts": quality["sample"]["primary_verdicts"],
            "external_judge": quality["external_judge"]["status"],
            "material_partition_overlap": 0,
            "public_oracle_fields": 0,
        },
        "baseline_models": {"qwen3_5_9b": "PENDING"},
        "variance_mde": "PENDING_BASELINE_ROLLOUTS",
        "cost": "PENDING_BASELINE_PROFILE",
        "known_limits": quality["known_limits"],
        "change_log": [
            "v1 candidate: 20-capability, three-split benchmark generated",
            "semantic QA: fixed random material/course and weak-topic mismatches",
            "grader hardening: observable tool-family and recovery contracts added",
            "v1 frozen for the 9B Base baseline; no post-freeze task edits are allowed",
        ],
        "claim_boundary": "Supports internal comparative evaluation only; no external leaderboard or production claim.",
        "content_sha256": content_sha,
    }
    card_json = public_root / "BENCHMARK_CARD.json"
    card_html = public_root / "BENCHMARK_CARD.html"
    card_json.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    card_html.write_text(render_card(card), encoding="utf-8")

    manifest["status"] = "FROZEN_FOR_BASELINE"
    manifest["frozen_at"] = frozen_at
    manifest["content_sha256"] = content_sha
    manifest["quality_gate"] = {
        "structural_audit": structural["status"],
        "teacher_review": quality["status"],
        "external_judge": quality["external_judge"]["status"],
    }
    manifest["public_files"].update(
        {
            "BENCHMARK_CARD.json": sha256(card_json),
            "BENCHMARK_CARD.html": sha256(card_html),
            "quality-review-summary.json": sha256(public_root / "quality-review-summary.json"),
        }
    )
    manifest["hidden_files"].update(
        {
            "quality/teacher-reviews.jsonl": sha256(hidden_review),
            "quality/teacher-review-summary.json": sha256(hidden_root / "quality/teacher-review-summary.json"),
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hidden_manifest = {
        **manifest,
        "public_manifest_sha256": sha256(manifest_path),
        "hidden_root": str(hidden_root),
    }
    (hidden_root / "manifest.json").write_text(
        json.dumps(hidden_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return card


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v1")
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1",
    )
    return parser.parse_args()


def main() -> int:
    card = freeze(parse_args())
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
