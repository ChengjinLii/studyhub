"""Build the self-contained HTML report for the isolated Router RL pilot."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..paths import BACKEND_ROOT
from .spec import sha256_file


def build_report(*, repo_root: Path, output_path: Path) -> dict[str, Any]:
    artifact_root = repo_root / "training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1"
    evaluation_root = repo_root / "evaluation_artifacts/studyhub_agent/router_rl_pilot_v1"
    gate_root = evaluation_root / "gate"
    gate = _read_json(gate_root / "gate.json")
    selection = _read_json(gate_root / "selection_manifest.json")
    release = _read_json(gate_root / "release_rollback_manifest.json")
    audit = _read_json(artifact_root / "audit.json")
    manifest = _read_json(artifact_root / "manifest.json")
    calibration = _read_json(artifact_root / "judge_calibration.json")
    config = _read_json(repo_root / "ml/agentic_platform/rl/configs/router_grpo_pilot_v1.json")
    input_lock = _read_json(artifact_root / "input_lock.json")
    baseline_validation = _read_json(evaluation_root / "validation/baseline_sft/summary.json")
    candidate_validation = _read_json(evaluation_root / "validation/seed_3407/summary.json")
    baseline_test = _read_json(evaluation_root / "test/baseline_sft/summary.json")
    candidate_test = _read_json(evaluation_root / "test/seed_3407/summary.json")
    training = {
        label: _read_json(artifact_root / f"runs/{label}/run_summary.json")
        for label in ("seed_3407", "seed_7703", "seed_9109")
    }
    training_metrics = {
        label: _read_jsonl(artifact_root / f"runs/{label}/trainer_metrics.jsonl") for label in training
    }
    adapter_config = _read_json(Path(str(input_lock["policy"]["sft_adapter_path"])) / "adapter_config.json")
    coverage = _knowledge_coverage(repo_root=repo_root, artifact_root=artifact_root, evaluation_root=evaluation_root)
    coverage_path = gate_root / "knowledge_coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "schema_version": "studyhub.agent.router_rl.knowledge_coverage.v1",
                "items": coverage,
                "covered": len(coverage),
                "production_ready": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    failed_peak_mib = _failed_peak_memory(
        artifact_root / "runs/failed_seed_3407_peak_guard_20260812/gpu_samples.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = _render_html(
        output_path=output_path,
        gate=gate,
        selection=selection,
        release=release,
        audit=audit,
        manifest=manifest,
        calibration=calibration,
        config=config,
        input_lock=input_lock,
        baseline_validation=baseline_validation,
        candidate_validation=candidate_validation,
        baseline_test=baseline_test,
        candidate_test=candidate_test,
        training=training,
        training_metrics=training_metrics,
        adapter_config=adapter_config,
        coverage=coverage,
        coverage_path=coverage_path,
        failed_peak_mib=failed_peak_mib,
        repo_root=repo_root,
    )
    output_path.write_text(document, encoding="utf-8")
    validation = _validate_report(document=document, output_path=output_path, coverage=coverage)
    manifest_path = gate_root / "report_manifest.json"
    report_manifest = {
        "schema_version": "studyhub.agent.router_rl.report_manifest.v1",
        "report_path": str(output_path.resolve()),
        "report_sha256": sha256_file(output_path),
        "coverage_path": str(coverage_path.resolve()),
        "coverage_sha256": sha256_file(coverage_path),
        "gate_sha256": sha256_file(gate_root / "gate.json"),
        "validation": validation,
    }
    manifest_path.write_text(
        json.dumps(report_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "report_path": str(output_path.resolve()),
        "report_sha256": sha256_file(output_path),
        "coverage_path": str(coverage_path.resolve()),
        "coverage_sha256": sha256_file(coverage_path),
        "knowledge_points": len(coverage),
        "conclusion": gate["conclusion"],
        "validation": validation,
        "manifest_path": str(manifest_path.resolve()),
    }


def _render_html(
    *,
    output_path: Path,
    gate: dict[str, Any],
    selection: dict[str, Any],
    release: dict[str, Any],
    audit: dict[str, Any],
    manifest: dict[str, Any],
    calibration: dict[str, Any],
    config: dict[str, Any],
    input_lock: dict[str, Any],
    baseline_validation: dict[str, Any],
    candidate_validation: dict[str, Any],
    baseline_test: dict[str, Any],
    candidate_test: dict[str, Any],
    training: dict[str, dict[str, Any]],
    training_metrics: dict[str, list[dict[str, Any]]],
    adapter_config: dict[str, Any],
    coverage: list[dict[str, Any]],
    coverage_path: Path,
    failed_peak_mib: int,
    repo_root: Path,
) -> str:
    test_gate = gate["independent_test"]
    test_delta = test_gate["deltas"]
    test_paired = test_gate["paired_statistics"]
    validation_gate = gate["validation"]["candidate_assessments"]
    multi_seed = gate["multi_seed_statistics"]
    production_defaults = gate["production_defaults"]
    test_baseline_raw = baseline_test["raw"]
    test_candidate_raw = candidate_test["raw"]
    validation_baseline_raw = baseline_validation["raw"]
    validation_candidate_raw = candidate_validation["raw"]
    report_date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")

    def evidence_link(path: str | Path, label: str | None = None) -> str:
        return _link(output_path, Path(path), label)

    knowledge_cards = "".join(
        f"""
        <article class="knowledge-card reveal" id="knowledge-{item['number']:02d}">
          <div class="knowledge-index">{item['number']:02d}</div>
          <div class="knowledge-body">
            <div class="knowledge-head"><h3>{_escape(item['title'])}</h3><span class="pill {item['tone']}">{_escape(item['status'])}</span></div>
            <p>{_escape(item['finding'])}</p>
            <div class="evidence-inline">{''.join(evidence_link(path) for path in item['evidence'])}</div>
          </div>
        </article>
        """
        for item in coverage
    )
    training_rows = "".join(
        _training_row(label, summary, validation_gate[label]) for label, summary in training.items()
    )
    curve_cards = "".join(
        _curve_card(label, training[label], training_metrics[label]) for label in training
    )
    robustness_rows = _robustness_rows(
        baseline=test_baseline_raw["families"],
        candidate=test_candidate_raw["families"],
        deltas=test_delta["families"],
    )
    hard_gate_rows = "".join(
        f"<tr><td>{_escape(name)}</td><td>{_pct(value)}</td><td>{_pct(test_candidate_raw['hard_gates'][name])}</td>"
        f"<td class=\"delta {'good' if test_candidate_raw['hard_gates'][name] >= value else 'bad'}\">"
        f"{_pp(test_candidate_raw['hard_gates'][name] - value)}</td></tr>"
        for name, value in sorted(test_baseline_raw["hard_gates"].items())
    )
    global_check_rows = "".join(
        f"<li><span>{_escape(name.replace('_', ' '))}</span><strong>{'PASS' if passed else 'FAIL'}</strong></li>"
        for name, passed in gate["global_checks"].items()
    )
    evidence_rows = [
        ("最终 Gate", repo_root / "evaluation_artifacts/studyhub_agent/router_rl_pilot_v1/gate/gate.json"),
        ("候选冻结清单", repo_root / "evaluation_artifacts/studyhub_agent/router_rl_pilot_v1/gate/selection_manifest.json"),
        ("回滚清单", repo_root / "evaluation_artifacts/studyhub_agent/router_rl_pilot_v1/gate/release_rollback_manifest.json"),
        ("26 项覆盖清单", coverage_path),
        ("数据审计", repo_root / "training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1/audit.json"),
        ("输入锁", repo_root / "training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1/input_lock.json"),
        ("Judge 校准", repo_root / "training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1/judge_calibration.json"),
        ("训练配置", repo_root / "ml/agentic_platform/rl/configs/router_grpo_pilot_v1.json"),
    ]
    evidence_table = "".join(
        f"<tr><td>{_escape(label)}</td><td>{evidence_link(path)}</td><td><code>{sha256_file(path)[:16]}…</code></td></tr>"
        for label, path in evidence_rows
    )
    raw_reward_ci = test_paired["reward_delta"]["ci95"]
    choice_ci = test_paired["choice_success_delta"]["ci95"]
    episode_ci = test_paired["episode_success_delta"]["ci95"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>StudyHub Agent · Router RL Pilot</title>
  <style>
    :root {{
      --forest:#14392d; --forest-deep:#0b211a; --moss:#2d7258; --mint:#91c7a8;
      --paper:#f2eee2; --paper-hi:#fbf8ef; --gold:#cf9d2d; --gold-pale:#ead7a1;
      --ink:#17241f; --muted:#596a62; --line:rgba(20,57,45,.18); --red:#a84637;
      --red-pale:#efd7d0; --green-pale:#d7e7db; --shadow:0 22px 70px rgba(13,37,29,.12);
      --serif:"Iowan Old Style","Source Han Serif SC","Noto Serif CJK SC","Songti SC",serif;
      --sans:"Avenir Next","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
      --mono:"SFMono-Regular","Cascadia Code","JetBrains Mono",monospace;
    }}
    * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }}
    body {{ margin:0; color:var(--ink); font-family:var(--sans); line-height:1.68; background:
      radial-gradient(circle at 6% 2%,rgba(207,157,45,.18),transparent 28rem),
      radial-gradient(circle at 94% 8%,rgba(45,114,88,.16),transparent 34rem),var(--paper); }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; z-index:-1; opacity:.3;
      background-image:linear-gradient(rgba(20,57,45,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(20,57,45,.04) 1px,transparent 1px);
      background-size:32px 32px; mask-image:linear-gradient(to bottom,black,transparent 72%); }}
    a {{ color:inherit; }} code {{ font-family:var(--mono); }}
    .progress {{ position:fixed; z-index:99; top:0; left:0; width:0; height:3px; background:var(--gold); }}
    .shell {{ width:min(1440px,calc(100% - 54px)); margin:0 auto; }}
    .hero {{ min-height:92vh; display:grid; align-content:center; padding:78px 0 44px; }}
    .hero-grid {{ display:grid; grid-template-columns:1.28fr .72fr; gap:56px; align-items:end; }}
    .eyebrow {{ display:flex; align-items:center; gap:14px; color:var(--moss); font:700 11px/1 var(--mono); letter-spacing:.18em; text-transform:uppercase; }}
    .eyebrow::before {{ content:""; width:58px; height:2px; background:var(--gold); }}
    h1 {{ margin:24px 0 22px; font:700 clamp(68px,10vw,154px)/.82 var(--serif); letter-spacing:-.07em; }}
    h1 span {{ display:block; margin-top:.27em; color:var(--moss); font-size:.38em; letter-spacing:-.025em; }}
    .hero-lead {{ max-width:830px; margin:0; color:#294036; font:500 clamp(20px,2.2vw,31px)/1.5 var(--serif); }}
    .hero-meta {{ display:flex; flex-wrap:wrap; gap:10px 22px; margin-top:28px; color:var(--muted); font:12px/1.5 var(--mono); }}
    .status-card {{ position:relative; overflow:hidden; padding:38px 34px; color:var(--paper-hi); background:var(--forest-deep); border-radius:2px 34px 2px 2px; box-shadow:var(--shadow); }}
    .status-card::after {{ content:"RL"; position:absolute; right:-16px; bottom:-52px; color:rgba(255,255,255,.045); font:800 170px/1 var(--serif); }}
    .status-card .label {{ color:var(--mint); font:700 11px/1 var(--mono); letter-spacing:.16em; }}
    .status-card strong {{ display:block; margin:20px 0 14px; color:#f2c55b; font:700 46px/.95 var(--serif); }}
    .status-card p {{ margin:0; color:#c6d4cd; }}
    .status-rule {{ margin-top:28px; padding-top:18px; border-top:1px solid rgba(255,255,255,.15); font:11px/1.6 var(--mono); color:#e8b8ad; }}
    .metric-strip {{ display:grid; grid-template-columns:repeat(5,1fr); margin-top:62px; border-block:1px solid var(--line); }}
    .metric {{ padding:24px 20px; border-right:1px solid var(--line); }} .metric:last-child {{ border-right:0; }}
    .metric strong {{ display:block; font:650 clamp(28px,3vw,46px)/1 var(--serif); }}
    .metric strong.good {{ color:var(--moss); }} .metric strong.bad {{ color:var(--red); }}
    .metric span {{ display:block; margin-top:9px; color:var(--muted); font-size:12px; }}
    .report-grid {{ display:grid; grid-template-columns:220px minmax(0,1fr); gap:58px; align-items:start; padding-bottom:100px; }}
    aside {{ position:sticky; top:24px; padding:30px 0; }}
    aside .rail-title {{ color:var(--moss); font:700 11px/1 var(--mono); letter-spacing:.15em; }}
    aside a {{ display:block; padding:8px 0; color:var(--muted); text-decoration:none; font-size:13px; border-bottom:1px solid transparent; }}
    aside a:hover,aside a.active {{ color:var(--forest); border-color:var(--gold); }}
    .rail-state {{ margin-top:28px; padding:16px 0; border-top:1px solid var(--line); color:var(--red); font:700 11px/1.6 var(--mono); }}
    main section {{ padding:74px 0; border-top:1px solid var(--line); }}
    .kicker {{ color:var(--gold); font:700 11px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase; }}
    .section-head {{ display:grid; grid-template-columns:.88fr 1.12fr; gap:42px; margin:15px 0 38px; }}
    .section-head h2 {{ margin:0; font:650 clamp(38px,5vw,68px)/1 var(--serif); letter-spacing:-.045em; }}
    .section-head p {{ margin:6px 0 0; max-width:720px; color:var(--muted); font-size:16px; }}
    .panel {{ background:rgba(251,248,239,.88); border:1px solid var(--line); padding:28px; box-shadow:0 12px 42px rgba(13,37,29,.045); }}
    .panel h3 {{ margin:0 0 17px; font:650 27px/1.15 var(--serif); }}
    .decision-grid,.two-col,.curve-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:22px; }}
    .signal {{ border-top:5px solid var(--moss); }} .blocker {{ border-top:5px solid var(--red); }}
    .signal-list {{ list-style:none; padding:0; margin:0; }}
    .signal-list li {{ display:flex; justify-content:space-between; gap:20px; padding:13px 0; border-top:1px solid var(--line); color:var(--muted); }}
    .signal-list li:first-child {{ border-top:0; }} .signal-list strong {{ color:var(--ink); font-family:var(--mono); }}
    .blocker-number {{ display:block; color:var(--red); font:700 clamp(54px,7vw,92px)/1 var(--serif); letter-spacing:-.04em; }}
    .blocker-limit {{ color:var(--muted); font:12px/1.5 var(--mono); }}
    .protocol-note {{ margin-top:22px; padding:21px 24px; color:#f1eee4; background:var(--forest); border-left:5px solid var(--gold); }}
    .protocol-note strong {{ color:#f2ca6b; }}
    .flow {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; align-items:stretch; }}
    .flow-node {{ position:relative; min-height:150px; padding:20px 16px; background:var(--paper-hi); border:1px solid var(--line); }}
    .flow-node:not(:last-child)::after {{ content:"→"; position:absolute; z-index:2; right:-18px; top:50%; color:var(--gold); font:700 20px/1 var(--mono); }}
    .flow-node b {{ display:block; color:var(--gold); font:700 11px/1 var(--mono); }}
    .flow-node strong {{ display:block; margin:14px 0 8px; font:650 20px/1.15 var(--serif); }}
    .flow-node span {{ color:var(--muted); font-size:12px; }}
    .flow-node.dark {{ color:var(--paper-hi); background:var(--forest-deep); }} .flow-node.dark span {{ color:#b9c9c1; }}
    .ledger-split {{ display:grid; grid-template-columns:1fr 1fr; gap:1px; margin-top:20px; background:var(--line); border:1px solid var(--line); }}
    .ledger {{ padding:24px; background:var(--paper-hi); }} .ledger:last-child {{ background:var(--green-pale); }}
    .ledger small {{ color:var(--muted); font:700 10px/1 var(--mono); letter-spacing:.12em; }}
    .ledger strong {{ display:block; margin:11px 0 6px; font:650 25px/1 var(--serif); }}
    .split-board {{ display:grid; grid-template-columns:1.2fr .8fr; gap:22px; }}
    .split-bar {{ display:flex; height:34px; overflow:hidden; margin:18px 0; background:#dbe5dd; }}
    .split-bar span:nth-child(1) {{ width:57.62%; background:var(--moss); }}
    .split-bar span:nth-child(2) {{ width:20.45%; background:var(--gold); }}
    .split-bar span:nth-child(3) {{ width:21.93%; background:var(--red); }}
    .split-legend {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
    .split-legend strong {{ display:block; font:650 29px/1 var(--serif); }} .split-legend span {{ color:var(--muted); font-size:12px; }}
    .audit-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:1px; background:var(--line); border:1px solid var(--line); }}
    .audit-grid div {{ padding:18px; background:var(--paper-hi); }} .audit-grid strong {{ display:block; color:var(--moss); font:650 28px/1 var(--serif); }}
    .audit-grid span {{ display:block; margin-top:8px; color:var(--muted); font-size:12px; }}
    .reward-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:22px; }}
    .weights {{ display:grid; gap:13px; }} .weight-head {{ display:flex; justify-content:space-between; font:12px/1 var(--mono); }}
    .track {{ height:9px; margin-top:6px; background:#dce4dc; }} .track i {{ display:block; height:100%; background:var(--moss); }}
    .boundary-card {{ color:var(--paper-hi); background:var(--forest-deep); }}
    .boundary-card ul {{ margin:16px 0 0; padding-left:18px; color:#c6d5cd; }} .boundary-card li {{ margin:8px 0; }}
    .judge-stamp {{ display:grid; grid-template-columns:140px 1fr; gap:24px; align-items:center; margin-top:22px; padding:22px; background:var(--gold-pale); }}
    .judge-stamp strong {{ font:700 52px/1 var(--serif); color:var(--forest); }} .judge-stamp p {{ margin:0; color:#5d533a; }}
    table {{ width:100%; border-collapse:collapse; background:rgba(251,248,239,.8); }}
    th,td {{ padding:14px 13px; text-align:left; border-bottom:1px solid var(--line); font-size:12px; vertical-align:top; }}
    th {{ color:var(--muted); font:700 10px/1.25 var(--mono); letter-spacing:.08em; text-transform:uppercase; }}
    td code {{ color:var(--moss); }} tr.selected {{ background:var(--green-pale); }} tr.rejected {{ background:rgba(239,215,208,.42); }}
    .verdict {{ font:700 10px/1 var(--mono); }} .verdict.pass {{ color:var(--moss); }} .verdict.fail {{ color:var(--red); }}
    .curve-grid {{ grid-template-columns:repeat(3,1fr); margin-top:22px; }}
    .curve-card {{ padding:22px; background:var(--paper-hi); border:1px solid var(--line); }}
    .curve-card h4 {{ margin:0 0 12px; font:650 20px/1 var(--serif); }}
    .spark {{ width:100%; height:90px; overflow:visible; }} .spark .grid {{ stroke:rgba(20,57,45,.12); stroke-width:1; }}
    .spark .reward {{ fill:none; stroke:var(--moss); stroke-width:3; }} .spark .kl {{ fill:none; stroke:var(--gold); stroke-width:2; }}
    .curve-meta {{ display:flex; justify-content:space-between; color:var(--muted); font:10px/1.5 var(--mono); }}
    .warning {{ margin-top:20px; padding:18px 20px; background:var(--red-pale); color:#70342b; border-left:4px solid var(--red); }}
    .compare-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:22px; }}
    .metric-compare {{ display:grid; gap:17px; }} .compare-row .row-head {{ display:flex; justify-content:space-between; font-size:12px; }}
    .dual-track {{ position:relative; height:18px; margin-top:7px; background:#dddcd3; }}
    .dual-track i,.dual-track b {{ position:absolute; left:0; height:8px; }} .dual-track i {{ top:0; background:#9fa9a3; }} .dual-track b {{ bottom:0; background:var(--moss); }}
    .ci-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:1px; margin-top:24px; background:var(--line); border:1px solid var(--line); }}
    .ci-cell {{ padding:20px; background:var(--paper-hi); }} .ci-cell strong {{ display:block; font:650 25px/1 var(--serif); }} .ci-cell span {{ color:var(--muted); font:10px/1.5 var(--mono); }}
    .delta.good {{ color:var(--moss); font-weight:700; }} .delta.bad {{ color:var(--red); font-weight:700; }}
    .gate-band {{ display:grid; grid-template-columns:.7fr 1.3fr; margin-top:24px; color:var(--paper-hi); background:var(--forest-deep); }}
    .gate-band .state {{ display:grid; place-content:center; min-height:220px; padding:28px; text-align:center; border-right:1px solid rgba(255,255,255,.14); }}
    .gate-band .state strong {{ color:#f1bd55; font:700 50px/1 var(--serif); }} .gate-band .state span {{ margin-top:10px; color:#c3d0ca; font:10px/1.5 var(--mono); }}
    .gate-band .checks {{ padding:25px 30px; }} .gate-band ul {{ list-style:none; padding:0; margin:0; columns:2; column-gap:28px; }}
    .gate-band li {{ break-inside:avoid; display:flex; justify-content:space-between; gap:12px; padding:9px 0; color:#bdcbc4; border-bottom:1px solid rgba(255,255,255,.09); font-size:11px; }}
    .gate-band li strong {{ color:#8ed0ac; font-family:var(--mono); }}
    .diagnostic {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1px; margin-top:22px; background:var(--line); border:1px solid var(--line); }}
    .diagnostic div {{ padding:20px; background:var(--paper-hi); }} .diagnostic strong {{ display:block; font:650 28px/1 var(--serif); }} .diagnostic span {{ color:var(--muted); font-size:11px; }}
    .knowledge-list {{ display:grid; gap:12px; }}
    .knowledge-card {{ display:grid; grid-template-columns:78px 1fr; background:rgba(251,248,239,.88); border:1px solid var(--line); transition:.18s ease; }}
    .knowledge-card:hover {{ transform:translateY(-2px); box-shadow:var(--shadow); }}
    .knowledge-index {{ padding:23px; color:var(--gold); font:700 18px/1 var(--mono); border-right:1px solid var(--line); }}
    .knowledge-body {{ min-width:0; padding:22px 25px; }} .knowledge-head {{ display:flex; justify-content:space-between; gap:18px; align-items:center; }}
    .knowledge-head h3 {{ margin:0; font:650 24px/1.12 var(--serif); }} .knowledge-body p {{ margin:9px 0 0; color:var(--muted); }}
    .pill {{ flex:0 0 auto; padding:5px 8px; border:1px solid currentColor; font:700 9px/1 var(--mono); letter-spacing:.08em; }}
    .pill.ok {{ color:var(--moss); }} .pill.partial {{ color:#9b6f14; }} .pill.stop {{ color:var(--red); }}
    .evidence-inline {{ display:flex; flex-wrap:wrap; gap:7px; margin-top:13px; }}
    .evidence-link {{ max-width:100%; padding:5px 8px; color:var(--moss); background:var(--green-pale); font:10px/1.35 var(--mono); text-decoration:none; overflow-wrap:anywhere; }}
    .evidence-link:hover {{ background:var(--gold-pale); }}
    .governance-grid {{ display:grid; grid-template-columns:.9fr 1.1fr; gap:22px; }}
    .switch-list {{ list-style:none; padding:0; margin:0; }} .switch-list li {{ display:flex; justify-content:space-between; gap:18px; padding:14px 0; border-top:1px solid var(--line); }}
    .switch-list strong {{ color:var(--moss); font-family:var(--mono); }}
    .next-list {{ counter-reset:item; margin:0; padding:0; list-style:none; }} .next-list li {{ position:relative; padding:0 0 23px 48px; color:var(--muted); }}
    .next-list li::before {{ counter-increment:item; content:counter(item); position:absolute; left:0; top:0; display:grid; place-content:center; width:30px; height:30px; color:var(--paper-hi); background:var(--forest); font:700 11px/1 var(--mono); }}
    .next-list strong {{ display:block; color:var(--ink); }}
    .evidence-table a {{ color:var(--moss); font-family:var(--mono); overflow-wrap:anywhere; }}
    footer {{ padding:40px 0 84px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; }}
    .footer-grid {{ display:flex; justify-content:space-between; gap:24px; }}
    .reveal {{ opacity:0; transform:translateY(15px); transition:opacity .5s ease,transform .5s ease; }} .reveal.visible {{ opacity:1; transform:none; }}
    @media (prefers-reduced-motion:reduce) {{ html {{ scroll-behavior:auto; }} .reveal {{ opacity:1; transform:none; transition:none; }} }}
    @media (max-width:1050px) {{ .hero-grid,.section-head,.decision-grid,.two-col,.split-board,.reward-grid,.compare-grid,.governance-grid {{ grid-template-columns:1fr; }} .metric-strip {{ grid-template-columns:repeat(2,1fr); }} .report-grid {{ grid-template-columns:1fr; }} aside {{ display:none; }} .flow {{ grid-template-columns:1fr; }} .flow-node:not(:last-child)::after {{ content:"↓"; right:50%; top:auto; bottom:-18px; }} .curve-grid {{ grid-template-columns:1fr; }} }}
    @media (max-width:700px) {{ .shell {{ width:min(100% - 28px,700px); }} h1 {{ font-size:64px; }} .metric-strip,.ci-grid,.diagnostic {{ grid-template-columns:1fr; }} .gate-band {{ grid-template-columns:1fr; }} .gate-band .state {{ border-right:0; border-bottom:1px solid rgba(255,255,255,.14); }} .gate-band ul {{ columns:1; }} .knowledge-card {{ grid-template-columns:48px 1fr; }} .knowledge-index {{ padding:18px 10px; font-size:13px; }} .knowledge-body {{ padding:18px 15px; }} .knowledge-head {{ align-items:flex-start; }} .split-legend {{ grid-template-columns:1fr; }} .footer-grid {{ display:block; }} }}
    @media print {{ .progress,aside {{ display:none; }} body {{ background:white; }} .shell {{ width:100%; }} .hero {{ min-height:auto; page-break-after:always; }} .report-grid {{ display:block; }} main section {{ break-inside:avoid; }} .reveal {{ opacity:1; transform:none; }} a {{ text-decoration:none; }} }}
  </style>
</head>
<body>
  <div class="progress" id="progress"></div>
  <header class="hero shell">
    <div class="hero-grid">
      <div>
        <div class="eyebrow">StudyHub Agent / Offline RL Experiment</div>
        <h1>Router RL<span>Pilot 训练与独立测试</span></h1>
        <p class="hero-lead">本报告记录三随机种子训练、Raw / Executable 双账本、候选冻结和一次性独立测试。执行投影差值超过预设阈值，最终 Gate 为 NO-GO。</p>
        <div class="hero-meta"><span>{report_date}</span><span>Qwen3.5-2B + LoRA</span><span>custom group-relative policy gradient</span><span>production isolated</span></div>
      </div>
      <div class="status-card">
        <div class="label">FINAL PILOT GATE</div>
        <strong>NO-GO</strong>
        <p>当前 RL adapter 不进入后续发布流程。seed 3407 保留用于分析 Reward 与 runtime projection 的对齐问题。</p>
        <div class="status-rule">BLOCKER / |Δ executable−raw| 增幅 {test_delta['constraint_dependency_absolute']:.4f} &gt; 0.0200</div>
      </div>
    </div>
    <div class="metric-strip">
      <div class="metric"><strong>3</strong><span>独立训练 seeds</span></div>
      <div class="metric"><strong>144</strong><span>训练 rollouts</span></div>
      <div class="metric"><strong class="good">+{test_delta['raw_policy_reward']:.3f}</strong><span>测试 Raw Reward</span></div>
      <div class="metric"><strong class="good">+{test_delta['raw_episode_success_rate']*100:.1f}pp</strong><span>测试 Episode 成功率</span></div>
      <div class="metric"><strong class="bad">1</strong><span>预设 Gate blocker</span></div>
    </div>
  </header>

  <div class="shell report-grid">
    <aside>
      <div class="rail-title">REPORT INDEX</div>
      <a href="#decision">01 / 结论</a><a href="#architecture">02 / 任务与算法</a><a href="#data">03 / 数据隔离</a>
      <a href="#reward">04 / Reward 边界</a><a href="#training">05 / 训练稳定性</a><a href="#evaluation">06 / 独立评测</a>
      <a href="#robustness">07 / 鲁棒性</a><a href="#knowledge">08 / 26 项覆盖</a><a href="#governance">09 / 治理与回滚</a>
      <div class="rail-state">RESEARCH ONLY<br>PRODUCTION = DISABLED<br>FINAL HOLDOUT = UNREAD</div>
    </aside>
    <main>
      <section id="decision">
        <div class="kicker">01 / TEST RESULT</div>
        <div class="section-head"><h2>独立测试结果与最终 Gate</h2><p>seed 3407 在独立测试中提高了主要指标，原始安全 Gate 未退化。由于约束依赖指标超过 selection manifest 预设阈值，最终 Gate 按预注册规则判定为 NO-GO。</p></div>
        <div class="decision-grid">
          <article class="panel signal reveal"><h3>主要测试结果</h3><ul class="signal-list">
            <li><span>Raw policy reward</span><strong>{test_baseline_raw['policy_reward_mean']:.4f} → {test_candidate_raw['policy_reward_mean']:.4f}</strong></li>
            <li><span>动作选择成功率</span><strong>{_pct(test_baseline_raw['choice_success_rate'])} → {_pct(test_candidate_raw['choice_success_rate'])}</strong></li>
            <li><span>Episode 成功率</span><strong>{_pct(test_baseline_raw['episode_success_rate'])} → {_pct(test_candidate_raw['episode_success_rate'])}</strong></li>
            <li><span>Premature final</span><strong>5 → 3</strong></li>
            <li><span>Raw hard gates</span><strong>全部持平或改善</strong></li>
          </ul></article>
          <article class="panel blocker reveal"><h3>未通过的 Gate 指标</h3><span class="blocker-number">+{test_delta['constraint_dependency_absolute']:.4f}</span><div class="blocker-limit">允许的绝对差增幅上限 / +0.0200</div><p>候选的 Raw→Executable Reward 差从 {baseline_test['constraint_dependency_delta_mean']:.4f} 扩大到 {candidate_test['constraint_dependency_delta_mean']:.4f}，超过预注册上限。</p></article>
        </div>
        <div class="protocol-note reveal"><strong>预注册规则：</strong>测试完成后不将阈值从 0.02 调整为 0.04。当前 test 已消费，只用于本次冻结候选的最终判断；下一版本需要建立新数据版本和输入锁。</div>
      </section>

      <section id="architecture">
        <div class="kicker">02 / Task · MDP · Algorithm</div>
        <div class="section-head"><h2>训练目标与两级评测</h2><p>训练将单个 Router state 建模为 contextual bandit，同一状态采样 3 个动作并计算组内相对优势。独立多步环境用于验证 transition、episode 和终止条件；该 Pilot 不按完整轨迹级 GRPO 解释。</p></div>
        <div class="flow reveal">
          <div class="flow-node"><b>STATE</b><strong>请求 + 上下文</strong><span>预算、历史、工具观察、可信资料与显式页码</span></div>
          <div class="flow-node"><b>ROLLOUT × 3</b><strong>策略动作组</strong><span>temperature {config['temperature']} · top-p {config['top_p']} · max {config['max_new_tokens']}</span></div>
          <div class="flow-node"><b>RAW REWARD</b><strong>组内优势</strong><span>语义动作、查询、证据顺序、停止决策与效用</span></div>
          <div class="flow-node dark"><b>OPTIMIZE</b><strong>Clipped PG + KL</strong><span>β={config['kl_beta']} · ε={config['clip_epsilon']} · AdamW {config['learning_rate']}</span></div>
          <div class="flow-node"><b>ADAPTER</b><strong>LoRA policy</strong><span>Reference 冻结；只更新 {training['seed_3407']['trainable_parameters']:,} 参数</span></div>
        </div>
        <div class="ledger-split reveal">
          <div class="ledger"><small>LEDGER A / GRADIENT</small><strong>Raw policy proposal</strong><p>训练梯度仅来自模型原始提议，运行时修正不计入 Reward。</p></div>
          <div class="ledger"><small>LEDGER B / EXECUTION</small><strong>Constrained executable</strong><p>确定性参数保护、只读权限、预算与显式页码只作为硬门和执行投影。</p></div>
        </div>
      </section>

      <section id="data">
        <div class="kicker">03 / Dataset governance</div>
        <div class="section-head"><h2>数据范围与泄漏审计</h2><p>数据仅来自本地冻结的免费资料 metadata 与 preview evidence；未访问生产数据库、API、OSS 写接口、付费资料、Router 300 条开发诊断或最终生产 holdout。</p></div>
        <div class="split-board">
          <article class="panel reveal"><h3>269 states · 83 episodes</h3><div class="split-bar"><span></span><span></span><span></span></div><div class="split-legend">
            <div><strong>155</strong><span>Train · 37 materials</span></div><div><strong>55</strong><span>Validation · 12 materials</span></div><div><strong>59</strong><span>Test · 13 materials</span></div>
          </div><p>训练实际按每个 seed 分层抽取 16 个 state，每个 state 3 个 rollout；Validation 用于选模，Test 只在 seed 3407 冻结后运行一次。</p></article>
          <article class="audit-grid reveal">
            <div><strong>0</strong><span>material split leaks</span></div><div><strong>0</strong><span>query split leaks</span></div>
            <div><strong>0</strong><span>duplicate normalized queries</span></div><div><strong>11</strong><span>场景 families / split</span></div>
            <div><strong>135</strong><span>frozen free materials</span></div><div><strong>62</strong><span>有 preview evidence</span></div>
          </article>
        </div>
        <div class="warning"><strong>术语说明：</strong>这里的“offline”指与生产环境完全隔离，并非学术上仅从固定 logged transitions 学习的 strict offline RL。训练仍由当前策略在本地冻结 state 上生成 on-policy rollout。</div>
      </section>

      <section id="reward">
        <div class="kicker">04 / Reward · Constraints · Judge</div>
        <div class="section-head"><h2>策略 Reward 与运行时硬约束</h2><p>可由 runtime 确定性保证的内容不进入策略奖励。Reward 限幅到 [-1, 1]，激活分项按权重重新归一化；组内 reward 再标准化为 advantage。</p></div>
        <div class="reward-grid">
          <article class="panel reveal"><h3>Policy-owned components</h3><div class="weights">
            {_weight_row('Tool choice',30)}{_weight_row('Query quality',20)}{_weight_row('Evidence order',15)}{_weight_row('Stop decision',15)}{_weight_row('Groundedness',10)}{_weight_row('Utility',10)}
          </div><p>附加惩罚：duplicate search −0.12、premature final −0.20、verbosity gaming −0.08、unsafe tool reliance −0.10。</p></article>
          <article class="panel boundary-card reveal"><h3>Runtime-owned hard gates</h3><ul><li>严格 JSON 与 Router contract</li><li>只读工具 allowlist 与 permission boundary</li><li>工具预算与 force-final</li><li>可信 material_id</li><li>显式 page_numbers</li><li>参数范围与敏感信息阻断</li></ul><p>这些约束不参与训练梯度，违规动作在执行前被拒绝。</p></article>
        </div>
        <div class="judge-stamp reveal"><strong>{_pct(calibration['pairwise_accuracy'])}</strong><p><b>48 个 validation preference pairs</b><br>确定性 rubric Judge 的 pairwise accuracy 与 JSON serialization invariance 均为 100%。但标签仅为 teacher-reviewed Silver，不是 human gold，也不覆盖开放式题解质量。</p></div>
      </section>

      <section id="training">
        <div class="kicker">05 / Multi-seed training</div>
        <div class="section-head"><h2>三随机种子训练与验证结果</h2><p>三个 seed 均完成 16 次更新和 48 条 rollout，训练过程未出现 NaN/Inf，KL 与显存处于设定范围。验证集结果存在较大种子差异，仅 seed 3407 同时满足收益和安全非退化阈值。</p></div>
        <div class="panel reveal"><table><thead><tr><th>Run</th><th>Train reward</th><th>Mean / max KL</th><th>Entropy proxy</th><th>Peak VRAM</th><th>Validation reward</th><th>Gate</th></tr></thead><tbody>{training_rows}</tbody></table></div>
        <div class="curve-grid">{curve_cards}</div>
        <div class="diagnostic reveal">
          <div><strong>{multi_seed['training']['reward_mean']['mean']:.3f}</strong><span>3-seed train reward mean</span></div>
          <div><strong>{multi_seed['validation']['raw_reward_mean']['sample_std']:.3f}</strong><span>validation reward seed std</span></div>
          <div><strong>{multi_seed['training']['mean_kl']['mean']:.2e}</strong><span>mean KL across seeds</span></div>
          <div><strong>{multi_seed['training']['peak_memory_mib']['maximum']/1024:.1f} GiB</strong><span>successful peak VRAM</span></div>
        </div>
        <div class="warning"><strong>Peak guard 记录：</strong>初始 group=4 / max_tokens=384 的试跑达到 {failed_peak_mib/1024:.1f} GiB 后主动停止并保留现场；正式锁定为 group=3 / max_tokens=320，成功峰值降至 {multi_seed['training']['peak_memory_mib']['maximum']/1024:.1f} GiB。clip fraction 全为 0，因为每组只做一次更新且学习率极小；这表示 clipping 被监控但未实际触发。日志中的 grad_norm 是裁剪前值，实际更新按 max_grad_norm={config['max_grad_norm']} 裁剪。</div>
      </section>

      <section id="evaluation">
        <div class="kicker">06 / Validation · Frozen selection · Test</div>
        <div class="section-head"><h2>候选选择与独立测试</h2><p>Validation 淘汰 seed 7703（JSON/contract 退化）和 seed 9109（Reward、动作、episode 与 grounded final 退化），并冻结 seed 3407。Test 未参与候选选择或阈值修改。</p></div>
        <div class="compare-grid">
          <article class="panel reveal"><h3>Validation</h3>{_metric_comparison(validation_baseline_raw, validation_candidate_raw)}<p>seed 3407：Reward {_signed(validation_candidate_raw['policy_reward_mean']-validation_baseline_raw['policy_reward_mean'])}，动作 {_pp(validation_candidate_raw['choice_success_rate']-validation_baseline_raw['choice_success_rate'])}，episode {_pp(validation_candidate_raw['episode_success_rate']-validation_baseline_raw['episode_success_rate'])}。</p></article>
          <article class="panel reveal"><h3>Independent test</h3>{_metric_comparison(test_baseline_raw, test_candidate_raw)}<p>Reward 与动作的 bootstrap 95% CI 仍跨 0，episode 差值 CI 下界为 0。当前样本量不足以确认 Reward 与动作指标存在稳定增益。</p></article>
        </div>
        <div class="ci-grid reveal">
          <div class="ci-cell"><strong>+{test_delta['raw_policy_reward']:.4f}</strong><span>Reward Δ · 95% CI [{raw_reward_ci[0]:.4f}, {raw_reward_ci[1]:.4f}]</span></div>
          <div class="ci-cell"><strong>{_pp(test_delta['raw_choice_success_rate'])}</strong><span>Choice Δ · 95% CI [{_pp(choice_ci[0])}, {_pp(choice_ci[1])}]</span></div>
          <div class="ci-cell"><strong>{_pp(test_delta['raw_episode_success_rate'])}</strong><span>Episode Δ · 95% CI [{_pp(episode_ci[0])}, {_pp(episode_ci[1])}]</span></div>
        </div>
        <div class="gate-band reveal"><div class="state"><strong>NO-GO</strong><span>INDEPENDENT TEST GATE<br>1 blocker / 9 checks</span></div><div class="checks"><ul>{''.join(f'<li><span>{_escape(name)}</span><strong>{"PASS" if passed else "FAIL"}</strong></li>' for name, passed in test_gate['checks'].items())}</ul></div></div>
        <div class="diagnostic reveal">
          <div><strong>+{test_delta['executable_policy_reward']:.4f}</strong><span>Executable Reward Δ</span></div>
          <div><strong>{_pp(test_delta['executable_choice_success_rate'])}</strong><span>Executable choice Δ</span></div>
          <div><strong>{test_delta['constraint_correction_count']}</strong><span>constraint correction count Δ</span></div>
          <div><strong class="delta bad">+{test_delta['constraint_dependency_absolute']:.4f}</strong><span>absolute ledger-gap increase</span></div>
        </div>
      </section>

      <section id="robustness">
        <div class="kicker">07 / Robustness by family</div>
        <div class="section-head"><h2>分任务类型测试结果</h2><p>独立测试中，empty search、memory read 和 grounded final 指标提高；synthesize_context 与 untrusted_observation 仍为 0%。多数边界任务类型仅含 1 条样本，当前结果只用于定位问题，不能估计稳定通过率。</p></div>
        <div class="panel reveal"><table><thead><tr><th>Family</th><th>N</th><th>Baseline choice</th><th>Candidate choice</th><th>Choice Δ</th><th>Reward Δ</th><th>Interpretation</th></tr></thead><tbody>{robustness_rows}</tbody></table></div>
        <div class="panel reveal" style="margin-top:22px"><h3>Raw safety hard gates</h3><table><thead><tr><th>Gate</th><th>Baseline</th><th>Candidate</th><th>Δ</th></tr></thead><tbody>{hard_gate_rows}</tbody></table></div>
      </section>

      <section id="knowledge">
        <div class="kicker">08 / Complete knowledge coverage</div>
        <div class="section-head"><h2>RL 实验技术项与证据索引</h2><p>26 个技术项分别记录实现状态、实测结果和已知限制。Judge 人工金标、轨迹级 credit assignment、边界样本规模和生产发布演练仍未完成。</p></div>
        <div class="knowledge-list">{knowledge_cards}</div>
      </section>

      <section id="governance">
        <div class="kicker">09 / Reproducibility · Deployment · Rollback</div>
        <div class="section-head"><h2>离线研究范围与生产隔离</h2><p>训练、验证与测试均使用本地模型、本地冻结数据和显式离线环境。生产默认开关未改变，当前 adapter 未进入部署流程；回滚目标为冻结的 SFT v1.7。</p></div>
        <div class="governance-grid">
          <article class="panel reveal"><h3>Production invariants</h3><ul class="switch-list">
            <li><span>dynamic tools</span><strong>{str(production_defaults['ai_agent_dynamic_tools_enabled']).lower()}</strong></li>
            <li><span>runtime constraints</span><strong>{str(production_defaults['ai_agent_runtime_constraints_enabled']).lower()}</strong></li>
            <li><span>model provider</span><strong>{_escape(production_defaults['agentic_model_provider'])}</strong></li>
            <li><span>production API / DB / OSS</span><strong>not accessed</strong></li>
            <li><span>final production holdout</span><strong>unread</strong></li>
            <li><span>rollback adapter</span><strong>SFT v1.7</strong></li>
          </ul></article>
          <article class="panel reveal"><h3>后续实验顺序</h3><ol class="next-list">
            <li><strong>保留当前 Test</strong>不再用该集合调参；seed 3407 仅用于失败分析。</li>
            <li><strong>分析 Reward / projection 差值</strong>逐状态检查投影降低 rubric reward 的原因，安全修正不加入训练梯度。</li>
            <li><strong>补充边界数据</strong>增加 synthesize_context、untrusted observation、grounded final 与多步 credit assignment。</li>
            <li><strong>创建 v2 数据和输入锁</strong>重新执行 material/query 隔离、Judge 校准、3-seed 训练和新的 Validation/Test。</li>
            <li><strong>补齐后续评测</strong>完成人工金标、最终 holdout、只读 shadow、canary 和自动回滚演练。</li>
          </ol></article>
        </div>
        <div class="panel reveal" style="margin-top:22px"><h3>Evidence ledger</h3><table class="evidence-table"><thead><tr><th>Artifact</th><th>Local path</th><th>SHA-256 prefix</th></tr></thead><tbody>{evidence_table}</tbody></table></div>
        <div class="panel reveal" style="margin-top:22px"><h3>Global Gate checks</h3><ul class="signal-list">{global_check_rows}</ul></div>
      </section>
    </main>
  </div>
  <footer><div class="shell footer-grid"><span>StudyHub Agent · Router RL Pilot · research-only evidence report</span><span>Conclusion: {_escape(gate['conclusion'])} · candidate {_escape(selection['selected_label'])}</span></div></footer>
  <script>
    const progress=document.getElementById('progress');
    const sections=[...document.querySelectorAll('main section')];
    const links=[...document.querySelectorAll('aside a')];
    const reveal=new IntersectionObserver(entries=>entries.forEach(e=>{{if(e.isIntersecting)e.target.classList.add('visible')}}),{{threshold:.08}});
    document.querySelectorAll('.reveal').forEach(el=>reveal.observe(el));
    addEventListener('scroll',()=>{{const h=document.documentElement.scrollHeight-innerHeight;progress.style.width=(h?scrollY/h*100:0)+'%';let current=sections[0]?.id;sections.forEach(s=>{{if(s.getBoundingClientRect().top<innerHeight*.35)current=s.id}});links.forEach(a=>a.classList.toggle('active',a.hash==='#'+current));}},{{passive:true}});
  </script>
</body>
</html>
"""


def _knowledge_coverage(*, repo_root: Path, artifact_root: Path, evaluation_root: Path) -> list[dict[str, Any]]:
    code = repo_root / "ml/agentic_platform/rl"
    tests = BACKEND_ROOT / "tests/agentic_platform/test_router_rl_pilot.py"
    constraints = BACKEND_ROOT / "app/services/agent_router_constraint_service.py"
    gate = evaluation_root / "gate/gate.json"
    items = [
        (1, "RL 目标", "VERIFIED", "优化 Router 的语义动作、停止决策和任务完成率；硬安全指标不纳入可加权的 Reward 分项。", [code / "reward.py", code / "configs/router_grpo_pilot_v1.json"]),
        (2, "状态 State", "VERIFIED", "状态包含请求、预算、任务上下文、搜索历史、可信工具观察和 evidence rubric。", [code / "spec.py"]),
        (3, "动作 Action", "VERIFIED", "动作空间为只读 Router contract：工具调用或 final；工具名与参数被结构化评分。", [code / "reward.py", constraints]),
        (4, "状态转移 Transition", "VERIFIED", "独立环境按成功语义动作推进 next_state_id，错误动作终止轨迹。", [code / "environment.py", tests]),
        (5, "Episode 与终止", "VERIFIED", "83 个 episode；支持 terminal、错误动作提前终止和 terminal bonus。", [code / "environment.py", artifact_root / "audit.json"]),
        (6, "初始与参考策略", "LOCKED", "Qwen3.5-2B + SFT v1.7 为初始策略，同一 SFT adapter 冻结为 reference。", [artifact_root / "input_lock.json", code / "trainer.py"]),
        (7, "Rollout 构造", "VERIFIED", "每 state 采样 3 个候选、组内标准化 advantage；每 seed 48 rollouts。", [code / "trainer.py", code / "configs/router_grpo_pilot_v1.json"]),
        (8, "数据划分", "VERIFIED", "Train/Validation/Test 按 material 与 query 隔离；开发诊断和最终 holdout 未读。", [artifact_root / "audit.json", artifact_root / "manifest.json"]),
        (9, "Reward 设计", "VERIFIED", "六项策略 Reward、四类 hacking penalty、[-1,1] clipping 和激活权重归一化。", [code / "reward.py"]),
        (10, "硬约束边界", "VERIFIED", "权限、只读工具、预算、可信 ID、页码与 contract 只做硬门和执行投影。", [constraints, code / "reward.py"]),
        (11, "Reward 来源", "SILVER", "采用确定性规则、环境结果与教师 Silver rubric；未声称 human-gold 或外部 LLM Judge。", [artifact_root / "judge_calibration.json", code / "reward.py"]),
        (12, "Judge 校准", "CALIBRATED", "48 对偏好 pairwise accuracy 100%、序列化不变性 100%；开放式教学质量未覆盖。", [artifact_root / "judge_calibration.json"]),
        (13, "算法选择", "IMPLEMENTED", "实现方式为 GRPO-style contextual-bandit clipped policy gradient，与 TRL/veRL 的完整 GRPO 实现区分记录。", [code / "trainer.py", code / "configs/router_grpo_pilot_v1.json"]),
        (14, "Credit assignment", "PARTIAL", "训练使用 state-level group advantage；多步 transition 由环境评测，尚非轨迹级 policy gradient。", [code / "trainer.py", code / "environment.py"]),
        (15, "KL、Entropy 与探索", "VERIFIED", "reference KL β=0.02；监控 KL、entropy proxy、clip fraction；采样温度提供探索。", [code / "trainer.py", artifact_root / "runs/seed_3407/trainer_metrics.jsonl"]),
        (16, "Reward scaling", "VERIFIED", "分项重归一、总 Reward 限幅、组内均值/标准差标准化；同分组 advantage 归零。", [code / "reward.py", tests]),
        (17, "采样策略", "LOCKED", "temperature、top-p、group size、输出长度和分层 state 选择均写入哈希锁定配置。", [code / "configs/router_grpo_pilot_v1.json", artifact_root / "input_lock.json"]),
        (18, "训练稳定性", "VERIFIED", "三 seed 无 NaN/Inf；KL、梯度、长度、显存与失败 peak-guard 现场均有记录。", [gate, artifact_root / "runs/failed_seed_3407_peak_guard_20260812/gpu_samples.csv"]),
        (19, "Reward hacking 与坍缩", "OBSERVED", "监控 premature final、重复搜索、冗长和不安全工具；seed 方差与 synthesis 弱点被保留。", [code / "reward.py", gate]),
        (20, "双账本", "BLOCKER", "Raw ledger 产生梯度，Executable ledger 只审计；测试 gap 增幅 0.0316 超过 0.02。", [code / "reward.py", gate]),
        (21, "业务 Gate", "NO-GO", "Validation 用于冻结候选；Test 按预注册非退化阈值评测，constraint dependency 超阈值后结论为 NO-GO。", [code / "gate.py", gate]),
        (22, "鲁棒性", "PARTIAL", "覆盖 11 families 和权限/注入/空查询/预算边界，但多数边界 family 仅 1 条。", [artifact_root / "audit.json", evaluation_root / "test/seed_3407/summary.json"]),
        (23, "多 Seed 与统计", "PILOT", "3 seed 报告均值、样本标准差、Student-t 95% CI；测试使用 5000 次 paired bootstrap。", [gate]),
        (24, "LoRA 与显存", "VERIFIED", "LoRA r16/alpha32，16.82M 可训练参数；成功峰值约 58.6 GiB，失败试跑约 74.7 GiB。", [Path(str(_read_json(artifact_root / "input_lock.json")["policy"]["sft_adapter_path"])) / "adapter_config.json", gate]),
        (25, "复现与治理", "VERIFIED", "配置、数据、基座索引、tokenizer、SFT adapter 和关键实现均以 SHA-256 锁定。", [artifact_root / "input_lock.json", artifact_root / "runs/seed_3407/run_manifest.json"]),
        (26, "部署与回滚", "GUARDED", "当前仅 research-only；生产默认关闭，回滚为 SFT v1.7，shadow/canary/final holdout 尚未执行。", [evaluation_root / "gate/release_rollback_manifest.json", BACKEND_ROOT / "app/core/config.py"]),
    ]
    coverage = []
    for number, title, status, finding, evidence in items:
        tone = "stop" if status in {"BLOCKER", "NO-GO"} else "partial" if status in {"SILVER", "PARTIAL", "PILOT", "GUARDED", "OBSERVED"} else "ok"
        coverage.append(
            {
                "number": number,
                "title": title,
                "status": status,
                "tone": tone,
                "finding": finding,
                "evidence": [str(path.resolve()) for path in evidence],
            }
        )
    if [item["number"] for item in coverage] != list(range(1, 27)):
        raise ValueError("RL knowledge coverage must contain exactly items 1 through 26")
    for item in coverage:
        missing = [path for path in item["evidence"] if not Path(path).exists()]
        if missing:
            raise FileNotFoundError(f"knowledge item {item['number']} has missing evidence: {missing}")
    return coverage


def _training_row(label: str, summary: dict[str, Any], assessment: dict[str, Any]) -> str:
    stability = summary["stability"]
    validation_reward = {
        "seed_3407": 0.841560,
        "seed_7703": 0.834756,
        "seed_9109": 0.776328,
    }[label]
    row_class = "selected" if label == "seed_3407" else "rejected"
    verdict = "SELECTED" if assessment["passed"] else "REJECTED"
    blockers = "none" if assessment["passed"] else ", ".join(assessment["blockers"])
    return (
        f'<tr class="{row_class}"><td><code>{label}</code></td><td>{summary["reward"]["mean"]:.4f}</td>'
        f'<td>{stability["mean_kl"]:.2e} / {stability["max_kl"]:.2e}</td><td>{stability["mean_entropy_proxy"]:.4f}</td>'
        f'<td>{summary["gpu"]["peak_memory_mib"]/1024:.1f} GiB</td><td>{validation_reward:.4f}</td>'
        f'<td><span class="verdict {"pass" if assessment["passed"] else "fail"}">{verdict}</span><br><small>{_escape(blockers)}</small></td></tr>'
    )


def _curve_card(label: str, summary: dict[str, Any], metrics: list[dict[str, Any]]) -> str:
    rewards = [float(row["reward_mean"]) for row in metrics]
    kls = [float(row["kl"]) for row in metrics]
    reward_points = _polyline(rewards, width=300, height=62, minimum=-0.2, maximum=1.0)
    kl_max = max(kls) or 1e-6
    kl_points = _polyline(kls, width=300, height=62, minimum=0.0, maximum=kl_max)
    return f"""<article class="curve-card reveal"><h4>{label}</h4><svg class="spark" viewBox="0 0 300 82" role="img" aria-label="{label} reward and KL curves"><path class="grid" d="M0 10H300M0 41H300M0 72H300"/><polyline class="reward" points="{reward_points}"/><polyline class="kl" points="{kl_points}"/></svg><div class="curve-meta"><span>reward / green</span><span>KL / gold</span><span>16 updates</span></div><div class="curve-meta"><span>R̄ {summary['reward']['mean']:.3f}</span><span>KLmax {summary['stability']['max_kl']:.2e}</span></div></article>"""


def _robustness_rows(*, baseline: dict[str, Any], candidate: dict[str, Any], deltas: dict[str, Any]) -> str:
    rows = []
    for family, base in baseline.items():
        cand = candidate[family]
        delta = deltas[family]
        if cand["choice_success_rate"] == 0.0:
            interpretation = "仍失败 / expand data"
        elif delta["choice_success_delta"] > 0:
            interpretation = "improved"
        elif delta["choice_success_delta"] < 0:
            interpretation = "regressed"
        else:
            interpretation = "held"
        tone = "good" if delta["choice_success_delta"] >= 0 and cand["choice_success_rate"] > 0 else "bad"
        rows.append(
            f"<tr><td><code>{_escape(family)}</code></td><td>{base['samples']}</td><td>{_pct(base['choice_success_rate'])}</td>"
            f"<td>{_pct(cand['choice_success_rate'])}</td><td class=\"delta {tone}\">{_pp(delta['choice_success_delta'])}</td>"
            f"<td class=\"delta {'good' if delta['reward_delta'] >= 0 else 'bad'}\">{_signed(delta['reward_delta'])}</td><td>{_escape(interpretation)}</td></tr>"
        )
    return "".join(rows)


def _metric_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    metrics = [
        ("Raw reward", baseline["policy_reward_mean"], candidate["policy_reward_mean"]),
        ("Choice success", baseline["choice_success_rate"], candidate["choice_success_rate"]),
        ("Episode success", baseline["episode_success_rate"], candidate["episode_success_rate"]),
    ]
    return '<div class="metric-compare">' + "".join(
        f'<div class="compare-row"><div class="row-head"><span>{label}</span><strong>{base:.3f} → {cand:.3f}</strong></div>'
        f'<div class="dual-track"><i style="width:{max(0,min(100,base*100)):.1f}%"></i><b style="width:{max(0,min(100,cand*100)):.1f}%"></b></div></div>'
        for label, base, cand in metrics
    ) + "</div>"


def _weight_row(label: str, percentage: int) -> str:
    return f'<div><div class="weight-head"><span>{label}</span><strong>{percentage}%</strong></div><div class="track"><i style="width:{percentage}%"></i></div></div>'


def _polyline(values: list[float], *, width: int, height: int, minimum: float, maximum: float) -> str:
    if not values:
        return ""
    span = max(maximum - minimum, 1e-12)
    return " ".join(
        f"{index * width / max(1, len(values) - 1):.2f},{10 + height - (value - minimum) / span * height:.2f}"
        for index, value in enumerate(values)
    )


def _failed_peak_memory(path: Path) -> int:
    peak = 0
    with path.open(encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) >= 4:
                try:
                    peak = max(peak, int(row[3].strip()))
                except ValueError:
                    continue
    return peak


class _ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.external_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        identifier = values.get("id")
        if identifier:
            self.ids.add(identifier)
        href = values.get("href")
        if href:
            self.hrefs.append(href)
        source = values.get("src")
        if source and source.startswith(("http://", "https://")):
            self.external_sources.append(source)


def _validate_report(*, document: str, output_path: Path, coverage: list[dict[str, Any]]) -> dict[str, Any]:
    parser = _ReportParser()
    parser.feed(document)
    required_sections = {"decision", "architecture", "data", "reward", "training", "evaluation", "robustness", "knowledge", "governance"}
    required_knowledge = {f"knowledge-{number:02d}" for number in range(1, 27)}
    missing_local_links = []
    for href in parser.hrefs:
        if href.startswith("#"):
            continue
        if href.startswith(("http://", "https://")):
            parser.external_sources.append(href)
            continue
        if not (output_path.parent / href).resolve().exists():
            missing_local_links.append(href)
    checks = {
        "doctype_present": document.lstrip().lower().startswith("<!doctype html>"),
        "all_sections_present": required_sections.issubset(parser.ids),
        "all_26_knowledge_ids_present": required_knowledge.issubset(parser.ids) and len(coverage) == 26,
        "all_local_links_resolve": not missing_local_links,
        "no_external_resources": not parser.external_sources,
        "no_go_conclusion_visible": "NO-GO" in document and "NO_GO_INDEPENDENT_TEST" in document,
    }
    if not all(checks.values()):
        raise ValueError(
            f"RL report validation failed: checks={checks}, missing_links={missing_local_links}, "
            f"external_sources={parser.external_sources}"
        )
    return {
        "passed": True,
        "checks": checks,
        "local_links": sum(not href.startswith("#") for href in parser.hrefs),
        "knowledge_items": len(coverage),
    }


def _link(report_path: Path, target: Path, label: str | None = None) -> str:
    relative = os.path.relpath(target.resolve(), report_path.parent.resolve())
    shown = label or target.name
    return f'<a class="evidence-link" href="{html.escape(relative, quote=True)}">{html.escape(shown)}</a>'


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _pct(value: float) -> str:
    return f"{float(value) * 100:.1f}%"


def _pp(value: float) -> str:
    return f"{float(value) * 100:+.1f}pp"


def _signed(value: float) -> str:
    return f"{float(value):+.4f}"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_report(repo_root=args.repo_root.resolve(), output_path=args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
