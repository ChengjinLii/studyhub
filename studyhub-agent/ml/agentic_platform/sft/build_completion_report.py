"""Build the self-contained StudyHub SFT completion report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = (
    ROOT
    / "reports"
    / "STUDYHUB_SFT_COMPLETION_REPORT.html"
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _metric_rate(summary: dict[str, Any], name: str) -> float:
    return float(summary["metrics"][name]["rate"])


def _path_link(path: Path, label: str | None = None) -> str:
    resolved = path.resolve()
    return (
        f'<a class="path" href="file://{html.escape(str(resolved))}">'
        f"{html.escape(label or str(resolved.relative_to(ROOT)))}</a>"
    )


def _line_chart(
    *,
    chart_id: str,
    train_points: list[tuple[float, float]],
    eval_points: list[tuple[float, float]],
    y_label: str,
) -> str:
    width, height = 760, 300
    left, right, top, bottom = 58, 24, 24, 44
    plot_w = width - left - right
    plot_h = height - top - bottom
    all_points = train_points + eval_points
    max_x = max((point[0] for point in all_points), default=1.0)
    max_y = max((point[1] for point in all_points), default=1.0) * 1.08
    max_y = max(max_y, 0.01)

    def coords(points: list[tuple[float, float]]) -> str:
        values = []
        for x_value, y_value in points:
            x = left + (x_value / max_x) * plot_w
            y = top + (1 - y_value / max_y) * plot_h
            values.append(f"{x:.1f},{y:.1f}")
        return " ".join(values)

    grid = []
    labels = []
    for index in range(5):
        ratio = index / 4
        y = top + ratio * plot_h
        value = max_y * (1 - ratio)
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" '
            f'y2="{y:.1f}" class="chart-grid" />'
        )
        labels.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" '
            f'class="chart-label">{value:.2f}</text>'
        )
    for index in range(5):
        ratio = index / 4
        x = left + ratio * plot_w
        value = max_x * ratio
        labels.append(
            f'<text x="{x:.1f}" y="{height - 16}" text-anchor="middle" '
            f'class="chart-label">{value:.0f}</text>'
        )

    train_line = coords(train_points)
    eval_line = coords(eval_points)
    return f"""
<svg id="{html.escape(chart_id)}" class="line-chart" viewBox="0 0 {width} {height}"
     role="img" aria-label="训练与验证 {html.escape(y_label)} 曲线">
  {''.join(grid)}
  {''.join(labels)}
  <text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})"
        class="chart-axis">{html.escape(y_label)}</text>
  <text x="{width / 2}" y="{height - 1}" class="chart-axis">step</text>
  <polyline points="{train_line}" class="chart-line train-line" />
  <polyline points="{eval_line}" class="chart-line eval-line" />
  <g class="chart-legend">
    <line x1="{width - 205}" y1="18" x2="{width - 177}" y2="18" class="chart-line train-line" />
    <text x="{width - 170}" y="22">train</text>
    <line x1="{width - 105}" y1="18" x2="{width - 77}" y2="18" class="chart-line eval-line" />
    <text x="{width - 70}" y="22">validation</text>
  </g>
</svg>
""".strip()


def _gate_bars(
    gate: dict[str, Any],
    *,
    variant: str,
) -> str:
    result = gate["variants"][variant]
    labels = {
        "json_valid": "JSON 有效",
        "contract_valid": "契约有效",
        "tool_required_mode": "工具模式",
        "tool_required_name": "工具名称",
        "force_final_compliant": "预算收尾",
        "explicit_page_number_preserved": "页码保真",
        "material_ids_exact": "资料 ID 保真",
        "direct_no_tool_compliant": "直接回答",
        "synthesis_contract": "综合输出",
        "policy_refusal_compliant": "权限拒绝",
        "injection_safe_readonly": "注入恢复",
    }
    rows = []
    for name, label in labels.items():
        actual = float(result["metrics"][name])
        threshold = float(result["thresholds"][name])
        passed = actual >= threshold
        rows.append(
            f"""
<div class="gate-row {'pass' if passed else 'fail'}">
  <div class="gate-label"><span>{html.escape(label)}</span><strong>{_pct(actual)}</strong></div>
  <div class="gate-track" aria-label="{html.escape(label)} {_pct(actual)}，阈值 {_pct(threshold)}">
    <span class="gate-fill" style="width:{actual * 100:.3f}%"></span>
    <i class="threshold" style="left:{threshold * 100:.3f}%"></i>
  </div>
</div>
"""
        )
    return "".join(rows)


def _training_points(path: Path) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    state = _load_json(path)
    train = [
        (float(row["step"]), float(row["loss"]))
        for row in state["log_history"]
        if "loss" in row
    ]
    validation = [
        (float(row["step"]), float(row["eval_loss"]))
        for row in state["log_history"]
        if "eval_loss" in row
    ]
    return train, validation


def _knowledge_cards(
    *,
    router_gate: dict[str, Any],
    router_token_limit: int,
    tutor_holdout_rate: float,
) -> str:
    router_passed = bool(router_gate["passed"])
    cards = [
        (
            "任务定义",
            "分别规定模型职责、输出格式和禁止操作。",
            "StudyHub 拆成 Router 2B 与 Grounded Tutor 9B：前者只输出 tools/final 严格 JSON，后者只基于免费证据生成带引用的 final JSON。生产写操作、付费链接和越权访问均不在训练边界内。",
            "已覆盖",
        ),
        (
            "数据来源与质量",
            "记录标签等级、证据来源和清洗规则。",
            "两条数据线的标注等级均为教师审校 Silver，不计作人工金标。Router 使用公开元数据、预览 OCR 和合成状态；Tutor 使用 69 个免费资料的 223 个清洗页。重复、空 target、付费资料和生产访问均为 0。",
            "已覆盖，缺人工金标",
        ),
        (
            "训练 / 验证 / 测试",
            "训练集用于参数更新，验证集用于选型，封存集用于最终评测。",
            (
                "Router 为 1,476/164，并另有 300 条开发诊断集与未读取的一次性封存集。"
                "Tutor 为 960/120，另有 120 条按资料隔离的封存集；封存集只访问一次，"
                f"结果为 {_pct(tutor_holdout_rate)}。"
            ),
            "已执行",
        ),
        (
            "数据泄漏控制",
            "同时检查资料、模板和 payload 级重叠。",
            "Tutor 按 material_id 划分 55/7/7 个资料。Router 与开发诊断集的 query、payload、target 精确重叠均为 0，并检查近似 query、资料交叉和 Pilot query 重叠；封存 Router 集尚未读取。",
            "已覆盖",
        ),
        (
            "数据构造与配比",
            "记录主任务、难例、负例和 Replay 的样本比例。",
            "Router v1.7 含 12 个任务族、raw/runtime_state 各 820 条，重点补注入恢复、状态迁移和个人记忆，并保留直接回答、拒绝越权、页码和搜索 Replay。Tutor 含 10 个讲解与证据任务族。",
            "已覆盖，仍需真实轨迹",
        ),
        (
            "Chat Template 与 Tokenizer",
            "训练与推理采用同一模板和 tokenizer 配置。",
            (
                "统一使用 qwen3_5_nothink 与 enable_thinking=false，cutoff 4,096，不 packing。"
                "Router 最大总 token 1,731，Tutor 最大 2,233，均无训练截断；"
                f"正式 Router 诊断按生产默认 {router_token_limit} 个输出 token 运行。"
            ),
            "已对齐",
        ),
        (
            "Loss 与 Label Mask",
            "使用标准自回归交叉熵，并明确 label mask 范围。",
            "使用自回归 token cross-entropy；train_on_prompt=false，仅 assistant target 参与 loss，system、user 和工具观察被 mask。验证同时记录 token accuracy，但上线决策不以 teacher-forcing 指标代替生成式 Gate。",
            "已覆盖",
        ),
        (
            "基础模型选择",
            "按任务复杂度、时延和许可证选择模型规模。",
            "Qwen3.5-2B（revision 15852e8c）用于结构化路由，合并后 2.213B 参数；Qwen3.5-9B（revision c2022362）用于长文本讲解与证据综合，9.453B 参数。两者均为本地模型、Apache-2.0，并验证 Transformers/PEFT/LLaMA-Factory 兼容性。",
            "已覆盖",
        ),
        (
            "LoRA / QLoRA",
            "分别记录 rank、target modules 和合并、量化结果。",
            "两条训练均为 BF16 LoRA，而非 QLoRA：r=16、alpha=32、dropout=0.05、target=all。2B 可训练 16.82M（0.7542%），9B 可训练 43.28M（0.4578%）；NF4 仅用于推理，并从 120/120 降至 116/120。",
            "LoRA 完成，NF4 未过 Gate",
        ),
        (
            "训练超参数",
            "固定并记录学习率、有效 batch、scheduler、seed 和 checkpoint 策略。",
            "2B：1 epoch、5e-6、warmup 10、2×4=8、seed 7703；9B：1 epoch、8e-5、warmup 6、1×8=8、seed 6209。均为 AdamW Torch、cosine、weight decay 0、max grad norm 1.0、BF16、梯度检查点和周期验证。",
            "已覆盖",
        ),
        (
            "显存与训练效率",
            "记录峰值显存、时长、吞吐和利用率。",
            "2B 训练 1,417 秒、峰值 76,588 MiB、1.095 sample/s；9B 训练 2,469 秒、峰值 50,544 MiB、0.408 sample/s。2B 使用 micro batch 2 且缺少快速内核，峰值显存因此高于 9B 运行。训练 token/s 尚未直接记录。",
            "大部分覆盖",
        ),
        (
            "Loss 曲线诊断",
            "同时记录训练与验证趋势，并依据验证点选择 checkpoint。",
            "2B eval loss 从 0.07315 降到 step 184 的 0.04360，最终 step 185 为 0.04372；9B 从 0.22853 降至约 0.186，后半程趋稳。step 184 的 raw Gate 未通过，因此 checkpoint 选择还需要生成式评测。",
            "已覆盖",
        ),
        (
            "生成式评测",
            "使用实际解码输出按业务合同评分。",
            "Router 检查 JSON、contract、mode、工具名、参数、ID、页码、拒绝和注入恢复，raw 与 runtime_state 必须同时通过。Tutor 检查引用精确、证据边界、无工具动作、无敏感输出和任务族最低通过率。",
            "已覆盖",
        ),
        (
            "泛化与稳定性",
            "评测覆盖未见措辞、状态路径、长上下文和多个随机种子。",
            "Router 开发诊断与训练 query 精确隔离，并同时跑两条生产形态路径；但 v1.7 只有 seed 7703，尚不能宣称多 seed 稳定。Tutor 使用按资料隔离的验证和封存集，但也只有单 seed。",
            "部分覆盖",
        ),
        (
            "灾难性遗忘",
            "使用回归集检查定向数据对旧路由和权限拒绝的影响。",
            "Router 数据保留直接回答、搜索、页码、ID、强制收尾和权限拒绝 Replay。当前开发诊断中直接回答与权限拒绝指标较高，注入恢复仍为失败项；Replay 结果与最终 Gate 分别记录。",
            "有回归集，仍未达标",
        ),
        (
            "推理与上线",
            "分别评测 Adapter、合并、量化、输出预算、约束解码和回滚。",
            (
                "9B 完成 base/adapter/merged/NF4 对照；BF16 merged 通过离线 Gate，"
                "NF4 因 4 条合同失败未通过。Router 正式评测使用生产输出预算；"
                f"开发 Gate {'通过' if router_passed else '未通过'}，生产开关保持关闭，"
                f"封存集和 Pilot {'可执行' if router_passed else '未执行'}。"
            ),
            "生产条件未满足" if not router_passed else "开发 Gate 通过",
        ),
        (
            "可复现与治理",
            "保存代码、数据、模型、环境和评测决策记录。",
            "保存 Git commit、配置快照、GPU 秒级遥测、各级 SHA-256、封存锁和运行清单。环境锁定 Python 3.12.13、Torch 2.4.1+cu121、Transformers 5.6.0；SFT 范围 ruff 与 76 个 pytest 通过，生产 DB/API 未访问。",
            "已覆盖",
        ),
    ]
    rendered = []
    for index, (title, lead, body, status) in enumerate(cards, start=1):
        rendered.append(
            f"""
<article class="knowledge-card" id="k{index:02d}" data-index="{index:02d}">
  <div class="knowledge-number">{index:02d}</div>
  <div class="knowledge-copy">
    <div class="knowledge-head">
      <h3>{html.escape(title)}</h3>
      <span class="status-pill">{html.escape(status)}</span>
    </div>
    <p class="knowledge-lead">{html.escape(lead)}</p>
    <p>{html.escape(body)}</p>
  </div>
</article>
"""
        )
    return "".join(rendered)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>StudyHub Agent · SFT 实验报告</title>
  <style>
    :root {
      --ink: #14241d;
      --ink-soft: #4e6158;
      --paper: #f4f0e5;
      --paper-light: #fbf9f2;
      --green: #1f6b50;
      --green-bright: #3f9b72;
      --green-pale: #dce9df;
      --gold: #c99930;
      --gold-pale: #eee0b9;
      --red: #a94c3d;
      --red-pale: #f0d8d1;
      --line: rgba(20, 36, 29, .16);
      --shadow: 0 18px 60px rgba(32, 49, 41, .10);
      --serif: "Iowan Old Style", "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", serif;
      --sans: "Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --mono: "SFMono-Regular", "Cascadia Code", "JetBrains Mono", monospace;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 9%, rgba(201, 153, 48, .14), transparent 26rem),
        radial-gradient(circle at 90% 4%, rgba(31, 107, 80, .13), transparent 30rem),
        var(--paper);
      font-family: var(--sans);
      line-height: 1.68;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: .18;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='80' viewBox='0 0 80 80'%3E%3Cpath d='M0 79.5h80M79.5 0v80' stroke='%231f6b50' stroke-opacity='.12'/%3E%3C/svg%3E");
      z-index: -1;
    }
    a { color: inherit; }
    .progress {
      position: fixed;
      top: 0;
      left: 0;
      width: 0;
      height: 3px;
      background: var(--gold);
      z-index: 100;
    }
    .shell { width: min(1420px, calc(100% - 48px)); margin: 0 auto; }
    .hero { min-height: 92vh; display: grid; align-content: center; padding: 72px 0 46px; }
    .hero-grid { display: grid; grid-template-columns: 1.28fr .72fr; gap: 56px; align-items: end; }
    .eyebrow { display: flex; align-items: center; gap: 14px; color: var(--green); font: 700 12px/1 var(--mono); letter-spacing: .16em; text-transform: uppercase; }
    .eyebrow::before { content: ""; width: 54px; height: 2px; background: var(--gold); }
    h1 { margin: 22px 0 20px; font-family: var(--serif); font-size: clamp(64px, 9vw, 142px); line-height: .86; letter-spacing: -.065em; font-weight: 700; }
    h1 span { display: block; color: var(--green); font-size: .47em; letter-spacing: -.03em; margin-top: .24em; }
    .hero-lead { max-width: 820px; font-family: var(--serif); font-size: clamp(20px, 2.2vw, 31px); line-height: 1.48; color: #2a3d34; }
    .hero-note { margin-top: 26px; max-width: 760px; color: var(--ink-soft); }
    .decision-card { background: var(--ink); color: var(--paper-light); padding: 34px; border-radius: 2px 28px 2px 2px; box-shadow: var(--shadow); position: relative; overflow: hidden; }
    .decision-card::after { content: "SFT"; position: absolute; right: -14px; bottom: -38px; font: 800 130px/1 var(--serif); color: rgba(255,255,255,.045); }
    .decision-label { color: #9dd1b6; font: 700 11px/1 var(--mono); letter-spacing: .15em; text-transform: uppercase; }
    .decision-card h2 { margin: 18px 0 12px; font: 600 32px/1.18 var(--serif); }
    .decision-card p { color: #c5d0ca; margin: 0; }
    .decision-state { display: inline-flex; margin-top: 28px; border: 1px solid rgba(255,255,255,.25); padding: 8px 12px; font: 700 12px/1 var(--mono); color: #ffd977; }
    .metric-strip { margin-top: 64px; display: grid; grid-template-columns: repeat(4, 1fr); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
    .metric { padding: 24px 20px; border-right: 1px solid var(--line); }
    .metric:last-child { border-right: 0; }
    .metric strong { display: block; font: 650 clamp(28px, 3.5vw, 48px)/1 var(--serif); }
    .metric span { display: block; margin-top: 9px; color: var(--ink-soft); font-size: 13px; }
    .report-layout { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 54px; align-items: start; padding-bottom: 100px; }
    main, .section-head > *, .track-card, .panel, .gate-column, .knowledge-copy { min-width: 0; }
    .rail { position: sticky; top: 28px; padding: 26px 0; }
    .rail-title { font: 700 11px/1 var(--mono); color: var(--green); letter-spacing: .14em; text-transform: uppercase; }
    .rail a { display: block; padding: 9px 0; text-decoration: none; color: var(--ink-soft); font-size: 13px; border-bottom: 1px solid transparent; }
    .rail a:hover, .rail a.active { color: var(--green); border-bottom-color: var(--gold); }
    .rail-meta { margin-top: 28px; padding-top: 18px; border-top: 1px solid var(--line); color: var(--ink-soft); font: 11px/1.7 var(--mono); }
    main section { padding: 74px 0; border-top: 1px solid var(--line); }
    .section-kicker { font: 700 11px/1 var(--mono); color: var(--gold); letter-spacing: .15em; text-transform: uppercase; }
    .section-head { display: grid; grid-template-columns: .86fr 1.14fr; gap: 42px; margin: 14px 0 38px; }
    .section-head h2 { margin: 0; font: 650 clamp(36px, 5vw, 65px)/1.02 var(--serif); letter-spacing: -.035em; }
    .section-head p { margin: 6px 0 0; color: var(--ink-soft); font-size: 17px; max-width: 700px; }
    .track-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
    .track-card { background: rgba(251, 249, 242, .88); border: 1px solid var(--line); padding: 30px; min-height: 340px; position: relative; box-shadow: 0 10px 40px rgba(32,49,41,.05); }
    .track-card.router { border-top: 5px solid var(--gold); }
    .track-card.tutor { border-top: 5px solid var(--green); }
    .track-id { font: 700 11px/1 var(--mono); letter-spacing: .12em; color: var(--ink-soft); }
    .track-card h3 { margin: 18px 0 7px; font: 650 34px/1.1 var(--serif); }
    .track-card .model { color: var(--green); font: 700 13px/1 var(--mono); }
    .track-list { margin: 28px 0 0; padding: 0; list-style: none; }
    .track-list li { display: grid; grid-template-columns: 125px 1fr; gap: 14px; padding: 10px 0; border-top: 1px solid var(--line); font-size: 14px; }
    .track-list span { color: var(--ink-soft); }
    .verdict { margin-top: 26px; padding: 14px 16px; background: var(--red-pale); color: #723329; font-weight: 700; }
    .data-board { display: grid; grid-template-columns: 1.2fr .8fr; gap: 22px; }
    .panel { background: rgba(251,249,242,.86); border: 1px solid var(--line); padding: 28px; }
    .panel h3 { margin: 0 0 20px; font: 650 25px/1.15 var(--serif); }
    .split-row { margin: 22px 0; }
    .split-label { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px; }
    .split-bar { display: flex; height: 28px; overflow: hidden; background: var(--green-pale); }
    .split-bar i { display: block; height: 100%; }
    .split-train { background: var(--green); }
    .split-val { background: var(--gold); }
    .split-test { background: var(--red); }
    .audit-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px; background: var(--line); border: 1px solid var(--line); }
    .audit-cell { padding: 18px; background: var(--paper-light); }
    .audit-cell strong { display: block; font: 650 27px/1 var(--serif); color: var(--green); }
    .audit-cell span { display: block; margin-top: 7px; font-size: 12px; color: var(--ink-soft); }
    .chart-grid { stroke: rgba(20,36,29,.11); stroke-width: 1; }
    .chart-label, .chart-axis, .chart-legend { fill: #607168; font: 11px var(--mono); }
    .chart-axis { text-anchor: middle; }
    .chart-line { fill: none; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
    .train-line { stroke: var(--green); }
    .eval-line { stroke: var(--gold); }
    .line-chart { width: 100%; height: auto; overflow: visible; }
    .chart-note { margin: 8px 0 0; color: var(--ink-soft); font-size: 13px; }
    .chart-grid-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
    .gate-shell { background: var(--ink); color: var(--paper-light); padding: 30px; }
    .gate-shell h3 { margin: 0 0 8px; font: 650 27px/1.2 var(--serif); }
    .gate-shell > p { color: #adbbb3; margin: 0 0 24px; font-size: 13px; }
    .gate-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
    .gate-column h4 { margin: 0 0 16px; color: #f0cc68; font: 700 12px/1 var(--mono); letter-spacing: .12em; text-transform: uppercase; }
    .gate-row { margin: 11px 0; }
    .gate-label { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
    .gate-label strong { font-family: var(--mono); }
    .gate-track { position: relative; height: 7px; margin-top: 5px; background: rgba(255,255,255,.10); }
    .gate-fill { display: block; height: 100%; background: #66b78f; }
    .gate-row.fail .gate-fill { background: #c76958; }
    .threshold { position: absolute; top: -3px; height: 13px; width: 1px; background: #f1d27d; }
    .compare-table { width: 100%; border-collapse: collapse; background: var(--paper-light); }
    .compare-table th, .compare-table td { padding: 15px 14px; text-align: left; border-bottom: 1px solid var(--line); font-size: 13px; }
    .compare-table th { color: var(--ink-soft); font: 700 11px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; }
    .compare-table td strong { font-family: var(--mono); }
    .compare-table tr.recommended { background: var(--green-pale); }
    .compare-table tr.rejected { background: rgba(240,216,209,.55); }
    .knowledge-list { display: grid; gap: 12px; }
    .knowledge-card { display: grid; grid-template-columns: 92px 1fr; background: rgba(251,249,242,.84); border: 1px solid var(--line); transition: transform .18s ease, box-shadow .18s ease; }
    .knowledge-card:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
    .knowledge-number { padding: 24px; color: var(--gold); font: 700 19px/1 var(--mono); border-right: 1px solid var(--line); }
    .knowledge-copy { padding: 23px 26px 25px; }
    .knowledge-head { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
    .knowledge-head h3 { margin: 0; font: 650 26px/1.1 var(--serif); }
    .status-pill { flex: 0 0 auto; border: 1px solid var(--line); padding: 5px 9px; color: var(--green); font: 700 10px/1 var(--mono); }
    .knowledge-copy p { margin: 10px 0 0; color: var(--ink-soft); }
    .knowledge-copy p, .knowledge-head h3, .chart-note { overflow-wrap: anywhere; }
    .knowledge-copy .knowledge-lead { color: var(--ink); font-weight: 700; }
    .decision-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
    .decision-panel { padding: 28px; border: 1px solid var(--line); background: var(--paper-light); }
    .decision-panel.blocked { border-top: 5px solid var(--red); }
    .decision-panel.next { border-top: 5px solid var(--green); }
    .decision-panel h3 { margin: 0 0 14px; font: 650 27px/1.15 var(--serif); }
    .decision-panel ol { margin: 0; padding-left: 21px; }
    .decision-panel li { margin: 9px 0; color: var(--ink-soft); }
    .evidence-list { display: grid; gap: 10px; }
    .evidence-row { display: grid; grid-template-columns: 180px 1fr; gap: 18px; padding: 14px 0; border-bottom: 1px solid var(--line); font-size: 12px; }
    .evidence-row span { color: var(--ink-soft); }
    .path { overflow-wrap: anywhere; font-family: var(--mono); color: var(--green); text-decoration-color: var(--gold); }
    .hash { overflow-wrap: anywhere; font: 11px/1.6 var(--mono); color: var(--ink-soft); }
    footer { padding: 38px 0 80px; border-top: 1px solid var(--line); color: var(--ink-soft); font-size: 12px; }
    .footer-grid { display: flex; justify-content: space-between; gap: 24px; }
    .reveal { opacity: 0; transform: translateY(16px); transition: opacity .55s ease, transform .55s ease; }
    .reveal.visible { opacity: 1; transform: none; }
    @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } .reveal { opacity: 1; transform: none; transition: none; } }
    @media (max-width: 980px) {
      .shell { width: min(100% - 30px, 780px); }
      .hero { min-height: auto; padding-top: 54px; }
      .hero-grid, .section-head, .data-board, .chart-grid-layout, .gate-columns, .decision-grid { grid-template-columns: 1fr; }
      .metric-strip { grid-template-columns: 1fr 1fr; }
      .metric:nth-child(2) { border-right: 0; }
      .metric:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
      .report-layout { grid-template-columns: 1fr; }
      .rail { display: none; }
      .track-grid { grid-template-columns: 1fr; }
      main section { padding: 58px 0; }
    }
    @media (max-width: 620px) {
      h1 { font-size: 58px; }
      .hero-lead { font-size: 20px; }
      .decision-card { padding: 26px; }
      .metric { padding: 18px 12px; }
      .knowledge-card { grid-template-columns: 52px 1fr; }
      .knowledge-number { padding: 18px 12px; font-size: 14px; }
      .knowledge-copy { padding: 18px 16px 20px; }
      .knowledge-head { align-items: flex-start; flex-direction: column; gap: 9px; }
      .knowledge-head h3 { font-size: 22px; }
      .status-pill { white-space: normal; }
      .track-list li, .evidence-row { grid-template-columns: 1fr; gap: 3px; }
      .compare-wrap { overflow-x: auto; }
      .compare-table { min-width: 680px; }
      .footer-grid { display: block; }
    }
    @media print {
      body { background: white; }
      body::before, .progress, .rail { display: none; }
      .shell { width: 100%; }
      .hero { min-height: auto; page-break-after: always; }
      .report-layout { display: block; }
      .knowledge-card, .panel, .track-card { break-inside: avoid; box-shadow: none; }
      .reveal { opacity: 1; transform: none; }
    }
  </style>
</head>
<body>
  <div class="progress" aria-hidden="true"></div>
  <header class="hero shell">
    <div class="hero-grid">
      <div>
        <div class="eyebrow">StudyHub Agent · SFT Experiment Report</div>
        <h1>SFT<span>任务、数据、训练与评测</span></h1>
        <p class="hero-lead">本报告分别记录 2B Router 和 9B Grounded Tutor 的数据、训练配置、生成式评测与 Gate 结果。</p>
        <p class="hero-note">共包含 2,720 条训练和验证样本，并比较 LoRA、合并 BF16 与 NF4 推理形态。实验未访问生产数据库、API、OSS 写接口或付费资料。</p>
      </div>
      <aside class="decision-card">
        <div class="decision-label">Release decision / 2026-08-11</div>
        <h2>当前 SFT<br>实验结论</h2>
        <p>9B 独立验证为 120/120，封存集因 1 条输出截断得到 119/120；2B 正式开发 Gate @@ROUTER_GATE_STATE@@。发布判断同时使用生成式任务指标和预设 Gate。</p>
        <div class="decision-state">PRODUCTION FLAGS · OFF</div>
      </aside>
    </div>
    <div class="metric-strip">
      <div class="metric"><strong>2,720</strong><span>训练 + 验证样本</span></div>
      <div class="metric"><strong>17</strong><span>实验记录项目</span></div>
      <div class="metric"><strong>120/120</strong><span>9B BF16 独立验证</span></div>
      <div class="metric"><strong>0</strong><span>生产与付费资料访问</span></div>
    </div>
  </header>

  <div class="shell report-layout">
    <nav class="rail" aria-label="报告目录">
      <div class="rail-title">Field index</div>
      <a href="#overview">结论总览</a>
      <a href="#data">数据与拆分</a>
      <a href="#curves">训练曲线</a>
      <a href="#gates">生成式 Gate</a>
      <a href="#deployment">部署对照</a>
      <a href="#knowledge">实验记录</a>
      <a href="#decision">决策与下一步</a>
      <a href="#evidence">证据与复现</a>
      <div class="rail-meta">Branch<br>research/agent-sft-completion<br><br>Scope<br>Offline only</div>
    </nav>

    <main>
      <section id="overview" class="reveal">
        <div class="section-kicker">01 / Executive readout</div>
        <div class="section-head">
          <h2>任务拆分与<br>模型职责</h2>
          <p>Router 负责离散工具决策，Tutor 负责基于证据生成学习内容。两项任务分别使用对应的模型规模、数据构造方式、输出合同和评测指标。</p>
        </div>
        <div class="track-grid">
          <article class="track-card router">
            <div class="track-id">TRACK A / CONTROL PLANE</div>
            <h3>Router 2B v1.7</h3>
            <div class="model">Qwen3.5-2B · LoRA r16 · seed 7703</div>
            <ul class="track-list">
              <li><span>任务</span><strong>tools / final 严格路由</strong></li>
              <li><span>数据</span><strong>1,476 train / 164 val</strong></li>
              <li><span>训练结果</span><strong>loss 0.0705 · val 0.0437</strong></li>
              <li><span>正式诊断</span><strong>@@ROUTER_TOKEN_LIMIT@@ output tokens</strong></li>
              <li><span>Gate 状态</span><strong>@@ROUTER_GATE_LABEL@@</strong></li>
            </ul>
            <div class="verdict">@@ROUTER_VERDICT@@</div>
          </article>
          <article class="track-card tutor">
            <div class="track-id">TRACK B / KNOWLEDGE PLANE</div>
            <h3>Grounded Tutor 9B</h3>
            <div class="model">Qwen3.5-9B · LoRA r16 · seed 6209</div>
            <ul class="track-list">
              <li><span>任务</span><strong>证据讲解、比较与计划</strong></li>
              <li><span>数据</span><strong>960 train / 120 val / 120 sealed</strong></li>
              <li><span>独立验证</span><strong>120/120 · 100%</strong></li>
              <li><span>一次性封存</span><strong>119/120 · 99.17%</strong></li>
              <li><span>Gate 状态</span><strong>未通过</strong></li>
            </ul>
            <div class="verdict">1 条输出在 768-token 上限截断，no-tool Gate 未通过。</div>
          </article>
        </div>
      </section>

      <section id="data" class="reveal">
        <div class="section-kicker">02 / Dataset anatomy</div>
        <div class="section-head">
          <h2>数据构造、拆分<br>与边界</h2>
          <p>标签等级为教师审校 Silver，资料范围为公开免费资料，Tutor 按资料拆分数据，开发集与封存集分离。Silver 标签不记作人工金标，封存结果不回流训练。</p>
        </div>
        <div class="data-board">
          <div class="panel">
            <h3>Split 结构</h3>
            <div class="split-row">
              <div class="split-label"><strong>Router 2B</strong><span>1,476 / 164 / sealed unread</span></div>
              <div class="split-bar"><i class="split-train" style="width:90%"></i><i class="split-val" style="width:10%"></i></div>
            </div>
            <div class="split-row">
              <div class="split-label"><strong>Grounded Tutor 9B</strong><span>960 / 120 / 120</span></div>
              <div class="split-bar"><i class="split-train" style="width:80%"></i><i class="split-val" style="width:10%"></i><i class="split-test" style="width:10%"></i></div>
            </div>
            <p class="chart-note">Tutor 按 material_id 划分 55 / 7 / 7 个资料；Router 另设 300 条开发诊断集，不属于训练、验证或最终封存集。</p>
          </div>
          <div class="panel">
            <h3>审计快照</h3>
            <div class="audit-grid">
              <div class="audit-cell"><strong>0</strong><span>重复样本对</span></div>
              <div class="audit-cell"><strong>0</strong><span>训练截断</span></div>
              <div class="audit-cell"><strong>0</strong><span>material split 泄漏</span></div>
              <div class="audit-cell"><strong>0</strong><span>付费资料</span></div>
              <div class="audit-cell"><strong>0</strong><span>生产 API / DB</span></div>
              <div class="audit-cell"><strong>Silver</strong><span>教师审校，非人工金标</span></div>
            </div>
          </div>
        </div>
      </section>

      <section id="curves" class="reveal">
        <div class="section-kicker">03 / Optimization signals</div>
        <div class="section-head">
          <h2>训练曲线与<br>任务评测</h2>
          <p>两条训练曲线均正常收敛，2B token accuracy 为 98.95%。Router 生成式 Gate 未通过，因此 teacher-forcing 指标不能单独用于判断任务完成率。</p>
        </div>
        <div class="chart-grid-layout">
          <div class="panel">
            <h3>Router 2B · train / validation loss</h3>
            @@ROUTER_LOSS_CHART@@
            <p class="chart-note">最低验证 loss 出现在 step 184：0.04360；最终 step 185：0.04372。@@CHECKPOINT_VERDICT@@</p>
          </div>
          <div class="panel">
            <h3>Grounded Tutor 9B · train / validation loss</h3>
            @@TUTOR_LOSS_CHART@@
            <p class="chart-note">验证 loss 从 0.22853 降至约 0.186，后半程稳定，无明显发散。</p>
          </div>
        </div>
      </section>

      <section id="gates" class="reveal">
        <div class="section-kicker">04 / Generated-output gate</div>
        <div class="section-head">
          <h2>生成式评测与<br>合同检查</h2>
          <p>Gate 对确定性生成结果逐条评分。细竖线表示阈值，红色表示未达到；raw 与 runtime_state 两条路径分别统计，安全指标与功能指标分别判断。</p>
        </div>
        <div class="gate-shell">
          <h3>Router 2B · 正式开发诊断</h3>
          <p>300 条教师隐藏开发诊断 · production prompt · greedy decoding · @@ROUTER_TOKEN_LIMIT@@ max new tokens</p>
          <div class="gate-columns">
            <div class="gate-column"><h4>Raw runtime payload</h4>@@RAW_GATE_BARS@@</div>
            <div class="gate-column"><h4>Normalized routing state</h4>@@NORMALIZED_GATE_BARS@@</div>
          </div>
        </div>
      </section>

      <section id="deployment" class="reveal">
        <div class="section-kicker">05 / Deployment forms</div>
        <div class="section-head">
          <h2>推理形态与<br>资源对照</h2>
          <p>9B adapter、合并 BF16 和 NF4 均完成生成式评测。合并 BF16 的严格通过率为 100%，本批次吞吐高于 adapter；NF4 降低显存，但出现 4 条合同失败，未通过 Gate。</p>
        </div>
        <div class="compare-wrap">
          <table class="compare-table">
            <thead><tr><th>形态</th><th>严格通过</th><th>峰值显存</th><th>生成吞吐</th><th>Gate</th></tr></thead>
            <tbody>
              <tr><td>Base BF16</td><td><strong>4 / 120</strong></td><td>21,232.6 MiB</td><td>152.46 token/s</td><td>失败</td></tr>
              <tr><td>LoRA BF16</td><td><strong>120 / 120</strong></td><td>21,399.2 MiB</td><td>86.49 token/s</td><td>通过</td></tr>
              <tr class="recommended"><td>Merged BF16</td><td><strong>120 / 120</strong></td><td>21,232.6 MiB</td><td>139.98 token/s</td><td>验证通过</td></tr>
              <tr class="rejected"><td>Merged NF4</td><td><strong>116 / 120</strong></td><td>10,800.9 MiB</td><td>80.86 token/s</td><td>失败</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section id="knowledge" class="reveal">
        <div class="section-kicker">06 / Experiment records</div>
        <div class="section-head">
          <h2>实验设计与<br>结果覆盖</h2>
          <p>报告覆盖任务定义、数据拆分、loss、训练曲线、模型、LoRA、显存、泄漏检查、模板一致性、生成式评测、稳定性、能力回归、推理形态和复现记录。</p>
        </div>
        <div class="knowledge-list">@@KNOWLEDGE_CARDS@@</div>
      </section>

      <section id="decision" class="reveal">
        <div class="section-kicker">07 / Decision log</div>
        <div class="section-head">
          <h2>模型结论与<br>后续实验</h2>
          <p>本节汇总任务指标和 Gate 状态。评测沿用预设阈值，封存集按既定次数访问，截断样本保留在统计中。</p>
        </div>
        <div class="decision-grid">
          <article class="decision-panel blocked">
            <h3>当前不执行</h3>
            <ol>
              <li>不启用生产 Agent 模型开关。</li>
              <li>不把 9B 封存集失败回流为新训练样本。</li>
              <li>不因 NF4 显存更低而忽略 4 条严格失败。</li>
              <li>@@ROUTER_BLOCKED_ACTION@@</li>
            </ol>
          </article>
          <article class="decision-panel next">
            <h3>后续实验</h3>
            <ol>
              <li>建立小规模人工金标集，重点复核路由状态、页码和注入恢复。</li>
              <li>单独评测结构化 JSON 约束解码，并与新增合成 SFT 做对照。</li>
              <li>为当前版本补多 seed 稳定性和真实长会话故障注入。</li>
              <li>开发 Gate 通过后，再创建新的封存集并执行 Pilot。</li>
            </ol>
          </article>
        </div>
      </section>

      <section id="evidence" class="reveal">
        <div class="section-kicker">08 / Provenance</div>
        <div class="section-head">
          <h2>实验产物与<br>复现索引</h2>
          <p>以下文件是本报告的直接证据。训练与评测大文件位于 Git ignore 目录；代码、配置、报告和哈希清单进入研究分支。</p>
        </div>
        <div class="evidence-list">
          @@EVIDENCE_ROWS@@
        </div>
        <p class="hash">Router dataset SHA-256 · 89ac4ffda706693cd5ec59b1f9b46938324ec511970d2fb19956189160e3eb14<br>
        Router adapter SHA-256 · 6d2428abf3686be600509c5dff8fae34bb43076f391d86c90eab9b1971797eb1<br>
        Tutor dataset SHA-256 · 85f5f211b913991beffbfea88daf45c4cf3291c5cf802d5b2d49ddb6befca0e4<br>
        Tutor adapter SHA-256 · d5f1b1cca2386cfa62b8f010c9b9c9cdc0055eb7c9c08e8672ec818eaef46c1a<br>
        Tutor merged aggregate SHA-256 · da7b7887487d8799c019a65f59db20f7d41c64336b5ba0f90660cfaba1d5d7a5</p>
        <p class="hash">2B model lock · revision 15852e8c16360a2fea060d615a32b45270f8a8fc · config ed1c1723241f23f7f4e23430759cbd7dcfb4103cbdfe052bfe7626b57c2615b4 · index aca8afed9da75b0f050b408d270766fd77627f1af401e240f61c3b47d0db02f9<br>
        9B model lock · revision c202236235762e1c871ad0ccb60c8ee5ba337b9a · config d0883072e01861ed0b2d47be3c16c36a8e81c224c7ffaa310c6558fb3f932b05 · index 26d3539b516be613f39563617cb9d33b3f83d401298125be392c80cefb8f7fe5</p>
      </section>
    </main>
  </div>

  <footer class="shell">
    <div class="footer-grid"><span>StudyHub Agent · SFT Completion Report</span><span>Teacher-reviewed Silver · Offline only · 2026-08-11</span></div>
  </footer>
  <script>
    const progress = document.querySelector('.progress');
    const links = [...document.querySelectorAll('.rail a')];
    const sections = [...document.querySelectorAll('main section')];
    const reveals = [...document.querySelectorAll('.reveal')];
    const updateProgress = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      progress.style.width = `${max > 0 ? (window.scrollY / max) * 100 : 0}%`;
    };
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          links.forEach((link) => link.classList.toggle('active', link.hash === `#${entry.target.id}`));
        }
      });
    }, { rootMargin: '-18% 0px -62% 0px', threshold: 0 });
    sections.forEach((section) => observer.observe(section));
    const revealObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => { if (entry.isIntersecting) entry.target.classList.add('visible'); });
    }, { threshold: .08 });
    reveals.forEach((item) => revealObserver.observe(item));
    window.addEventListener('scroll', updateProgress, { passive: true });
    updateProgress();
  </script>
</body>
</html>
"""


def build_report(output: Path) -> Path:
    router_root = (
        ROOT
        / "evaluation_artifacts"
        / "studyhub_agent"
        / "router_v1_7_contract_exact_1800_diagnostic"
        / "seed_7703"
    )
    fallback_router_root = (
        ROOT
        / "evaluation_artifacts"
        / "studyhub_agent"
        / "router_v1_7_contract_exact_diagnostic"
        / "seed_7703"
    )
    if not (router_root / "gate.json").is_file():
        router_root = fallback_router_root
    router_gate = _load_json(router_root / "gate.json")
    manifest_path = router_root / "run_manifest.json"
    if not manifest_path.is_file():
        manifest_path = router_root / "run_manifest.recovered.json"
    router_manifest = _load_json(manifest_path)
    router_token_limit = int(router_manifest["decoding"]["max_new_tokens"])
    checkpoint_root = (
        ROOT
        / "evaluation_artifacts"
        / "studyhub_agent"
        / "router_v1_7_checkpoint184_contract_exact_1800_diagnostic"
        / "seed_7703"
    )
    checkpoint_gate = _load_json(checkpoint_root / "gate.json")
    checkpoint_raw_metrics = checkpoint_gate["variants"]["raw"]["metrics"]
    checkpoint_verdict = (
        "step 184 raw Gate 通过。"
        if checkpoint_gate["passed"]
        else (
            "step 184 raw Gate 仍失败："
            f"force-final {_pct(float(checkpoint_raw_metrics['force_final_compliant']))}，"
            f"注入只读 {_pct(float(checkpoint_raw_metrics['injection_safe_readonly']))}。"
        )
    )

    tutor_root = (
        ROOT
        / "evaluation_artifacts"
        / "studyhub_agent"
        / "grounded_tutor_9b_v1_0"
    )
    tutor_holdout = _load_json(
        tutor_root / "adapter_holdout_seed_6209_768" / "adapter_summary.json"
    )
    tutor_holdout_rate = _metric_rate(tutor_holdout, "strict_grounded_pass")

    router_train, router_eval = _training_points(
        ROOT
        / "training_artifacts"
        / "studyhub_agent_sft"
        / "qwen35_2b_lora_v1_7_state_transitions_from_v1_6_seed_7703"
        / "trainer_state.json"
    )
    tutor_train, tutor_eval = _training_points(
        ROOT
        / "training_artifacts"
        / "studyhub_agent_sft"
        / "qwen35_9b_lora_grounded_tutor_v1_seed_6209"
        / "trainer_state.json"
    )

    router_passed = bool(router_gate["passed"])
    formal = router_token_limit == 1800
    if router_passed:
        router_verdict = "开发 Gate 通过；只允许进入一次性封存集，不代表可上线。"
        router_blocked_action = "不把开发 Gate 通过解释为生产发布批准。"
    elif formal:
        router_verdict = "正式开发 Gate 未通过；不读取封存集，不运行模型 Pilot，不发布。"
        router_blocked_action = "不读取 Router 一次性封存集，也不运行 100 场景模型 Pilot。"
    else:
        router_verdict = "384-token 基线 Gate 未通过；正式 1,800-token 诊断仍待完成。"
        router_blocked_action = "正式开发诊断完成前，不读取 Router 封存集或运行 Pilot。"

    evidence = [
        (
            "数据与模型卡",
            ROOT
            / "reports"
            / "recagent"
            / "agentic-platform"
            / "STUDYHUB_SFT_CARDS.md",
        ),
        (
            "Router v1.7 数据审计",
            ROOT
            / "training_artifacts"
            / "studyhub_agent_sft"
            / "router_2b_v1_7_state_transitions"
            / "audit.json",
        ),
        ("Router 正式 Gate", router_root / "gate.json"),
        ("Router step 184 raw Gate", checkpoint_root / "gate.json"),
        (
            "Tutor 9B 验证 Gate",
            tutor_root / "adapter_validation_seed_6209_768" / "gate.json",
        ),
        (
            "Tutor 9B 封存 Gate",
            tutor_root / "adapter_holdout_seed_6209_768" / "gate.json",
        ),
        (
            "Tutor 9B NF4 Gate",
            tutor_root / "merged_nf4_validation_768_compat" / "gate.json",
        ),
        (
            "最终 SFT 模型锁",
            ROOT
            / "ml"
            / "agentic_platform"
            / "sft"
            / "model_locks"
            / "studyhub_sft_completion_20260811.json",
        ),
    ]
    evidence_rows = "".join(
        f'<div class="evidence-row"><span>{html.escape(label)}</span>{_path_link(path)}</div>'
        for label, path in evidence
    )

    replacements = {
        "ROUTER_GATE_STATE": "已通过" if router_passed else "未通过",
        "ROUTER_GATE_LABEL": "PASS" if router_passed else "FAIL",
        "ROUTER_TOKEN_LIMIT": str(router_token_limit),
        "ROUTER_VERDICT": router_verdict,
        "ROUTER_BLOCKED_ACTION": router_blocked_action,
        "CHECKPOINT_VERDICT": checkpoint_verdict,
        "ROUTER_LOSS_CHART": _line_chart(
            chart_id="router-loss",
            train_points=router_train,
            eval_points=router_eval,
            y_label="loss",
        ),
        "TUTOR_LOSS_CHART": _line_chart(
            chart_id="tutor-loss",
            train_points=tutor_train,
            eval_points=tutor_eval,
            y_label="loss",
        ),
        "RAW_GATE_BARS": _gate_bars(router_gate, variant="raw"),
        "NORMALIZED_GATE_BARS": _gate_bars(router_gate, variant="normalized"),
        "KNOWLEDGE_CARDS": _knowledge_cards(
            router_gate=router_gate,
            router_token_limit=router_token_limit,
            tutor_holdout_rate=tutor_holdout_rate,
        ),
        "EVIDENCE_ROWS": evidence_rows,
    }
    rendered = HTML_TEMPLATE
    for key, value in replacements.items():
        rendered = rendered.replace(f"@@{key}@@", value)
    unresolved = [piece for piece in rendered.split("@@") if piece.isupper()]
    if unresolved:
        raise RuntimeError(f"unresolved report placeholders: {unresolved}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(build_report(args.output.resolve()))


if __name__ == "__main__":
    main()
