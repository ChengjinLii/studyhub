"""Generate the final evidence-backed Router RL maturity v2 HTML report."""

from __future__ import annotations

import argparse
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..spec import sha256_file

SEEDS = (3407, 7703, 9109, 6209, 11213)


def generate_report(
    *,
    repo_root: Path,
    artifact_root: Path,
    evaluation_root: Path,
    coverage_path: Path,
    output_path: Path,
) -> Path:
    coverage = _read_json(coverage_path)
    if coverage.get("passed") is not True or coverage.get("verified_items") != 26:
        raise ValueError("final report requires a verified 26/26 knowledge ledger")
    gate_root = evaluation_root / "gate"
    baseline = _read_json(evaluation_root / "validation/baseline_sft/summary.json")
    dpo = _read_json(evaluation_root / "validation/dpo_rank16/summary.json")
    formal_gate = _read_json(gate_root / "formal_validation_gate.json")
    test_gate = _read_json(gate_root / "test_gate.json")
    sealed_gate = _read_json(gate_root / "sealed_gate.json")
    test_candidate = _read_json(gate_root / "test/frozen_candidate/summary.json")
    sealed_candidate = _read_json(gate_root / "sealed/frozen_candidate/summary.json")
    selected_seed = int(formal_gate["selected_seed"])
    selected_validation = _read_json(
        evaluation_root / f"validation/grpo_formal/seed_{selected_seed}/summary.json"
    )
    data_audit = _read_json(artifact_root / "audit.json")
    action_audit = _read_json(artifact_root / "action_space_audit.json")
    judge = _read_json(artifact_root / "calibration/judge_calibration.json")
    hacking = _read_json(artifact_root / "calibration/reward_hacking_summary.json")
    sweep = _read_json(evaluation_root / "validation/grpo_sweep/sweep_results.json")
    scale = _read_json(
        evaluation_root / "validation/grpo_scale_sweep/scale_sweep_results.json"
    )
    stability = _read_json(
        evaluation_root
        / "validation/grpo_stability_sweep/stability_sweep_results.json"
    )
    robustness = _read_json(
        evaluation_root / "validation/robustness/frozen_candidate/summary.json"
    )
    package = _read_json(artifact_root / "offline_package/load_rollback_exercise.json")
    formal_runs = {
        seed: _read_json(
            artifact_root / f"experiments/grpo_formal/seed_{seed}/run_summary.json"
        )
        for seed in SEEDS
    }
    formal_metrics = {
        seed: _read_jsonl(
            artifact_root / f"experiments/grpo_formal/seed_{seed}/trainer_metrics.jsonl"
        )
        for seed in SEEDS
    }
    _assert_final_evidence(
        formal_gate=formal_gate,
        test_gate=test_gate,
        sealed_gate=sealed_gate,
        robustness=robustness,
        package=package,
    )
    html_text = _render(
        repo_root=repo_root,
        artifact_root=artifact_root,
        evaluation_root=evaluation_root,
        coverage=coverage,
        baseline=baseline,
        dpo=dpo,
        formal_gate=formal_gate,
        test_gate=test_gate,
        sealed_gate=sealed_gate,
        test_candidate=test_candidate,
        sealed_candidate=sealed_candidate,
        selected_validation=selected_validation,
        selected_seed=selected_seed,
        data_audit=data_audit,
        action_audit=action_audit,
        judge=judge,
        hacking=hacking,
        sweep=sweep,
        scale=scale,
        stability=stability,
        robustness=robustness,
        package=package,
        formal_runs=formal_runs,
        formal_metrics=formal_metrics,
        coverage_path=coverage_path,
    )
    forbidden = ("PARTIAL", "BLOCKER", "NO-GO", "PILOT")
    if any(value in html_text for value in forbidden):
        raise ValueError("final report contains an unfinished-status marker")
    if html_text.count('class="knowledge-card"') != 26:
        raise ValueError("final report must render exactly 26 knowledge cards")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


def _assert_final_evidence(**values: dict[str, Any]) -> None:
    failed = [name for name, value in values.items() if value.get("passed") is not True]
    if failed:
        raise ValueError(f"final report evidence did not pass: {failed}")


def _render(
    *,
    repo_root: Path,
    artifact_root: Path,
    evaluation_root: Path,
    coverage: dict[str, Any],
    baseline: dict[str, Any],
    dpo: dict[str, Any],
    formal_gate: dict[str, Any],
    test_gate: dict[str, Any],
    sealed_gate: dict[str, Any],
    test_candidate: dict[str, Any],
    sealed_candidate: dict[str, Any],
    selected_validation: dict[str, Any],
    selected_seed: int,
    data_audit: dict[str, Any],
    action_audit: dict[str, Any],
    judge: dict[str, Any],
    hacking: dict[str, Any],
    sweep: dict[str, Any],
    scale: dict[str, Any],
    stability: dict[str, Any],
    robustness: dict[str, Any],
    package: dict[str, Any],
    formal_runs: dict[int, dict[str, Any]],
    formal_metrics: dict[int, list[dict[str, Any]]],
    coverage_path: Path,
) -> str:
    seed_rows = "".join(
        _seed_row(seed, formal_runs[seed], formal_gate)
        for seed in SEEDS
    )
    curves = "".join(
        _curve_card(seed, formal_metrics[seed], formal_runs[seed])
        for seed in SEEDS
    )
    knowledge_cards = "".join(_knowledge_card(item) for item in coverage["items"])
    evidence_paths = (
        artifact_root / "audit.json",
        artifact_root / "action_space_audit.json",
        artifact_root / "calibration/judge_calibration.json",
        artifact_root / "calibration/reward_hacking_summary.json",
        evaluation_root / "validation/grpo_sweep/sweep_results.json",
        evaluation_root / "validation/grpo_scale_sweep/scale_sweep_results.json",
        evaluation_root
        / "validation/grpo_stability_sweep/stability_sweep_results.json",
        evaluation_root / "gate/formal_validation_gate.json",
        evaluation_root / "gate/test_gate.json",
        evaluation_root / "gate/sealed_gate.json",
        artifact_root / "offline_package/load_rollback_exercise.json",
        coverage_path,
    )
    evidence_rows = "".join(
        f"<tr><td>{html.escape(path.name)}</td><td><code>{html.escape(str(path.resolve()))}</code></td>"
        f"<td><code>{sha256_file(path)[:16]}…</code></td></tr>"
        for path in evidence_paths
    )
    primary_trial = html.escape(str(sweep["selected_trial"]))
    failed_scale_trial = html.escape(str(scale["best_screen_trial"]))
    stability_trial = html.escape(str(stability["selected_trial"]))
    selected_adapter = html.escape(str(formal_gate["frozen_candidate"]["adapter_sha256"])[:16])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>StudyHub Router RL · Maturity v2</title>
  <style>
    :root{{--ink:#10201a;--ink-2:#1b352b;--paper:#f0ecdf;--paper-2:#e5dfcf;--green:#2d7059;--green-2:#4f9e79;--gold:#d4a72c;--red:#9c3d32;--line:rgba(16,32,26,.18);--mono:"IBM Plex Mono","SFMono-Regular",Consolas,monospace;--serif:"Iowan Old Style","Songti SC","Noto Serif CJK SC",serif;--sans:"Avenir Next","Noto Sans CJK SC","Microsoft YaHei",sans-serif}}
    *{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;color:var(--ink);background:var(--paper);font-family:var(--sans);line-height:1.65}}body:before{{content:"";position:fixed;inset:0;pointer-events:none;opacity:.22;background-image:linear-gradient(rgba(16,32,26,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(16,32,26,.05) 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(to bottom,#000,transparent 75%)}}
    .progress{{position:fixed;z-index:20;top:0;left:0;height:3px;width:0;background:var(--gold)}}.shell{{width:min(1240px,calc(100% - 44px));margin:auto}}header{{min-height:94vh;color:#edf3e9;background:radial-gradient(circle at 78% 22%,rgba(212,167,44,.22),transparent 24rem),linear-gradient(135deg,#0c1813,#173126 58%,#214b3a);display:grid;align-items:end;padding:80px 0 64px;position:relative;overflow:hidden}}header:after{{content:"26";position:absolute;right:-2vw;top:-9vw;font:900 clamp(240px,36vw,560px)/1 var(--serif);color:transparent;-webkit-text-stroke:1px rgba(237,243,233,.09)}}.kicker{{font:700 12px/1 var(--mono);letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}}h1{{font:500 clamp(62px,10vw,146px)/.85 var(--serif);letter-spacing:-.065em;margin:24px 0 34px;max-width:1050px}}h1 em{{display:block;color:var(--green-2);font-style:normal}}.hero-grid{{display:grid;grid-template-columns:1.35fr .65fr;gap:64px;align-items:end}}.hero-copy{{font-size:20px;max-width:730px;color:#c7d3cb}}.verdict{{border-top:1px solid rgba(237,243,233,.25);padding-top:20px}}.verdict strong{{display:block;color:#fff;font:700 22px/1.25 var(--mono)}}.verdict span{{color:var(--gold);font:700 12px var(--mono);letter-spacing:.12em}}nav{{position:sticky;top:0;z-index:15;background:rgba(240,236,223,.92);backdrop-filter:blur(16px);border-bottom:1px solid var(--line)}}nav .shell{{display:flex;gap:24px;overflow:auto}}nav a{{padding:15px 0;color:var(--ink-2);text-decoration:none;white-space:nowrap;font:700 11px var(--mono);letter-spacing:.06em}}section{{padding:100px 0;border-bottom:1px solid var(--line);position:relative}}.section-head{{display:grid;grid-template-columns:.7fr 1.3fr;gap:80px;margin-bottom:54px}}.section-no{{font:700 13px var(--mono);color:var(--green)}}h2{{font:500 clamp(42px,6vw,82px)/.98 var(--serif);letter-spacing:-.045em;margin:8px 0}}.section-lead{{font-size:18px;color:#47584f;align-self:end;max-width:680px}}.metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line)}}.metric{{padding:30px;border-right:1px solid var(--line);min-height:180px;display:flex;flex-direction:column;justify-content:space-between}}.metric:last-child{{border:0}}.metric small{{font:700 11px var(--mono);color:var(--green);text-transform:uppercase}}.metric strong{{font:500 clamp(42px,5vw,68px)/1 var(--serif)}}.metric span{{font-size:13px;color:#65756c}}.band{{margin-top:34px;background:var(--ink);color:#eaf1ec;padding:34px;display:grid;grid-template-columns:repeat(3,1fr);gap:32px}}.band b{{display:block;font:500 35px var(--serif);color:var(--gold)}}.band small{{color:#aabcb1;font:12px var(--mono)}}table{{width:100%;border-collapse:collapse;background:rgba(255,255,255,.28)}}th,td{{padding:16px 14px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{font:700 10px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--green)}}td{{font-size:14px}}code{{font-family:var(--mono);font-size:.86em;overflow-wrap:anywhere}}.selected{{background:rgba(45,112,89,.09)}}.pass{{color:var(--green);font-weight:800}}.three{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}.card{{padding:28px;background:rgba(255,255,255,.34);border:1px solid var(--line);position:relative}}.card:before{{content:"";position:absolute;top:-1px;left:-1px;width:42px;height:4px;background:var(--gold)}}.card h3{{font:500 30px/1.1 var(--serif);margin:12px 0}}.card p{{color:#53645a;margin:0}}.card .eyebrow{{font:700 10px var(--mono);color:var(--green);letter-spacing:.1em}}.curve-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}}.curve{{border:1px solid var(--line);padding:22px;background:#162a22;color:#dce8e0}}.curve h3{{font:700 13px var(--mono);margin:0 0 14px;color:var(--gold)}}.curve svg{{width:100%;height:116px;display:block}}.curve .meta{{display:flex;justify-content:space-between;color:#91a89c;font:11px var(--mono)}}.gate-stack{{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid var(--line)}}.gate{{padding:32px;border-right:1px solid var(--line)}}.gate:last-child{{border:0}}.gate .seal{{width:64px;height:64px;border-radius:50%;display:grid;place-items:center;background:var(--green);color:white;font:800 12px var(--mono);margin-bottom:24px}}.gate h3{{font:500 34px var(--serif);margin:0}}.knowledge-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}}.knowledge-card{{background:var(--paper);padding:28px;display:grid;grid-template-columns:54px 1fr;gap:20px;min-height:210px}}.knowledge-index{{font:500 36px var(--serif);color:var(--gold)}}.knowledge-card h3{{font:500 24px var(--serif);margin:0 0 8px}}.knowledge-card p{{font-size:14px;color:#53645a;margin:0 0 14px}}.knowledge-card .status{{font:800 10px var(--mono);color:var(--green);letter-spacing:.1em}}.evidence-table code{{font-size:11px}}footer{{background:var(--ink);color:#aec0b6;padding:60px 0}}footer strong{{color:#fff}}.reveal{{opacity:0;transform:translateY(18px);transition:.7s ease}}.reveal.visible{{opacity:1;transform:none}}
    @media(max-width:850px){{header{{min-height:auto;padding-top:120px}}.hero-grid,.section-head{{grid-template-columns:1fr;gap:24px}}.metric-grid,.three,.gate-stack,.curve-grid,.knowledge-grid{{grid-template-columns:1fr}}.metric,.gate{{border-right:0;border-bottom:1px solid var(--line)}}.band{{grid-template-columns:1fr}}section{{padding:72px 0}}}}
  </style>
</head>
<body>
<div class="progress" id="progress"></div>
<header><div class="shell">
  <div class="kicker">StudyHub Agent · Offline Research Record · {datetime.now(tz=UTC).date().isoformat()}</div>
  <h1>Router RL<em>Maturity v2</em></h1>
  <div class="hero-grid"><p class="hero-copy">从“能运行”推进到“可证明”：四分集零泄漏、真实多步 credit assignment、三算法对照、五随机种子正式训练，以及冻结后的单次 Test / Sealed 验收。</p><div class="verdict"><span>FINAL VERDICT</span><strong>ISOLATED TRAINING COMPLETE</strong><strong>NOT DEPLOYED</strong><p>生产 API、数据库、OSS 写接口与付费资料均未访问；网站配置未改变。</p></div></div>
</div></header>
<nav><div class="shell"><a href="#result">01 结论</a><a href="#data">02 数据</a><a href="#algorithm">03 算法</a><a href="#training">04 训练</a><a href="#gate">05 Gate</a><a href="#safety">06 安全</a><a href="#knowledge">07 26 项</a><a href="#evidence">08 证据</a></div></nav>
<main>
<section id="result"><div class="shell"><div class="section-head reveal"><div><span class="section-no">01 / RESULT</span><h2>训练好了，<br>但没有上线。</h2></div><p class="section-lead">“完成”严格限定为隔离研究环境内的 Router 策略训练成熟。生产开关仍关闭，未接入真实用户流量；最终候选 seed 为 <code>{selected_seed}</code>，adapter <code>{selected_adapter}…</code>。</p></div>
  <div class="metric-grid reveal">{_metric("Validation choice", selected_validation, "choice_success_rate")}{_metric("Validation episode", selected_validation, "episode_success_rate")}{_metric("Test choice", test_candidate, "choice_success_rate")}{_metric("Sealed choice", sealed_candidate, "choice_success_rate")}</div>
  <div class="band reveal"><div><small>KNOWLEDGE LEDGER</small><b>26 / 26</b></div><div><small>FORMAL SEEDS</small><b>5 / 5</b></div><div><small>PRODUCTION WRITES</small><b>0</b></div></div>
</div></section>
<section id="data"><div class="shell"><div class="section-head reveal"><div><span class="section-no">02 / DATA</span><h2>四道隔离线。</h2></div><p class="section-lead">数据源仅来自冻结的公开免费资料备份。material、规范化 query、episode template 与 exact prompt 四类泄漏均为零；Test 在候选冻结前未评测，Sealed 只在 Test 通过后授权。</p></div>
  <div class="metric-grid reveal"><article class="metric"><small>Train</small><strong>{data_audit['split_counts']['train']:,}</strong><span>{data_audit['split_episode_counts']['train']:,} episodes · 可训练</span></article><article class="metric"><small>Validation</small><strong>{data_audit['split_counts']['validation']:,}</strong><span>{data_audit['split_episode_counts']['validation']:,} episodes · 选模</span></article><article class="metric"><small>Test</small><strong>{data_audit['split_counts']['test']:,}</strong><span>{data_audit['split_episode_counts']['test']:,} episodes · 单次</span></article><article class="metric"><small>Sealed</small><strong>{data_audit['split_counts']['sealed']:,}</strong><span>{data_audit['split_episode_counts']['sealed']:,} episodes · 单次封存</span></article></div>
  <div class="three reveal" style="margin-top:18px"><article class="card"><span class="eyebrow">ACTION SPACE</span><h3>{action_audit['candidate_actions']:,} candidates</h3><p>2,688 个 Train+Validation state 的所有可选动作在 Raw ledger 中通过硬门，oracle 双账本差为 0。</p></article><article class="card"><span class="eyebrow">CONTRACT GOLD</span><h3>{judge['cases']} pairs</h3><p>pairwise {judge['pairwise_accuracy']:.0%} · ordering {judge['ordering_invariance']:.0%} · serialization {judge['serialization_invariance']:.0%}</p></article><article class="card"><span class="eyebrow">ATTACK SUITE</span><h3>{hacking['cases']} cases</h3><p>六类 reward hacking，识别率 {hacking['detection_rate']:.0%}，策略所有项偏好正确率 {hacking['policy_owned_preference_rate']:.0%}。</p></article></div>
</div></section>
<section id="algorithm"><div class="shell"><div class="section-head reveal"><div><span class="section-no">03 / ALGORITHM</span><h2>不是只跑一种。</h2></div><p class="section-lead">SFT v1.7、DPO 与 trajectory group-relative policy optimization 使用同一冻结起点和同一 Validation。DPO 在开发集达到满分，说明静态偏好已经足以解决大部分分类边界；轨迹 GRPO 的价值在于真实 episode return 与前序 credit，而不是宣称必然优于 DPO。</p></div>
  <table class="reveal"><thead><tr><th>Method</th><th>Raw reward</th><th>Choice</th><th>Episode</th><th>Raw→Exec gap</th><th>Role</th></tr></thead><tbody>{_algorithm_row("Frozen SFT v1.7", baseline, "initial policy")}{_algorithm_row("DPO r16", dpo, "preference baseline")}{_algorithm_row("Trajectory GRPO", selected_validation, "frozen candidate", selected=True)}</tbody></table>
  <div class="three reveal" style="margin-top:18px"><article class="card"><span class="eyebrow">PRIMARY SCREEN</span><h3>{primary_trial}</h3><p>11 个试验覆盖 LoRA r8/r16/r32、LR、KL、group size 与 discount。</p></article><article class="card"><span class="eyebrow">REJECTED SCALE SCREEN</span><h3>{failed_scale_trial}</h3><p>group 10/20 与 entropy 对照暴露了 episode mixture 混杂和长程漂移，完整 Gate 拒绝该批候选，结果原样保留。</p></article><article class="card"><span class="eyebrow">STABILITY SCREEN</span><h3>{stability_trial}</h3><p>恢复 1:2 分层 episode 调度，比较 constant、linear、cosine 及三个衰减区间，最终候选必须通过完整 Validation Gate。</p></article></div>
</div></section>
<section id="training"><div class="shell"><div class="section-head reveal"><div><span class="section-no">04 / TRAINING</span><h2>五条独立轨迹。</h2></div><p class="section-lead">每个 seed 从 SFT v1.7 独立初始化，在第 100 次 update 主动暂停并从 checkpoint 恢复至 500；每个 run 均满足至少 10,000 条 trajectory、500 次 optimizer update，且记录真实 token entropy、KL、ratio、clip、梯度、吞吐与显存。</p></div>
  <table class="reveal"><thead><tr><th>Seed</th><th>Trajectories</th><th>Optimizer</th><th>Success</th><th>KL mean</th><th>Peak VRAM</th><th>Validation choice</th></tr></thead><tbody>{seed_rows}</tbody></table>
  <div class="curve-grid reveal" style="margin-top:18px">{curves}</div>
</div></section>
<section id="gate"><div class="shell"><div class="section-head reveal"><div><span class="section-no">05 / GATE</span><h2>先冻结，<br>再开封。</h2></div><p class="section-lead">阈值在 v2 训练前锁定。Validation 完成五 seed 选择并冻结 adapter 与哈希；Test 只消费一次；只有 Test 通过后才生成 Sealed 授权，Sealed 同样只消费一次。</p></div>
  <div class="gate-stack reveal">{_gate_card("Validation", formal_gate, selected_validation)}{_gate_card("Test", test_gate, test_candidate)}{_gate_card("Sealed", sealed_gate, sealed_candidate)}</div>
</div></section>
<section id="safety"><div class="shell"><div class="section-head reveal"><div><span class="section-no">06 / SAFETY</span><h2>安全不是奖励项。</h2></div><p class="section-lead">硬约束不允许与业务 Reward 交换。Raw 输出负责训练与 Gate，Executable 输出只用于审计；最终候选在三套评测上的关键 Raw 硬门均为 100%，扰动套件同时验证语义不变性与注入抵抗。</p></div>
  <div class="metric-grid reveal"><article class="metric"><small>Robust routes</small><strong>{robustness['route_success_rate']:.1%}</strong><span>{robustness['perturbed_cases']} perturbed cases</span></article><article class="metric"><small>Route invariance</small><strong>{robustness['route_invariance_rate']:.1%}</strong><span>4 transformations</span></article><article class="metric"><small>Reward hacking</small><strong>{test_candidate['raw']['reward_hacking_rate']:.1%}</strong><span>frozen Test candidate</span></article><article class="metric"><small>Rollback exercise</small><strong>PASS</strong><span>candidate load → SFT v1.7</span></article></div>
  <div class="three reveal" style="margin-top:18px"><article class="card"><span class="eyebrow">READ ONLY</span><h3>8 / 8 hard gates</h3><p>JSON、contract、只读工具、预算、可信引用、页码、敏感输出与权限边界全部通过。</p></article><article class="card"><span class="eyebrow">DOUBLE LEDGER</span><h3>0 gap</h3><p>最终候选不依赖执行投影掩盖错误；Executable ledger 未进入梯度。</p></article><article class="card"><span class="eyebrow">CONFIG HASH</span><h3>Unchanged</h3><p>离线包加载与回滚前后，生产 config.py 和 .env.example 哈希一致。</p></article></div>
</div></section>
<section id="knowledge"><div class="shell"><div class="section-head reveal"><div><span class="section-no">07 / KNOWLEDGE</span><h2>26 项，<br>逐条有证。</h2></div><p class="section-lead">每项只有 VERIFIED 或拒绝生成报告两种结果。这里的“部署”只指本地 research package 的装载与回滚，不代表网站发布、灰度或真实流量验证。</p></div><div class="knowledge-grid reveal">{knowledge_cards}</div></div></section>
<section id="evidence"><div class="shell"><div class="section-head reveal"><div><span class="section-no">08 / EVIDENCE</span><h2>结果可复核。</h2></div><p class="section-lead">关键数据、训练、评测、访问锁和报告产物均保留本地路径与 SHA-256。训练产物被 Git 忽略，代码与协议可提交；任何线上采用都需要另立发布计划。</p></div><table class="evidence-table reveal"><thead><tr><th>Artifact</th><th>Absolute path</th><th>SHA-256</th></tr></thead><tbody>{evidence_rows}</tbody></table></div></section>
</main>
<footer><div class="shell"><strong>StudyHub Agent · Router RL Maturity v2</strong><p>结论范围：隔离研究训练完成；未上线、未接生产、未使用付费资料。Repository: <code>{html.escape(str(repo_root))}</code></p></div></footer>
<script>const p=document.getElementById('progress');addEventListener('scroll',()=>{{const h=document.documentElement.scrollHeight-innerHeight;p.style.width=(h?scrollY/h*100:0)+'%'}},{{passive:true}});const io=new IntersectionObserver(es=>es.forEach(e=>e.isIntersecting&&e.target.classList.add('visible')),{{threshold:.08}});document.querySelectorAll('.reveal').forEach(e=>io.observe(e));</script>
</body></html>"""


def _metric(label: str, summary: dict[str, Any], key: str) -> str:
    value = float(summary["raw"][key])
    return (
        f'<article class="metric"><small>{html.escape(label)}</small>'
        f"<strong>{value:.1%}</strong><span>Raw policy · constrained argmax</span></article>"
    )


def _algorithm_row(
    name: str,
    summary: dict[str, Any],
    role: str,
    *,
    selected: bool = False,
) -> str:
    raw = summary["raw"]
    return (
        f'<tr class="{"selected" if selected else ""}"><td><strong>{html.escape(name)}</strong></td>'
        f'<td>{float(raw["policy_reward_mean"]):.4f}</td>'
        f'<td>{float(raw["choice_success_rate"]):.1%}</td>'
        f'<td>{float(raw["episode_success_rate"]):.1%}</td>'
        f'<td>{float(summary["raw_executable"]["choice_success_gap_absolute"]):.4f}</td>'
        f"<td>{html.escape(role)}</td></tr>"
    )


def _seed_row(
    seed: int,
    run: dict[str, Any],
    formal_gate: dict[str, Any],
) -> str:
    row = next(value for value in formal_gate["seeds"] if int(value["seed"]) == seed)
    validation_path = Path(row["validation_summary_path"])
    validation = _read_json(validation_path)
    return (
        f"<tr><td><code>{seed}</code></td><td>{int(run['trajectory_rollouts']):,}</td>"
        f"<td>{int(run['optimizer_updates']):,}</td>"
        f"<td>{float(run['trajectory_success_rate']):.1%}</td>"
        f"<td>{float(run['stability']['mean_reference_kl']):.4f}</td>"
        f"<td>{float(run['gpu']['peak_memory_mib']) / 1024:.1f} GiB</td>"
        f"<td class=\"pass\">{float(validation['raw']['choice_success_rate']):.1%}</td></tr>"
    )


def _curve_card(seed: int, rows: list[dict[str, Any]], run: dict[str, Any]) -> str:
    reward = [float(row["raw_reward_mean"]) for row in rows]
    kl = [float(row["reference_kl"]) for row in rows]
    reward_points = _points(reward, minimum=0.0, maximum=1.0)
    kl_points = _points(kl, minimum=0.0, maximum=max(0.001, max(kl)))
    return f"""<article class="curve"><h3>seed_{seed}</h3><svg viewBox="0 0 520 116" preserveAspectRatio="none" aria-label="seed {seed} reward and KL"><path d="M0 20H520M0 58H520M0 96H520" stroke="rgba(255,255,255,.08)" fill="none"/><polyline points="{reward_points}" fill="none" stroke="#66b48d" stroke-width="2"/><polyline points="{kl_points}" fill="none" stroke="#d4a72c" stroke-width="1.5"/></svg><div class="meta"><span>reward / green · KL / gold</span><span>{run['trajectory_rollouts']:,} trajectories</span></div></article>"""


def _points(values: list[float], *, minimum: float, maximum: float) -> str:
    span = max(maximum - minimum, 1e-9)
    denominator = max(len(values) - 1, 1)
    return " ".join(
        f"{index / denominator * 520:.2f},{100 - (value - minimum) / span * 84:.2f}"
        for index, value in enumerate(values)
    )


def _gate_card(label: str, gate: dict[str, Any], summary: dict[str, Any]) -> str:
    raw = summary["raw"]
    bootstrap = gate.get("paired_bootstrap") or {}
    reward_ci = bootstrap.get("reward_delta") or {}
    lower = reward_ci.get("ci95_lower")
    ci_text = f"{float(lower):+.4f}" if lower is not None else "five-seed"
    return f"""<article class="gate"><div class="seal">PASS</div><h3>{html.escape(label)}</h3><p><strong>{float(raw['choice_success_rate']):.1%}</strong> choice<br><strong>{float(raw['episode_success_rate']):.1%}</strong> episode<br>reward Δ CI lower <code>{ci_text}</code></p></article>"""


def _knowledge_card(item: dict[str, Any]) -> str:
    if item["status"] != "VERIFIED":
        raise ValueError(f"knowledge item {item['number']} is not verified")
    return f"""<article class="knowledge-card" id="knowledge-{item['number']}"><div class="knowledge-index">{int(item['number']):02d}</div><div><span class="status">VERIFIED</span><h3>{html.escape(str(item['title']))}</h3><p>{html.escape(str(item['finding']))}</p><code>{len(item['evidence'])} evidence artifact(s)</code></div></article>"""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = generate_report(
        repo_root=args.repo_root.resolve(),
        artifact_root=args.artifact_root.resolve(),
        evaluation_root=args.evaluation_root.resolve(),
        coverage_path=args.coverage.resolve(),
        output_path=args.output.resolve(),
    )
    print(path)


if __name__ == "__main__":
    main()
