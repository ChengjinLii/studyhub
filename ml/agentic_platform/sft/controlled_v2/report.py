"""Render the controlled-v2 SFT report exclusively from experiment artifacts."""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .completion_audit import _sealed_requirement, audit_completion
from .contract import ControlledPaths, contract_sha256

DEFAULT_OUTPUT = (
    ControlledPaths().project_root
    / "reports/recagent/agentic-platform/STUDYHUB_SFT_COMPLETION_REPORT.html"
)
STAGE_LABELS = {
    "router-lr": "Router learning rate",
    "router-epoch": "Router training length",
    "router-scheduler": "Router scheduler",
    "router-lora-rank": "Router LoRA rank",
    "router-lora-target": "Router target modules",
    "r-data-scale": "Router data scale",
    "r-data-replay": "Router replay ratio",
    "r-data-state": "Router state representation",
    "tutor-lr": "Tutor learning rate",
    "tutor-lora": "Tutor LoRA rank",
    "t-mix": "Tutor negative-evidence mixture",
}


def _optional_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "pending"
    return f"{float(value) * 100:.{digits}f}%"


def _number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "pending"
    return f"{float(value):,.{digits}f}"


def _seconds(value: Any) -> str:
    if value is None:
        return "pending"
    seconds = float(value)
    if seconds >= 3600:
        return f"{seconds / 3600:.2f} h"
    if seconds >= 60:
        return f"{seconds / 60:.1f} min"
    return f"{seconds:.0f} s"


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _relative_link(paths: ControlledPaths, path: Path, label: str) -> str:
    try:
        relative = path.resolve().relative_to(paths.project_root.resolve())
        href = "../../../" + str(relative)
    except ValueError:
        href = str(path)
    return f'<a href="{html.escape(href)}">{html.escape(label)}</a>'


def _pending(title: str, detail: str) -> str:
    return (
        '<article class="pending-card">'
        f"<b>{_escape(title)}</b><p>{_escape(detail)}</p>"
        "</article>"
    )


def _condition_label(condition: str) -> str:
    return {
        "base": "Base",
        "prompt": "Strong prompt",
        "few_shot": "Few-shot",
        "sft": "Completed SFT reference",
    }.get(condition, condition)


def _baseline_table(paths: ControlledPaths, task: str) -> str:
    index_path = paths.evaluation_root / "baselines" / task / "baseline_index.json"
    value = _optional_json(index_path)
    if not value:
        return _pending(
            f"{task.title()} 基线待完成",
            "Base、强 Prompt、Few-shot 和 SFT 参考模型尚未全部完成冻结 challenge 评测。",
        )
    comparisons = value["paired_comparisons"]
    rows = []
    reference_rate = None
    for condition in ("base", "prompt", "few_shot"):
        comparison = comparisons[condition]
        reference_rate = comparison["candidate_rate"]
        bootstrap = comparison["paired_bootstrap"]
        mcnemar = comparison["mcnemar_exact"]
        rows.append(
            "<tr>"
            f"<td><strong>{_condition_label(condition)}</strong></td>"
            f"<td>{_pct(comparison['baseline_rate'])}</td>"
            f"<td>{_pct(bootstrap['observed_delta'])}</td>"
            f"<td>[{_pct(bootstrap['ci95'][0])}, {_pct(bootstrap['ci95'][1])}]</td>"
            f"<td>{_number(mcnemar['exact_two_sided_p'], 6)}</td>"
            "</tr>"
        )
    rows.append(
        '<tr class="anchor-row">'
        "<td><strong>Completed SFT reference</strong></td>"
        f"<td>{_pct(reference_rate)}</td><td>anchor</td><td>anchor</td><td>anchor</td>"
        "</tr>"
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Condition</th><th>Strict pass</th><th>SFT delta</th>"
        "<th>Paired bootstrap 95% CI</th><th>McNemar p</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _arm_configuration(spec: dict[str, Any]) -> str:
    parts = [
        f"lr={spec.get('learning_rate')}",
        f"epoch={spec.get('epochs')}",
        f"r={spec.get('lora_rank')}",
        f"target={spec.get('lora_target')}",
    ]
    if spec.get("dataset_variant") != "frozen":
        parts.append(f"data={spec.get('dataset_variant')}")
    if spec.get("max_steps") is not None:
        parts.append(f"steps={spec.get('max_steps')}")
    return " · ".join(parts)


def _ablation_groups(paths: ControlledPaths, task: str) -> str:
    path = paths.evaluation_root / "ablation" / task / "ablation_index.json"
    value = _optional_json(path)
    if not value:
        return _pending(
            f"{task.title()} 消融待完成",
            "受控优化与单变量消融实验尚未完成。",
        )
    groups = []
    for group in value["groups"]:
        rows = []
        for arm in sorted(
            group["arms"],
            key=lambda item: (
                not item["is_anchor"],
                str(item["spec"]["experiment_id"]),
            ),
        ):
            paired = arm.get("paired_primary_vs_anchor") or {}
            ci = paired.get("paired_bootstrap", {}).get("ci95")
            ci_text = (
                f"[{_pct(ci[0])}, {_pct(ci[1])}]" if ci is not None else "anchor"
            )
            resources = arm["resources"]
            status = "PASS" if arm["gate_passed"] else "diagnostic"
            rows.append(
                "<tr>"
                f"<td><strong>{_escape(arm['spec']['experiment_id'])}</strong>"
                f"<small>{_escape(_arm_configuration(arm['spec']))}</small></td>"
                f"<td>{_pct(arm['selection_score'])}</td>"
                f"<td>{_pct(arm['metric_delta_vs_anchor'].get(group['primary_metric']))}</td>"
                f"<td>{ci_text}</td>"
                f"<td>{_seconds(resources.get('duration_seconds'))}</td>"
                f"<td>{_number(resources.get('peak_memory_mib'), 0)} MiB</td>"
                f'<td><span class="pill {"pass" if arm["gate_passed"] else "warn"}">{status}</span></td>'
                "</tr>"
            )
        resource_note = (
            "所有实验臂均记录为独占 GPU，资源数据可直接比较。"
            if group["resource_comparison_valid"]
            else "至少一个实验臂缺少独占 GPU 记录，资源数据仅作描述。"
        )
        groups.append(
            '<article class="experiment-group">'
            f'<div class="group-head"><div><span>{_escape(group["stage"])}</span>'
            f"<h3>{_escape(STAGE_LABELS.get(group['stage'], group['stage']))}</h3></div>"
            f'<p>Anchor: <code>{_escape(group["anchor"]["experiment_id"])}</code></p></div>'
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Arm</th><th>Primary</th><th>Delta</th><th>95% CI</th>"
            "<th>Duration</th><th>Peak memory</th><th>Gate</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
            f'<p class="fine-print">{_escape(resource_note)}</p></article>'
        )
    return "".join(groups)


def _seed_panel(paths: ControlledPaths, task: str) -> str:
    decision_path = paths.evaluation_root / "final" / task / "final_decision.json"
    receipt_path = (
        paths.evaluation_root / "final" / task / "sealed_evaluation_receipt.json"
    )
    decision = _optional_json(decision_path)
    if not decision:
        return _pending(
            f"{task.title()} 最终配置待确定",
            "入选配置尚未完成三个冻结随机种子的复验。",
        )
    seed_summary = decision["seed_summary"]
    seed_rows = "".join(
        f"<li><span>seed {item['seed']}</span><strong>{_pct(item['rate'])}</strong></li>"
        for item in seed_summary["seeds"]
    )
    configuration = " · ".join(
        f"{key}={value}" for key, value in decision["configuration"].items()
    )
    receipt = _optional_json(receipt_path)
    claim_path = receipt_path.with_name("sealed_evaluation_claim.json")
    sealed_valid = _sealed_requirement(paths, task)["passed"]
    if receipt and sealed_valid:
        sealed_html = (
            '<div class="sealed-state pass"><b>SEALED · OPENED ONCE</b>'
            f"<span>evaluation_count={receipt['evaluation_count']} · "
            f"delivery seed {decision['delivery_seed']}</span></div>"
        )
    elif receipt or claim_path.is_file():
        sealed_html = (
            '<div class="sealed-state pending"><b>SEALED · RECEIPT NOT VALIDATED</b>'
            "<span>A claim or receipt exists, but the single-use receipt, output hashes, "
            "and passing Sealed Gate have not all been verified.</span></div>"
        )
    else:
        sealed_html = (
            '<div class="sealed-state pending"><b>SEALED · NOT OPENED</b>'
            "<span>Waiting for the frozen development decision and reproducibility "
            "snapshot.</span></div>"
        )
    return (
        f'<article class="seed-card {"pass" if decision["passed"] else "fail"}">'
        f'<span class="track-label">{_escape(task)} · selected configuration</span>'
        f"<h3>{_escape(decision['experiment_id'])}</h3>"
        f'<p class="configuration">{_escape(configuration)}</p>'
        '<div class="seed-metrics">'
        f'<div><b>{_pct(seed_summary["mean"])}</b><span>mean</span></div>'
        f'<div><b>{_pct(seed_summary["std"])}</b><span>std</span></div>'
        f'<div><b>{_pct(seed_summary["min"])}</b><span>worst seed</span></div>'
        f'<div><b>{"PASS" if decision["passed"] else "FAIL"}</b><span>development Gate</span></div>'
        "</div>"
        f'<ul class="seed-list">{seed_rows}</ul>{sealed_html}</article>'
    )


def _context_table(paths: ControlledPaths) -> str:
    path = paths.evaluation_root / "t-context/results/context_study_index.json"
    value = _optional_json(path)
    if not value:
        return _pending(
            "Tutor 上下文实验待完成",
            "1/3/5/8 chunks、2k/4k/8k 输入 token 和 768/1024 输出预算条件尚未全部完成。",
        )
    rows = []
    for label, payload in sorted(value.items()):
        summary = payload.get("raw", payload)
        metrics = summary.get("metrics", {})
        runtime = summary.get("runtime", summary.get("generation", {}))
        rows.append(
            "<tr>"
            f"<td><strong>{_escape(label)}</strong></td>"
            f"<td>{_pct(metrics.get('strict_grounded_pass', {}).get('rate'))}</td>"
            f"<td>{_pct(metrics.get('citation_exact', {}).get('rate'))}</td>"
            f"<td>{_pct(metrics.get('no_answer_abstention', {}).get('rate'))}</td>"
            f"<td>{_number(runtime.get('seconds_per_record'), 4)} s</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Condition</th>'
        "<th>Strict pass</th><th>Citation exact</th><th>Abstention</th>"
        "<th>Latency / record</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _contract_summary(paths: ControlledPaths) -> str:
    audit_path = paths.contract_dir / "audit.json"
    audit = _optional_json(audit_path) or {}
    router = audit.get("router", {})
    tutor = audit.get("tutor", {})
    tokenization = audit.get("tokenization", {})
    review = _optional_json(
        paths.contract_dir / "human_review/challenge_review_receipt.json"
    ) or {}
    return f"""
<div class="contract-grid">
  <article><span>ROUTER CHALLENGE</span><b>{router.get('records', 'pending')}</b><p>12 balanced families; exact source-query overlap {router.get('exact_source_query_overlap', 'pending')}.</p></article>
  <article><span>TUTOR CHALLENGE</span><b>{tutor.get('records', 'pending')}</b><p>6 evidence-pressure families; train material overlap {len(tutor.get('train_material_overlap', []))}.</p></article>
  <article><span>INPUT BUDGET</span><b>4,096</b><p>Router prompt max {tokenization.get('router', {}).get('prompt', {}).get('max', 'pending')}; Tutor few-shot max {tokenization.get('tutor', {}).get('few_shot', {}).get('max', 'pending')}.</p></article>
  <article><span>HUMAN REVIEW</span><b>{'complete' if review.get('human_review_completed') else 'pending'}</b><p>{tutor.get('human_review_packet_records', 'pending')} challenge items prepared; teacher structural review is not reported as human review.</p></article>
</div>
"""


def _audit_board(audit: dict[str, Any]) -> str:
    cards = []
    for item in audit["requirements"]:
        cards.append(
            f'<div class="audit-item {"pass" if item["passed"] else "pending"}">'
            f'<span>{"PASS" if item["passed"] else "PENDING"}</span>'
            f"<b>{_escape(item['title'])}</b></div>"
        )
    return "".join(cards)


def _evidence_links(paths: ControlledPaths, sources: list[Path]) -> str:
    rows = []
    for path in sources:
        rows.append(
            "<li>"
            + _relative_link(paths, path, str(path.relative_to(paths.project_root)))
            + f"<code>{sha256_file(path) if path.is_file() else 'missing'}</code></li>"
        )
    return "".join(rows)


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="studyhub-report-schema" content="controlled_v2">
  <meta name="studyhub-contract-sha256" content="@@CONTRACT_SHA@@">
  <title>StudyHub Agent · SFT controlled_v2 实验报告</title>
  <script>document.documentElement.classList.add('js')</script>
  <style>
    :root { --ink:#13241d; --muted:#50625a; --paper:#f2eee2; --white:#fbf9f2; --green:#1e6b50; --mint:#4d9d78; --gold:#c8952d; --red:#a64b3e; --line:rgba(19,36,29,.16); --serif:"Source Han Serif SC","Noto Serif CJK SC","Songti SC",serif; --sans:"Avenir Next","PingFang SC","Microsoft YaHei",sans-serif; --mono:"SFMono-Regular","Cascadia Code",monospace; }
    *{box-sizing:border-box} html{scroll-behavior:smooth} body{margin:0;color:var(--ink);font:16px/1.7 var(--sans);background:radial-gradient(circle at 8% 0,rgba(200,149,45,.15),transparent 30rem),radial-gradient(circle at 92% 3%,rgba(30,107,80,.14),transparent 35rem),var(--paper)}
    body:before{content:"";position:fixed;inset:0;z-index:-1;opacity:.15;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='88' height='88'%3E%3Cpath d='M0 87.5h88M87.5 0v88' fill='none' stroke='%231e6b50' stroke-opacity='.12'/%3E%3C/svg%3E")}
    a{color:var(--green);text-decoration-color:var(--gold)} code{font:12px/1.5 var(--mono);overflow-wrap:anywhere}.shell{width:min(1380px,calc(100% - 48px));margin:auto}.progress{position:fixed;z-index:20;top:0;left:0;height:3px;width:0;background:var(--gold)}
    .hero{min-height:88vh;display:grid;align-content:center;padding:70px 0 45px}.hero-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:58px;align-items:end}.eyebrow,.kicker,.track-label{font:700 11px/1 var(--mono);letter-spacing:.15em;text-transform:uppercase;color:var(--green)}h1{margin:22px 0;font:700 clamp(64px,9vw,136px)/.86 var(--serif);letter-spacing:-.065em}h1 span{display:block;margin-top:.27em;color:var(--green);font-size:.43em;letter-spacing:-.03em}.lead{max-width:840px;font:500 clamp(21px,2.1vw,30px)/1.48 var(--serif)}
    .hero-card{padding:32px;background:var(--ink);color:#dbe6e0;border-radius:2px 28px 2px 2px}.hero-card span{font:700 10px/1 var(--mono);color:#91caac;letter-spacing:.13em}.hero-card b{display:block;margin:18px 0 10px;color:white;font:600 36px/1.1 var(--serif)}.hero-card p{margin:0;color:#b6c6bd}.metric-strip{display:grid;grid-template-columns:repeat(4,1fr);margin-top:58px;border-block:1px solid var(--line)}.metric-strip div{padding:22px;border-right:1px solid var(--line)}.metric-strip div:last-child{border:0}.metric-strip b{display:block;font:650 36px/1 var(--serif)}.metric-strip span{font-size:12px;color:var(--muted)}
    .layout{display:grid;grid-template-columns:205px minmax(0,1fr);gap:54px;padding-bottom:90px}nav{position:sticky;top:24px;padding:25px 0}nav b{font:700 10px/1 var(--mono);letter-spacing:.14em;color:var(--green)}nav a{display:block;padding:8px 0;color:var(--muted);font-size:13px;text-decoration:none}nav a:hover{color:var(--green)}main,article,td{min-width:0}section{padding:76px 0;border-top:1px solid var(--line)}.section-head{display:grid;grid-template-columns:.85fr 1.15fr;gap:42px;margin:15px 0 36px}.section-head h2{margin:0;font:650 clamp(38px,5vw,64px)/1.02 var(--serif);letter-spacing:-.04em}.section-head p{margin:6px 0;color:var(--muted);font-size:17px}
    .contract-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}.contract-grid article{padding:24px;background:var(--white)}.contract-grid span{font:700 10px/1 var(--mono);color:var(--green)}.contract-grid b{display:block;margin:13px 0 7px;font:650 30px/1 var(--serif)}.contract-grid p{margin:0;color:var(--muted);font-size:12px}
    .two{display:grid;grid-template-columns:1fr 1fr;gap:22px}.panel,.pending-card,.experiment-group,.seed-card{padding:28px;background:rgba(251,249,242,.88);border:1px solid var(--line)}.panel h3,.pending-card b{margin:0 0 12px;font:650 28px/1.15 var(--serif)}.pending-card{border-left:5px solid var(--gold)}.pending-card p{margin:8px 0;color:var(--muted)}
    .experiment-group{margin:0 0 20px}.group-head{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:20px}.group-head span{font:700 10px/1 var(--mono);color:var(--gold)}.group-head h3{margin:10px 0 0;font:650 28px/1.1 var(--serif)}.group-head p{margin:0;color:var(--muted);font-size:12px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;background:rgba(251,249,242,.82)}th,td{padding:13px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line);font-size:12px}th{font:700 10px/1 var(--mono);letter-spacing:.08em;color:var(--green);text-transform:uppercase}td small{display:block;margin-top:5px;color:var(--muted)}.anchor-row{background:rgba(30,107,80,.08)}.pill{display:inline-block;padding:5px 8px;font:700 9px/1 var(--mono);letter-spacing:.07em}.pill.pass{color:#155039;background:#d7e9df}.pill.warn{color:#7c4e13;background:#f1e3bd}.fine-print{margin:15px 0 0;color:var(--muted);font-size:11px}
    .seed-card.pass{border-top:5px solid var(--green)}.seed-card.fail{border-top:5px solid var(--red)}.seed-card h3{margin:16px 0 7px;font:650 28px/1.15 var(--serif);overflow-wrap:anywhere}.configuration{color:var(--muted);font:11px/1.7 var(--mono)}.seed-metrics{display:grid;grid-template-columns:repeat(4,1fr);margin:24px 0;border-block:1px solid var(--line)}.seed-metrics div{padding:16px 10px;border-right:1px solid var(--line)}.seed-metrics div:last-child{border:0}.seed-metrics b{display:block;font:650 25px/1 var(--serif)}.seed-metrics span{font-size:10px;color:var(--muted)}.seed-list{list-style:none;padding:0;margin:0}.seed-list li{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line);font:12px var(--mono)}.sealed-state{display:flex;justify-content:space-between;gap:20px;margin-top:20px;padding:14px;font:10px/1.5 var(--mono)}.sealed-state.pass{background:#d7e9df;color:#155039}.sealed-state.pending{background:#f1e3bd;color:#7c4e13}
    .audit-board{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}.audit-item{display:grid;grid-template-columns:80px 1fr;gap:14px;padding:15px;background:var(--white)}.audit-item span{font:700 9px/1.5 var(--mono)}.audit-item.pass span{color:var(--green)}.audit-item.pending span{color:var(--gold)}.audit-item b{font-size:12px}.evidence{list-style:none;padding:0;margin:0}.evidence li{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:20px;padding:12px 0;border-bottom:1px solid var(--line);font-size:12px}.evidence code{color:var(--muted)}footer{padding:35px 0 65px;border-top:1px solid var(--line);font:11px var(--mono);color:var(--muted)}
    .js .reveal{opacity:0;transform:translateY(14px);transition:.5s ease}.js .reveal.visible{opacity:1;transform:none}@media(prefers-reduced-motion:reduce){.js .reveal{opacity:1;transform:none;transition:none}}@media(max-width:980px){.hero-grid,.section-head,.two{grid-template-columns:1fr}.layout{grid-template-columns:1fr}nav{display:none}.contract-grid,.metric-strip{grid-template-columns:1fr 1fr}.seed-metrics{grid-template-columns:1fr 1fr}.audit-board{grid-template-columns:1fr}}@media(max-width:620px){.shell{width:calc(100% - 26px)}h1{font-size:58px}.contract-grid,.metric-strip,.seed-metrics{grid-template-columns:1fr}.group-head,.sealed-state{display:block}.evidence li{grid-template-columns:1fr}.audit-item{grid-template-columns:70px 1fr}}@media print{body{background:white}body:before,.progress,nav{display:none}.layout{display:block}.hero{min-height:auto;page-break-after:always}.js .reveal{opacity:1;transform:none}}
  </style>
</head>
<body>
<div class="progress"></div>
<header class="hero shell"><div class="hero-grid"><div><div class="eyebrow">StudyHub Agent · SFT controlled_v2</div><h1>SFT<span>对照、消融与封存评测</span></h1><p class="lead">在同一冻结合同下比较 Base、Prompt、Few-shot、SFT、优化参数、LoRA 配置、数据配比和随机种子差异。</p></div><aside class="hero-card"><span>CONTROLLED_V2 · @@GENERATED_AT@@</span><b>@@AUDIT_STATE@@</b><p>所有统计仅来自 controlled_v2 产物，缺失实验保持 pending 状态。</p></aside></div><div class="metric-strip"><div><b>@@AUDIT_SCORE@@</b><span>pre-report requirements</span></div><div><b>300</b><span>Router challenge records</span></div><div><b>240</b><span>Tutor challenge records</span></div><div><b>3 + 3</b><span>final random seeds</span></div></div></header>
<div class="shell layout"><nav><b>REPORT INDEX</b><a href="#contract">01 Contract</a><a href="#baselines">02 Baselines</a><a href="#router">03 Router</a><a href="#tutor">04 Tutor</a><a href="#context">05 Context</a><a href="#final">06 Seeds & sealed</a><a href="#audit">07 Audit</a><a href="#evidence">08 Evidence</a></nav><main>
<section id="contract" class="reveal"><div class="kicker">01 / frozen contract</div><div class="section-head"><h2>冻结评测合同</h2><p>Challenge、prompt、解码、Gate 和一次性封存策略在候选选择前冻结。训练环境不连接生产数据库、生产 API 或付费资料。</p></div>@@CONTRACT_SUMMARY@@</section>
<section id="baselines" class="reveal"><div class="kicker">02 / paired baselines</div><div class="section-head"><h2>Base、Prompt、Few-shot<br>与 SFT 对照</h2><p>四个条件使用完全相同的 challenge 输入，逐样本执行 10,000 次 paired bootstrap 和 McNemar exact test。</p></div><div class="two"><article class="panel"><h3>Router 2B</h3>@@ROUTER_BASELINES@@</article><article class="panel"><h3>Grounded Tutor 9B</h3>@@TUTOR_BASELINES@@</article></div></section>
<section id="router" class="reveal"><div class="kicker">03 / router controlled study</div><div class="section-head"><h2>Router 参数与<br>数据消融</h2><p>依次筛选 LR、训练长度、scheduler 与 LoRA，并在等优化步数条件下比较数据规模、replay 和状态表示。</p></div>@@ROUTER_ABLATIONS@@</section>
<section id="tutor" class="reveal"><div class="kicker">04 / grounded tutor study</div><div class="section-head"><h2>Grounded Tutor<br>边界证据实验</h2><p>在正常、无答案、干扰、冲突、部分证据和反事实引用六类条件下比较 LR、rank 与负证据配比。</p></div>@@TUTOR_ABLATIONS@@</section>
<section id="context" class="reveal"><div class="kicker">05 / context pressure</div><div class="section-head"><h2>上下文长度与<br>证据密度</h2><p>对同一问题改变 chunk 数、输入 token 桶和输出预算，分别报告严格通过率、引用、拒答与延迟。</p></div>@@CONTEXT_TABLE@@</section>
<section id="final" class="reveal"><div class="kicker">06 / multi-seed and sealed</div><div class="section-head"><h2>多随机种子与<br>封存评测</h2><p>入选配置锁定后运行三个 seed，并以开发主指标居中的 seed 作为交付 checkpoint；封存集仅评测一次。</p></div><div class="two">@@ROUTER_FINAL@@@@TUTOR_FINAL@@</div></section>
<section id="audit" class="reveal"><div class="kicker">07 / completion audit</div><div class="section-head"><h2>完成条件审计</h2><p>审计人工复核、基线、训练臂、统计、资源、多随机种子和封存回执，并逐项记录完成状态。</p></div><div class="audit-board">@@AUDIT_BOARD@@</div></section>
<section id="evidence" class="reveal"><div class="kicker">08 / provenance</div><div class="section-head"><h2>实验产物与<br>哈希索引</h2><p>模型权重保留在本地忽略目录；报告引用冻结合同、逐样本预测汇总、Gate、统计与单次封存回执。</p></div><ul class="evidence">@@EVIDENCE@@</ul></section>
</main></div><footer><div class="shell">StudyHub Agent · SFT controlled_v2 · contract @@CONTRACT_SHA@@</div></footer>
<script>const p=document.querySelector('.progress');const r=[...document.querySelectorAll('.reveal')];const o=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.06});r.forEach(x=>o.observe(x));addEventListener('scroll',()=>{const m=document.documentElement.scrollHeight-innerHeight;p.style.width=`${m>0?scrollY/m*100:0}%`},{passive:true});</script>
</body></html>"""


def build_report(
    output: Path = DEFAULT_OUTPUT,
    *,
    allow_incomplete: bool = False,
    write_manifest: bool = True,
    paths: ControlledPaths | None = None,
) -> Path:
    paths = paths or ControlledPaths()
    audit = audit_completion(paths=paths, include_report=False)
    if not audit["passed"] and not allow_incomplete:
        missing = ", ".join(audit["requirements_failed"])
        raise RuntimeError(f"controlled-v2 report is not complete: {missing}")

    sources = [
        paths.pre_registration,
        paths.experiment_registry,
        paths.contract_dir / "audit.json",
        paths.evaluation_root / "baselines/router/baseline_index.json",
        paths.evaluation_root / "baselines/tutor/baseline_index.json",
        paths.evaluation_root / "ablation/router/ablation_index.json",
        paths.evaluation_root / "ablation/tutor/ablation_index.json",
        paths.evaluation_root / "t-context/results/context_study_index.json",
        paths.evaluation_root / "final/router/final_decision.json",
        paths.evaluation_root / "final/tutor/final_decision.json",
        paths.evaluation_root / "final/router/sealed_evaluation_receipt.json",
        paths.evaluation_root / "final/tutor/sealed_evaluation_receipt.json",
        paths.evaluation_root / "final/human_review_receipt.json",
        paths.contract_dir / "human_review/challenge_review_receipt.json",
        paths.evaluation_root / "final/completion_audit.json",
    ]
    replacements = {
        "CONTRACT_SHA": contract_sha256(),
        "GENERATED_AT": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "AUDIT_STATE": "15 项完成条件已通过" if audit["passed"] else "实验尚未完成",
        "AUDIT_SCORE": f"{audit['requirements_passed']} / {audit['requirements_total']}",
        "CONTRACT_SUMMARY": _contract_summary(paths),
        "ROUTER_BASELINES": _baseline_table(paths, "router"),
        "TUTOR_BASELINES": _baseline_table(paths, "tutor"),
        "ROUTER_ABLATIONS": _ablation_groups(paths, "router"),
        "TUTOR_ABLATIONS": _ablation_groups(paths, "tutor"),
        "CONTEXT_TABLE": _context_table(paths),
        "ROUTER_FINAL": _seed_panel(paths, "router"),
        "TUTOR_FINAL": _seed_panel(paths, "tutor"),
        "AUDIT_BOARD": _audit_board(audit),
        "EVIDENCE": _evidence_links(paths, sources),
    }
    rendered = HTML_TEMPLATE
    for key, value in replacements.items():
        rendered = rendered.replace(f"@@{key}@@", value)
    if "@@" in rendered:
        raise ValueError("unresolved report template placeholder")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")

    if write_manifest:
        if not audit["passed"]:
            raise RuntimeError("cannot write a canonical report manifest for an incomplete run")
        missing_sources = [str(path) for path in sources if not path.is_file()]
        if missing_sources:
            raise FileNotFoundError(f"report evidence is missing: {missing_sources}")
        manifest = {
            "schema_version": "studyhub.agent.sft.controlled_v2.report_manifest.v1",
            "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "generated_from_controlled_v2_only": True,
            "contract_sha256": contract_sha256(),
            "report_path": str(output),
            "report_sha256": sha256_file(output),
            "pre_report_completion_audit_passed": True,
            "sources": [
                {"path": str(path), "sha256": sha256_file(path)} for path in sources
            ],
        }
        manifest_path = paths.evaluation_root / "final/completion_report_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--no-manifest", action="store_true")
    args = parser.parse_args()
    output = build_report(
        args.output,
        allow_incomplete=args.allow_incomplete,
        write_manifest=not args.no_manifest,
    )
    print(output)


if __name__ == "__main__":
    main()
