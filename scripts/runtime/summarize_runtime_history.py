#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from typing import Any


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def load_history(history_dir: Path) -> tuple[list[dict[str, Any]], int]:
    samples: list[dict[str, Any]] = []
    malformed = 0
    for path in sorted(history_dir.glob("runtime-history-????-??-??.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    payload = json.loads(line)
                    checked_at = datetime.fromisoformat(str(payload["checkedAt"]))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    malformed += 1
                    continue
                if not isinstance(payload, dict):
                    malformed += 1
                    continue
                payload["_checkedAt"] = checked_at
                samples.append(payload)
    samples.sort(key=lambda item: item["_checkedAt"])
    return samples, malformed


def _root_disk_percent(sample: dict[str, Any]) -> float:
    filesystems = sample.get("filesystems")
    if not isinstance(filesystems, list):
        return 0.0
    for item in filesystems:
        if isinstance(item, dict) and item.get("path") == "/":
            return _number(item.get("diskUsedPercent"))
    return 0.0


def summarize(samples: list[dict[str, Any]], *, days: int, malformed_lines: int = 0) -> dict[str, Any]:
    if days < 1:
        raise ValueError("days must be positive")
    if not samples:
        return {"range": None, "sampleCount": 0, "malformedLineCount": malformed_lines, "days": []}

    latest_date = max(item["_checkedAt"].date() for item in samples)
    cutoff = latest_date - timedelta(days=days - 1)
    selected = [item for item in samples if item["_checkedAt"].date() >= cutoff]
    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        by_date[item["_checkedAt"].date()].append(item)

    daily: list[dict[str, Any]] = []
    previous_process_start: float | None = None
    previous_requests: float | None = None
    previous_errors: float | None = None
    for day, day_samples in sorted(by_date.items()):
        requests_per_minute = [_number(item.get("peakRequestsPerMinute")) for item in day_samples]
        cpu_values = [_number(item.get("cpuPercent")) for item in day_samples]
        observed_request_delta = 0
        observed_error_delta = 0
        restarts = 0
        for item in day_samples:
            application = item.get("application") if isinstance(item.get("application"), dict) else {}
            process_start = _number(application.get("processStartTimeSeconds"), -1)
            requests_total = _number(application.get("requestsTotal"), -1)
            errors_total = _number(application.get("serverErrorsTotal"), -1)
            if process_start >= 0 and previous_process_start is not None and process_start != previous_process_start:
                restarts += 1
            if process_start >= 0 and process_start == previous_process_start:
                if requests_total >= 0 and previous_requests is not None:
                    observed_request_delta += max(0, int(requests_total - previous_requests))
                if errors_total >= 0 and previous_errors is not None:
                    observed_error_delta += max(0, int(errors_total - previous_errors))
            previous_process_start = process_start if process_start >= 0 else None
            previous_requests = requests_total if requests_total >= 0 else None
            previous_errors = errors_total if errors_total >= 0 else None

        daily.append({
            "date": day.isoformat(),
            "sampleCount": len(day_samples),
            "peakRequestsPerMinute": int(max(requests_per_minute, default=0)),
            "p95PeakRequestsPerMinute": int(_percentile(requests_per_minute, 0.95)),
            "peakRequestsPerIpMinute": int(max((_number(item.get("peakRequestsPerIpMinute")) for item in day_samples), default=0)),
            "maxRateLimitedWindow": int(max((_number(item.get("rateLimited")) for item in day_samples), default=0)),
            "maxServerErrorsWindow": int(max((_number(item.get("serverErrors")) for item in day_samples), default=0)),
            "observedApplicationRequestDelta": observed_request_delta,
            "observedApplicationErrorDelta": observed_error_delta,
            "applicationRestartCount": restarts,
            "minAvailableMemoryMb": int(min((_number(item.get("availableMemoryMb")) for item in day_samples), default=0)),
            "maxLoadOne": round(max((_number(item.get("loadOne")) for item in day_samples), default=0), 2),
            "p95CpuPercent": round(_percentile(cpu_values, 0.95), 2),
            "maxRootDiskUsedPercent": round(max((_root_disk_percent(item) for item in day_samples), default=0), 2),
            "alertSampleCount": sum(bool(item.get("alerts")) for item in day_samples),
            "probeFailureSampleCount": sum(
                any(value is not None for value in item.get("probes", {}).values())
                for item in day_samples
                if isinstance(item.get("probes"), dict)
            ),
            "inactiveServiceSampleCount": sum(
                any(value is not True for value in item.get("services", {}).values())
                for item in day_samples
                if isinstance(item.get("services"), dict)
            ),
        })

    return {
        "range": {"from": cutoff.isoformat(), "to": latest_date.isoformat()},
        "sampleCount": len(selected),
        "malformedLineCount": malformed_lines,
        "summary": {
            "peakRequestsPerMinute": max((item["peakRequestsPerMinute"] for item in daily), default=0),
            "peakRequestsPerIpMinute": max((item["peakRequestsPerIpMinute"] for item in daily), default=0),
            "maxServerErrorsWindow": max((item["maxServerErrorsWindow"] for item in daily), default=0),
            "applicationRestartCount": sum(item["applicationRestartCount"] for item in daily),
            "minAvailableMemoryMb": min((item["minAvailableMemoryMb"] for item in daily), default=0),
            "maxRootDiskUsedPercent": max((item["maxRootDiskUsedPercent"] for item in daily), default=0),
            "alertSampleCount": sum(item["alertSampleCount"] for item in daily),
        },
        "days": daily,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize privacy-safe StudyHub runtime history")
    parser.add_argument("--history-dir", type=Path, default=Path("/var/lib/studyhub-security/history"))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.history_dir.is_dir():
        raise SystemExit(f"history directory not found: {args.history_dir}")
    samples, malformed = load_history(args.history_dir)
    payload = summarize(samples, days=args.days, malformed_lines=malformed)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
