#!/usr/bin/env python3
"""Generate a standalone HTML report from AReaL logs and manifests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
METRIC_RE = re.compile(
    r"(?:^|│)\s*([A-Za-z0-9_./-]+)\s*│\s*([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)",
    re.IGNORECASE,
)
STEP_RE = re.compile(r"Train step (\d+)/(\d+) done")
ELAPSED_RE = re.compile(r"Training completes! Total time elapsed (\d+(?:\.\d+)?)")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return str(value)


def parse_metrics(path: Path) -> list[dict[str, float]]:
    if not path.is_file():
        return []
    rows: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    with path.open(errors="ignore") as stream:
        for raw in stream:
            line = ANSI_RE.sub("", raw)
            step_match = STEP_RE.search(line)
            if step_match:
                if current is not None:
                    rows.append(current)
                current = {"step": float(step_match.group(1)), "total_steps": float(step_match.group(2))}
                continue
            if current is None:
                continue
            for key, value in METRIC_RE.findall(line):
                current[key] = float(value)
    if current is not None:
        rows.append(current)
    return rows


def parse_training_elapsed(path: Path) -> float | None:
    if not path.is_file():
        return None
    match = None
    with path.open(errors="ignore") as stream:
        for raw in stream:
            candidate = ELAPSED_RE.search(ANSI_RE.sub("", raw))
            if candidate:
                match = candidate
    return float(match.group(1)) if match else None


def read_gpu_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    parsed = []
    for row in rows:
        try:
            parsed.append(
                {
                    "timestamp": row["timestamp"],
                    "memory": int(row["memory_used_mib"]),
                    "free": int(row["memory_free_mib"]),
                    "util": int(row["utilization_gpu_pct"]),
                    "power": float(row["power_w"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


def line_chart(
    series: list[tuple[str, list[tuple[float, float]], str]],
    *,
    width: int = 920,
    height: int = 260,
    y_label: str = "",
    threshold: float | None = None,
) -> str:
    all_points = [point for _, points, _ in series for point in points]
    if not all_points:
        return '<div class="empty-chart">暂无可绘制数据</div>'
    x_values = [point[0] for point in all_points]
    y_values = [point[1] for point in all_points]
    if threshold is not None:
        y_values.append(threshold)
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(0.0, min(y_values)), max(y_values)
    if math.isclose(x_min, x_max):
        x_max = x_min + 1
    if math.isclose(y_min, y_max):
        y_max = y_min + 1
    left, right, top, bottom = 64, 20, 24, 42
    plot_w, plot_h = width - left - right, height - top - bottom

    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(y_label)}">']
    for tick in range(5):
        value = y_min + (y_max - y_min) * tick / 4
        y = sy(value)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end">{value:.2f}</text>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis"/>')
    parts.append(f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis"/>')
    if threshold is not None:
        y = sy(threshold)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="threshold"/>')
        parts.append(f'<text x="{width-right}" y="{y-7:.1f}" text-anchor="end" class="threshold-label">上限 {threshold:.0f}</text>')
    for name, points, color in series:
        coords = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in points)
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="3" vector-effect="non-scaling-stroke"/>')
        for x, y in points[-1:]:
            parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="{color}"/>')
        parts.append(f'<g class="legend"><circle cx="{left+len(parts)%3*170}" cy="12" r="4" fill="{color}"/></g>')
    legend = "".join(
        f'<span><i style="background:{color}"></i>{esc(name)}</span>' for name, _, color in series
    )
    parts.append(f'<text x="{left}" y="{height-10}">step / sample</text>')
    parts.append("</svg>")
    return f'<div class="chart-wrap"><div class="chart-legend">{legend}</div>{"".join(parts)}</div>'


def checkpoint_rows(root: Path, experiment: str, trial: str) -> list[dict[str, Any]]:
    base = root / "artifacts/areal/checkpoints/chengjin" / experiment / trial
    rows = []
    for adapter in sorted(base.glob("**/adapter_model.safetensors")):
        step_match = re.search(r"globalstep(\d+)", adapter.parent.name)
        rows.append(
            {
                "step": adapter.parent.name,
                "reported_step": int(step_match.group(1)) + 1 if step_match else None,
                "path": str(adapter.parent.relative_to(root)),
                "bytes": adapter.stat().st_size,
                "sha256": sha256(adapter),
            }
        )
    return sorted(rows, key=lambda item: item["reported_step"] or 0)


def source_split_counts(quota: int) -> tuple[int, int, int]:
    train = int(quota * 0.85)
    validation = int(quota * 0.10)
    return train, validation, quota - train - validation


def latest_run(log_dir: Path, mode: str) -> Path | None:
    candidates = sorted(log_dir.glob(f"{mode}_*.run.json"))
    return candidates[-1] if candidates else None


def run_context(root: Path, run: dict[str, Any]) -> tuple[dict[str, Any], str, str, Path]:
    config = yaml.safe_load(Path(run["config"]["path"]).read_text(encoding="utf-8"))
    overrides = dict(item.split("=", 1) for item in run["config"]["overrides"] if "=" in item)
    experiment = overrides.get("experiment_name", config["experiment_name"])
    trial = overrides.get("trial_name", config["trial_name"])
    merged_log = root / "artifacts/areal/logs/chengjin" / experiment / trial / "merged.log"
    return config, experiment, trial, merged_log


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument("--run-metadata", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "docs/StudyHub_Open_SFT_Training_Report.html",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.project.resolve()
    log_dir = root / "artifacts/areal/launcher_logs"
    run_path = args.run_metadata or latest_run(log_dir, "pilot") or latest_run(log_dir, "gate")
    if run_path is None:
        raise FileNotFoundError("No run metadata found")
    run_path = run_path.resolve()
    run = json.loads(run_path.read_text(encoding="utf-8"))
    registry = json.loads((root / "data_registry/open_sft_sources.json").read_text(encoding="utf-8"))
    dataset = run["dataset_manifest"]
    candidate_manifest = Path(
        dataset.get(
            "candidate_manifest",
            root / "datasets/interim/open_sft_bootstrap_v1/candidates.manifest.json",
        )
    )
    candidates = json.loads(candidate_manifest.read_text(encoding="utf-8"))
    journal_path = root / "artifacts/areal/experiment_journal.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.is_file() else {"events": []}
    dataset_audit_path = root / "artifacts/areal/dataset-audit-v2.json"
    dataset_audit = (
        json.loads(dataset_audit_path.read_text(encoding="utf-8"))
        if dataset_audit_path.is_file()
        else None
    )
    config, experiment, trial, merged_log = run_context(root, run)
    metrics = parse_metrics(merged_log)
    engine_elapsed = parse_training_elapsed(merged_log)
    gpu_rows = read_gpu_csv(Path(run["gpu_csv"]))
    checkpoints = checkpoint_rows(root, experiment, trial)
    reload_files = sorted(log_dir.glob(f"{run_path.stem.removesuffix('.run')}*.reload*.json"))
    reload_result = json.loads(reload_files[-1].read_text(encoding="utf-8")) if reload_files else None

    status = "完成" if run.get("exit_status") == 0 else ("运行中" if "exit_status" not in run else "失败")
    status_class = "ok" if status == "完成" else ("live" if status == "运行中" else "bad")
    sampled_peak_memory = max((row["memory"] for row in gpu_rows), default=0)
    sampled_peak_util = max((row["util"] for row in gpu_rows), default=0)
    peak_memory = run.get("resource_summary", {}).get("peak_memory_used_mib") or sampled_peak_memory
    peak_util = run.get("resource_summary", {}).get("peak_utilization_gpu_pct") or sampled_peak_util
    started = datetime.fromisoformat(run["started_at"])
    finished = datetime.fromisoformat(run["finished_at"]) if run.get("finished_at") else None
    duration = str(finished - started).split(".")[0] if finished else "尚未结束"
    final_metrics = metrics[-1] if metrics else {}
    loss_points = [(row["step"], row["sft/loss/avg"]) for row in metrics if "sft/loss/avg" in row]
    eval_points = [
        (row["step"], row[key])
        for row in metrics
        for key in ("sft-eval/loss/avg", "sft_eval/loss/avg")
        if key in row
    ]
    latest_eval_loss = eval_points[-1][1] if eval_points else None
    eval_loss_reduction = (
        (eval_points[0][1] - eval_points[-1][1]) / eval_points[0][1] * 100
        if len(eval_points) > 1 and eval_points[0][1]
        else None
    )
    latest_eval_ppl = next(
        (row["sft-eval/ppl/avg"] for row in reversed(metrics) if "sft-eval/ppl/avg" in row),
        None,
    )
    eval_by_step = {int(step): loss for step, loss in eval_points}
    for checkpoint in checkpoints:
        checkpoint["validation_loss"] = eval_by_step.get(checkpoint["reported_step"])
    best_eval_step, best_eval_loss = min(eval_points, key=lambda point: point[1]) if eval_points else (None, None)
    train_sequences = int(sum(row.get("sft/n_seqs", 0) for row in metrics))
    train_tokens = int(sum(row.get("sft/n_tokens", 0) for row in metrics))
    loss_tokens = int(sum(row.get("sft/n_valid_tokens", 0) for row in metrics))
    successful_updates = int(sum(row.get("sft/update_successful", 0) for row in metrics))
    throughput = train_tokens / engine_elapsed if engine_elapsed else None
    baseline = None
    if dataset["schema_version"].endswith(".v2"):
        for candidate_path in reversed(sorted(log_dir.glob("pilot_*.run.json"))):
            if candidate_path.resolve() == run_path:
                continue
            candidate_run = json.loads(candidate_path.read_text(encoding="utf-8"))
            if candidate_run.get("exit_status") != 0:
                continue
            if not candidate_run.get("dataset_manifest", {}).get("schema_version", "").endswith(".v1"):
                continue
            _, _, candidate_trial, candidate_log = run_context(root, candidate_run)
            candidate_metrics = parse_metrics(candidate_log)
            candidate_eval = [
                (row["step"], row[key])
                for row in candidate_metrics
                for key in ("sft-eval/loss/avg", "sft_eval/loss/avg")
                if key in row
            ]
            baseline = {
                "trial": candidate_trial,
                "eval_points": candidate_eval,
                "last_eval_loss": candidate_eval[-1][1] if candidate_eval else None,
            }
            break
    metric_series = [
        ("v2 train loss", loss_points, "#2f7d62"),
        ("v2 validation loss", eval_points, "#d3a73c"),
    ]
    if baseline and baseline["eval_points"]:
        metric_series.append(("v1 validation (discarded split)", baseline["eval_points"], "#7c827d"))
    memory_points = [(index, row["memory"] / 1024) for index, row in enumerate(gpu_rows)]
    util_points = [(index, row["util"]) for index, row in enumerate(gpu_rows)]
    power_points = [(index, row["power"]) for index, row in enumerate(gpu_rows)]
    average_power = sum(row["power"] for row in gpu_rows) / len(gpu_rows) if gpu_rows else 0
    peak_power = max((row["power"] for row in gpu_rows), default=0)

    source_rows = []
    source_hash_details = []
    for source in registry["sources"]:
        quota = dataset["source_quotas"][source["id"]]
        if "source_split_counts" in dataset:
            counts = dataset["source_split_counts"][source["id"]]
            train_count, validation_count, test_count = (
                counts["train"],
                counts["validation"],
                counts["test"],
            )
        else:
            train_count, validation_count, test_count = source_split_counts(quota)
        first_hash = next((value for value in source["files"].values() if value), "-")
        source_rows.append(
            f'<tr><td><strong><a href="{esc(source["source_url"])}">{esc(source["id"])}</a></strong>'
            f"<small>{esc(source['attribution'])}</small></td>"
            f"<td>{esc(source['license'])}</td><td><code>{esc(source['revision'][:12])}</code></td>"
            f"<td>{candidates['source_counts'][source['id']]:,}</td><td>{quota:,}</td>"
            f"<td>{train_count}/{validation_count}/{test_count}</td><td><code>{esc(first_hash[:14])}…</code></td></tr>"
        )
        file_hashes = "".join(
            f"<tr><td>{esc(filename)}</td><td><code>{esc(file_hash)}</code></td></tr>"
            for filename, file_hash in source["files"].items()
            if file_hash
        )
        source_hash_details.append(
            f"<details><summary>{esc(source['id'])} · raw file fingerprints</summary>"
            f"<table><tbody>{file_hashes}</tbody></table></details>"
        )

    event_rows = []
    for event in journal["events"]:
        event_rows.append(
            f'<article class="event {esc(event["status"])}"><time>{esc(event["time"][5:16].replace("T", " "))}</time>'
            f'<div><span class="event-stage">{esc(event["stage"])}</span><h3>{esc(event["summary"])}</h3>'
            f'<p>{esc(event["detail"])}</p></div></article>'
        )

    metric_rows = []
    for row in metrics:
        eval_loss = row.get("sft-eval/loss/avg", row.get("sft_eval/loss/avg"))
        eval_cell = f"<td>{eval_loss:.4f}</td>" if eval_loss is not None else "<td>—</td>"
        metric_rows.append(
            "<tr>"
            f"<td>{int(row['step'])}</td>"
            f"<td>{row.get('sft/loss/avg', float('nan')):.4f}</td>"
            f"{eval_cell}"
        )
        metric_rows[-1] += (
            f"<td>{row.get('sft/ppl/avg', float('nan')):.4f}</td>"
            f"<td>{row.get('sft/grad_norm', float('nan')):.4f}</td>"
            f"<td>{row.get('sft/lr', float('nan')):.3e}</td>"
            f"<td>{int(row.get('sft/n_tokens', 0)):,}</td>"
            f"<td>{int(row.get('sft/n_valid_tokens', 0)):,}</td>"
            "</tr>"
        )
    checkpoint_table = "".join(
        f"<tr><td>{esc(item['step'])}</td>"
        f"<td>{f'{item['validation_loss']:.6f}' if item['validation_loss'] is not None else '—'}</td>"
        f"<td>{human_bytes(item['bytes'])}</td>"
        f"<td><code>{esc(item['sha256'])}</code></td><td><code>{esc(item['path'])}</code></td></tr>"
        for item in checkpoints
    ) or '<tr><td colspan="5">当前尚无 checkpoint</td></tr>'
    run_files = [
        Path(run["log_file"]),
        merged_log,
        Path(run["gpu_csv"]),
        run_path,
        journal_path,
        dataset_audit_path,
    ]
    run_file_table = "".join(
        f"<tr><td>{esc(path.name)}</td><td>{human_bytes(path.stat().st_size)}</td>"
        f"<td><code>{sha256(path)}</code></td><td><code>{esc(path.relative_to(root))}</code></td></tr>"
        for path in run_files
        if path.is_file()
    )

    reload_html = (
        f'<div class="callout ok"><b>重载通过</b><span>adapter {esc(reload_result["adapter_sha256"][:16])}… · '
        f'峰值 {reload_result["peak_memory_allocated_mib"]:,.2f} MiB · 输出“{esc(reload_result["generation"])}”</span></div>'
        if reload_result
        else '<div class="callout">当前 run 尚未执行独立重载验证。</div>'
    )
    overlap = dataset.get("group_overlap")
    split_audit_html = (
        '<div class="callout ok"><b>分组泄漏检查通过</b><span>'
        f'Train-Val {overlap["train_validation"]} · Train-Test {overlap["train_test"]} · '
        f'Val-Test {overlap["validation_test"]} 个重叠 group'
        + (
            f' · {dataset_audit["unique_ids"]:,} 个唯一 ID / '
            f'{dataset_audit["unique_content_hashes"]:,} 个唯一内容哈希'
            if dataset_audit and dataset_audit.get("status") == "passed"
            else ""
        )
        + "</span></div>"
        if overlap is not None
        else '<div class="callout"><b>旧版划分</b><span>该运行未记录语义文档 group overlap；仅用于接线基线。</span></div>'
    )
    baseline_html = (
        '<div class="callout"><b>v1 对照</b><span>'
        f'{esc(baseline["trial"])} · 最后验证 loss '
        f'{baseline["last_eval_loss"]:.6f}；因 QASPER 论文跨 split，只作为工程基线。</span></div>'
        if baseline and baseline["last_eval_loss"] is not None
        else ""
    )

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyHub 2B Open SFT 训练报告</title>
<style>
:root{{--paper:#f3f0e6;--ink:#18221d;--muted:#667168;--green:#2f7d62;--green2:#4a9d7a;--gold:#d3a73c;--line:#c9c7bb;--red:#a84b3f;--panel:#fbfaf5;--shadow:rgba(24,34,29,.09)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;color:var(--ink);background:var(--paper);font-family:"IBM Plex Sans","Noto Sans CJK SC","Microsoft YaHei",sans-serif;line-height:1.65}}
body:before{{content:"";position:fixed;inset:0;pointer-events:none;opacity:.28;background-image:linear-gradient(rgba(47,125,98,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(47,125,98,.055) 1px,transparent 1px);background-size:32px 32px;mask-image:linear-gradient(to bottom,#000,transparent 70%)}}
a{{color:var(--green);text-decoration-thickness:1px;text-underline-offset:3px}}code{{font-family:"IBM Plex Mono","Cascadia Mono",monospace;font-size:.88em;word-break:break-all}}.shell{{max-width:1240px;margin:auto;padding:0 32px 96px;position:relative}}
header{{min-height:78vh;display:grid;align-content:center;border-bottom:1px solid var(--ink);position:relative}}.eyebrow{{letter-spacing:.18em;text-transform:uppercase;font-size:12px;font-weight:700;color:var(--green)}}
h1,h2,h3{{font-family:"Source Han Serif SC","Noto Serif CJK SC","STSong",serif;font-weight:600}}h1{{font-size:clamp(54px,8vw,112px);line-height:.92;letter-spacing:-.055em;margin:22px 0 30px;max-width:980px}}h1 span{{color:var(--green)}}
.lede{{font-size:clamp(18px,2vw,25px);max-width:780px;margin:0;color:#39433d}}.hero-meta{{display:flex;gap:14px;flex-wrap:wrap;margin-top:42px}}.pill{{border:1px solid var(--ink);border-radius:999px;padding:8px 14px;font-size:13px;background:rgba(251,250,245,.65)}}.pill.ok{{background:var(--green);color:white;border-color:var(--green)}}.pill.live{{background:var(--gold)}}.pill.bad{{background:var(--red);color:#fff;border-color:var(--red)}}
.index{{position:sticky;top:0;z-index:10;display:flex;gap:22px;overflow:auto;padding:15px 0;background:rgba(243,240,230,.93);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}}.index a{{white-space:nowrap;text-decoration:none;font-size:13px;color:var(--ink)}}
section{{padding:78px 0;border-bottom:1px solid var(--line);scroll-margin-top:54px}}.section-head{{display:grid;grid-template-columns:140px 1fr;gap:20px;margin-bottom:38px}}.section-no{{font-family:"IBM Plex Mono",monospace;color:var(--gold);font-size:13px}}h2{{font-size:clamp(34px,5vw,62px);line-height:1;margin:0;letter-spacing:-.035em}}h3{{margin:0 0 8px;font-size:21px}}p{{margin:0 0 16px}}.note{{max-width:830px;color:var(--muted)}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line)}}.kpi{{background:var(--panel);padding:26px}}.kpi b{{display:block;font-family:"Source Han Serif SC","STSong",serif;font-size:35px;line-height:1.1}}.kpi span{{font-size:12px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}.card{{background:rgba(251,250,245,.82);border:1px solid var(--line);padding:26px;box-shadow:0 14px 40px var(--shadow)}}.card.gold{{border-top:5px solid var(--gold)}}.card.green{{border-top:5px solid var(--green)}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:rgba(251,250,245,.68)}}th{{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--ink);padding:12px 10px}}td{{padding:13px 10px;border-bottom:1px solid var(--line);vertical-align:top}}td small{{display:block;color:var(--muted);margin-top:3px}}.table-scroll{{overflow:auto;border:1px solid var(--line)}}
details{{border-bottom:1px solid var(--line);background:rgba(251,250,245,.5)}}summary{{cursor:pointer;padding:14px 10px;font-size:13px;font-weight:700;color:var(--green)}}details table{{margin:0}}
.pipeline{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;counter-reset:pipeline}}.pipe{{min-height:150px;padding:18px;border:1px solid var(--line);background:var(--panel);position:relative}}.pipe:before{{counter-increment:pipeline;content:"0" counter(pipeline);color:var(--gold);font-family:monospace;font-size:12px}}.pipe b{{display:block;margin:24px 0 8px}}.pipe span{{color:var(--muted);font-size:13px}}
.event{{display:grid;grid-template-columns:150px 1fr;gap:24px;padding:22px 0;border-top:1px solid var(--line)}}.event time{{font-family:monospace;font-size:12px;color:var(--muted)}}.event-stage{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--green)}}.event h3{{font-family:inherit;font-size:16px;margin:2px 0 6px}}.event p{{font-size:13px;color:var(--muted);margin:0}}.event.failed{{border-left:3px solid var(--red);padding-left:18px}}.event.passed{{border-left:3px solid var(--green);padding-left:18px}}.event.blocked{{border-left:3px solid var(--gold);padding-left:18px}}
.chart-wrap{{border:1px solid var(--line);background:var(--panel);padding:18px;margin-top:18px;overflow:auto}}.chart{{width:100%;min-width:680px;height:auto}}.chart text{{font-family:"IBM Plex Mono",monospace;font-size:10px;fill:var(--muted)}}.chart .grid{{stroke:#dedbd0;stroke-width:1}}.chart .axis{{stroke:var(--ink);stroke-width:1}}.chart .threshold{{stroke:var(--red);stroke-dasharray:7 6}}.chart .threshold-label{{fill:var(--red)}}.chart-legend{{display:flex;gap:18px;font-size:12px;margin-bottom:4px}}.chart-legend i{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px}}.empty-chart{{padding:70px;text-align:center;color:var(--muted)}}
.callout{{display:flex;justify-content:space-between;gap:20px;padding:18px;border:1px solid var(--line);margin:18px 0;background:var(--panel)}}.callout.ok{{border-color:var(--green);box-shadow:inset 5px 0 var(--green)}}.callout span{{color:var(--muted);font-size:13px}}pre{{padding:22px;background:#17211c;color:#e9eadf;overflow:auto;border-left:5px solid var(--gold);font:12px/1.7 "IBM Plex Mono","Cascadia Mono",monospace}}
.fineprint{{font-size:12px;color:var(--muted)}}footer{{padding-top:50px;display:flex;justify-content:space-between;color:var(--muted);font-size:12px}}
@media(max-width:820px){{.shell{{padding:0 18px 60px}}header{{min-height:70vh}}.section-head{{grid-template-columns:1fr}}.kpis{{grid-template-columns:1fr 1fr}}.grid-2{{grid-template-columns:1fr}}.pipeline{{grid-template-columns:1fr}}.event{{grid-template-columns:1fr;gap:5px}}}}
@media print{{body:before,.index{{display:none}}.shell{{max-width:none;padding:0}}header{{min-height:auto;padding:80px 0}}section{{break-inside:avoid;padding:40px 0}}.kpi b{{font-size:26px}}}}
</style>
</head>
<body><div class="shell">
<header id="top">
  <div class="eyebrow">StudyHub Agent · Training Record / 2026.08.24</div>
  <h1>2B Open SFT<br><span>训练报告</span></h1>
  <p class="lede">基于 AReaL 原生 SFT、Qwen3.5-2B 与五类开放数据完成的单卡 LoRA Pilot。本文由数据清单、运行日志、GPU 采样和 checkpoint 自动汇总。</p>
  <div class="hero-meta"><span class="pill {status_class}">{status}</span><span class="pill">trial · {esc(trial)}</span><span class="pill">Git · {esc(run['git']['commit'][:10])}</span><span class="pill">生成于 · {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}</span></div>
</header>
<nav class="index"><a href="#scope">任务</a><a href="#data">数据</a><a href="#compile">编译</a><a href="#recipe">配方</a><a href="#timeline">运行记录</a><a href="#metrics">指标</a><a href="#resource">资源</a><a href="#artifacts">产物</a><a href="#reproduce">复现</a></nav>

<section id="scope"><div class="section-head"><span class="section-no">01 / Scope</span><h2>训练任务</h2></div>
<div class="kpis"><div class="kpi"><b>{dataset['split_counts']['train']:,}</b><span>Train samples</span></div><div class="kpi"><b>{int(final_metrics.get('step',0))}/{int(final_metrics.get('total_steps',159))}</b><span>Completed steps</span></div><div class="kpi"><b>{peak_memory/1024:.2f} GiB</b><span>Peak GPU memory</span></div><div class="kpi"><b>{duration}</b><span>Wall clock</span></div></div>
<div class="grid-2" style="margin-top:24px"><div class="card green"><h3>本轮目标</h3><p>验证开放数据下载、规范化、assistant-only loss mask、AReaL FSDP LoRA、checkpoint 保存与重载的完整链路，并形成可复现实验记录。</p></div><div class="card gold"><h3>结果边界</h3><p>这是 2B 接线与开放数据 bootstrap，不是最终 StudyHub Agent 模型。最终 4B SFT 仍应以 StudyHub 原生、可 replay 轨迹为主，通用开放数据占比不超过 30%。</p></div></div>
<div class="table-scroll" style="margin-top:24px"><table><thead><tr><th>项目</th><th>完整方案建议</th><th>本轮实跑</th></tr></thead><tbody><tr><td>Student</td><td>Qwen3.5-4B</td><td>Qwen3.5-2B 兼容性 Pilot</td></tr><tr><td>数据</td><td>1,500–3,000 条经过 verifier 的 StudyHub/Hermes 轨迹</td><td>3,000 条许可明确的开放数据 bootstrap</td></tr><tr><td>序列长度</td><td>8,192 + trajectory-aware segmentation</td><td>2,048；超长样本丢弃，不截断观察链</td></tr><tr><td>运行时</td><td>Hermes tool-loop + 冻结 RAG/Web/Memory</td><td>AReaL 原生 SFT 张量路径，不执行外部工具</td></tr><tr><td>评估</td><td>Base/SFT AgentBench、grounding、tool validity</td><td>验证 loss、资源、保存与独立重载；测试集封存</td></tr><tr><td>后训练</td><td>同一 SFT checkpoint 分叉 GRPO / OPD / KDRL</td><td>未进入 RL</td></tr></tbody></table></div>
</section>

<section id="data"><div class="section-head"><span class="section-no">02 / Data</span><h2>开放数据与许可</h2></div><p class="note">下载器固定 Hugging Face revision 或数据版本，并在训练前校验 SHA-256。原始文件与处理结果不进入 Git，登记表和转换代码进入版本控制。</p>
<div class="table-scroll"><table><thead><tr><th>来源</th><th>许可</th><th>Revision</th><th>候选池</th><th>采用</th><th>Train/Val/Test</th><th>Raw SHA</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></div>
<div style="margin-top:16px">{''.join(source_hash_details)}</div>
<div class="callout"><b>COIG 使用约束</b><span>只读取 exam_instructions 子集；保留数据集顶层 Apache-2.0 与内部混合来源说明，不扩展到 web-crawled 子集。</span></div>
{split_audit_html}
</section>

<section id="compile"><div class="section-head"><span class="section-no">03 / Compile</span><h2>数据编译</h2></div>
<div class="pipeline"><div class="pipe"><b>Raw record</b><span>原始 JSON / JSONL / Parquet / QASPER v0.3</span></div><div class="pipe"><b>Normalize</b><span>角色统一、文本清理、来源字段和 attribution</span></div><div class="pipe"><b>Ground</b><span>2Wiki supporting facts；QASPER evidence；不伪造 tool observation</span></div><div class="pipe"><b>Group split</b><span>来源分层 + 语义文档分组；85 / 10 / 5；跨源内容 hash 去重</span></div><div class="pipe"><b>AReaL tensors</b><span>Qwen chat template → input_ids + assistant-only loss_mask</span></div></div>
<div class="grid-2" style="margin-top:24px"><div class="card"><h3>长度与筛选</h3><table><tr><td>最大长度</td><td>{dataset['max_length']} token</td></tr><tr><td>P50 / P95</td><td>{dataset['token_length']['p50']} / {dataset['token_length']['p95']}</td></tr><tr><td>实际最大</td><td>{dataset['token_length']['max']}</td></tr><tr><td>超长丢弃</td><td>{sum(dataset['drop_counts'].values())} 条</td></tr><tr><td>编译 token</td><td>{f'{dataset_audit["token_stats"]["all_tokens"]:,}' if dataset_audit else '未审计'}</td></tr><tr><td>规范化输入 SHA</td><td><code>{esc(dataset['input_sha256'])}</code></td></tr></table></div><div class="card"><h3>Loss mask</h3><p>system、user、tool result、retrieved evidence 与 memory observation 为 0；assistant reasoning、tool call 和 final answer 为 1。</p><p><b>{dataset['assistant_token_fraction']*100:.2f}%</b> 的编译 token 参与 causal cross-entropy，避免模型学习复述用户输入和工具观察。</p><p>测试集 150 条保持封存，本轮只用训练集更新参数，并在验证集上周期评估。</p></div></div>
</section>

<section id="recipe"><div class="section-head"><span class="section-no">04 / Recipe</span><h2>模型与训练配方</h2></div>
<div class="grid-2"><div class="card green"><h3>模型与参数</h3><table><tr><td>Base</td><td>Qwen3.5-2B · Apache-2.0</td></tr><tr><td>总参数</td><td>2,236,581,696</td></tr><tr><td>可训练参数</td><td>23,340,032（1.0436%）</td></tr><tr><td>LoRA</td><td>r16 / alpha16 / all-linear</td></tr><tr><td>精度</td><td>BF16</td></tr><tr><td>Attention</td><td>SDPA</td></tr><tr><td>Checkpointing</td><td>Gradient checkpointing</td></tr></table></div><div class="card gold"><h3>优化配置</h3><table><tr><td>Engine</td><td>AReaL FSDP d1p1t1</td></tr><tr><td>Seed</td><td>1</td></tr><tr><td>Global batch</td><td>16</td></tr><tr><td>Microbatch</td><td>≤ 2048 token</td></tr><tr><td>Optimizer</td><td>Adam / β=(0.9, 0.95) / eps 1e-5</td></tr><tr><td>LR / schedule</td><td>2e-5 / cosine / 3% warmup</td></tr><tr><td>Weight decay / clip</td><td>0.05 / 1.0</td></tr><tr><td>Save / Eval</td><td>每 40 step + epoch end</td></tr><tr><td>Epoch</td><td>1 · 159 steps</td></tr></table></div></div>
<div class="callout"><b>环境锁定</b><span>AReaL {esc(run['software']['areal'])} @ {esc(run['areal_upstream']['commit'][:12])} · torch {esc(run['software']['torch'])} · transformers {esc(run['software']['transformers'])} · peft {esc(run['software']['peft'])} · Python 3.12 · HF/Transformers offline · W&amp;B disabled</span></div>
</section>

<section id="timeline"><div class="section-head"><span class="section-no">05 / Journal</span><h2>运行记录</h2></div><p class="note">失败尝试不删除。每个失败均说明发生阶段、是否占用 GPU、修复方式和对应原始日志。</p>{''.join(event_rows)}</section>

<section id="metrics"><div class="section-head"><span class="section-no">06 / Metrics</span><h2>训练指标</h2></div>
<div class="kpis"><div class="kpi"><b>{train_sequences:,}</b><span>Sequences consumed</span></div><div class="kpi"><b>{train_tokens:,}</b><span>Train tokens</span></div><div class="kpi"><b>{loss_tokens:,}</b><span>Loss tokens</span></div><div class="kpi"><b>{successful_updates:,}</b><span>Successful updates</span></div></div>
{line_chart(metric_series,y_label='loss')}
<div class="callout"><b>验证摘要</b><span>最近 {f'{latest_eval_loss:.6f}' if latest_eval_loss is not None else '尚未运行'} · 最佳 {f'{best_eval_loss:.6f} @ step {int(best_eval_step)}' if best_eval_loss is not None else '尚未产生'} · {f'较首次下降 {eval_loss_reduction:.2f}%' if eval_loss_reduction is not None else '等待第二次验证'} · {f'validation PPL {latest_eval_ppl:.4f}' if latest_eval_ppl is not None else 'PPL 尚未产生'} · {len(eval_points)} 次 validation · {f'{engine_elapsed:.2f} 秒 / {throughput:.2f} train token/s' if throughput is not None else '训练进行中'}。训练 loss 为动态 batch 的逐步值，不用单个 step 判断收敛。</span></div>
{baseline_html}
<div class="table-scroll" style="margin-top:24px"><table><thead><tr><th>Step</th><th>Train loss</th><th>Validation loss</th><th>PPL</th><th>Grad norm</th><th>LR</th><th>Tokens</th><th>Loss tokens</th></tr></thead><tbody>{''.join(metric_rows) if metric_rows else '<tr><td colspan="8">训练尚未输出 step 指标</td></tr>'}</tbody></table></div>
</section>

<section id="resource"><div class="section-head"><span class="section-no">07 / Resource</span><h2>资源占用</h2></div>
<div class="kpis"><div class="kpi"><b>{peak_memory or 0:,} MiB</b><span>Peak memory</span></div><div class="kpi"><b>{peak_util or 0}%</b><span>Peak utilization</span></div><div class="kpi"><b>1 / 2</b><span>GPUs used</span></div><div class="kpi"><b>28 GiB</b><span>Hard stop</span></div></div>
{line_chart([('GPU 0 memory (GiB)',memory_points,'#2f7d62')],y_label='GiB',threshold=28)}
{line_chart([('GPU 0 utilization (%)',util_points,'#d3a73c')],y_label='%')}
{line_chart([('GPU 0 power (W)',power_points,'#7c827d')],y_label='W')}
<p class="fineprint">设备：{esc(run['hardware'])}。共 {len(gpu_rows)} 个 5 秒采样，平均/峰值功耗 {average_power:.2f}/{peak_power:.2f} W。启动前要求至少 60,000 MiB 空闲；检测到非当前用户的 GPU 进程时，仅终止 StudyHub 自身进程组。GPU 1 未设置到 CUDA_VISIBLE_DEVICES。</p>
</section>

<section id="artifacts"><div class="section-head"><span class="section-no">08 / Artifacts</span><h2>Checkpoint 与重载</h2></div>{reload_html}
<div class="table-scroll"><table><thead><tr><th>Checkpoint</th><th>Validation loss</th><th>Size</th><th>SHA-256</th><th>Path</th></tr></thead><tbody>{checkpoint_table}</tbody></table></div>
<div class="callout"><b>Base fingerprint</b><span>{esc(run['model']['weight_files'][0]['sha256'])} · {human_bytes(run['model']['weight_files'][0]['bytes'])}</span></div>
<div class="table-scroll"><table><thead><tr><th>复现对象</th><th>SHA-256 / Commit</th></tr></thead><tbody><tr><td>训练配置</td><td><code>{esc(run['config']['sha256'])}</code></td></tr><tr><td>Dataset manifest</td><td><code>{esc(run['dataset_manifest_sha256'])}</code></td></tr><tr><td>候选池 manifest</td><td><code>{esc(dataset.get('candidate_manifest_sha256', '旧版未记录'))}</code></td></tr><tr><td>Base model config</td><td><code>{esc(run['model']['config_sha256'])}</code></td></tr><tr><td>AReaL upstream</td><td><code>{esc(run['areal_upstream']['commit'])}</code></td></tr><tr><td>StudyHub Git</td><td><code>{esc(run['git']['commit'])}</code></td></tr></tbody></table></div>
<h3 style="margin-top:30px">原始运行文件</h3><div class="table-scroll"><table><thead><tr><th>文件</th><th>Size</th><th>SHA-256</th><th>Path</th></tr></thead><tbody>{run_file_table}</tbody></table></div>
</section>

<section id="reproduce"><div class="section-head"><span class="section-no">09 / Reproduce</span><h2>复现步骤</h2></div>
<pre>cd /data/chengjin/studyhub/studyhub-agent

# 1. 下载并校验开放数据（只使用 127.0.0.1:7892）
.venv-train/bin/python scripts/data/download_open_sft_sources.py

# 2. 规范化候选池并编译 AReaL DatasetDict
.venv-train/bin/python scripts/data/build_open_sft_bootstrap.py
.venv-train/bin/python scripts/data/tokenize_areal_sft.py --overwrite
.venv-train/bin/python scripts/data/verify_open_sft_dataset.py

# 3. 固定 AReaL commit 与 uv.lock
scripts/train/setup_areal_env.sh

# 4. 单步 Gate；通过后运行完整 Pilot
scripts/train/run_low_memory_areal_sft.sh gate
scripts/train/run_low_memory_areal_sft.sh pilot

# 5. 生成本报告
.venv-train/bin/python scripts/train/generate_training_report.py</pre>
<p class="fineprint">原始数据、私有环境、GPU CSV、完整日志、模型和 checkpoint 均由 Git 忽略；代码、配置、数据登记表、上游锁和 HTML 报告可进入版本控制。</p>
</section>
<footer><span>StudyHub Agent · Open SFT Pilot</span><a href="#top">返回顶部 ↑</a></footer>
</div></body></html>"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": status,
                "metric_steps": len(metrics),
                "gpu_samples": len(gpu_rows),
                "checkpoints": len(checkpoints),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
