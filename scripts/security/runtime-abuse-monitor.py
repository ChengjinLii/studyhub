#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen


ACCESS_PATTERN = re.compile(
    r'^(?P<ip>\S+) .* \[(?P<timestamp>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) [^"]+" '
    r'(?P<status>\d{3}) '
)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check recent StudyHub traffic and host pressure.")
    parser.add_argument("--access-log", default="/var/log/nginx/access.log")
    parser.add_argument("--status-file")
    parser.add_argument("--window-seconds", type=positive_int, default=300)
    parser.add_argument("--tail-lines", type=positive_int, default=100000)
    parser.add_argument("--requests-per-minute", type=positive_int, default=900)
    parser.add_argument("--requests-per-ip-minute", type=positive_int, default=300)
    parser.add_argument("--rate-limited", type=positive_int, default=20)
    parser.add_argument("--server-errors", type=positive_int, default=20)
    parser.add_argument("--active-connections", type=positive_int, default=800)
    parser.add_argument("--available-memory-mb", type=positive_int, default=256)
    parser.add_argument("--load-one", type=float, default=8.0)
    parser.add_argument("--fail-on-alert", action="store_true")
    return parser.parse_args()


def tail_lines(path: Path, maximum: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunks: list[bytes] = []
        line_count = 0
        while position > 0 and line_count <= maximum:
            size = min(65536, position)
            position -= size
            handle.seek(position)
            chunk = handle.read(size)
            chunks.append(chunk)
            line_count += chunk.count(b"\n")
    return b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()[-maximum:]


def active_connections() -> int | None:
    request = Request("http://127.0.0.1/nginx_status", headers={"Host": "127.0.0.1"})
    try:
        with urlopen(request, timeout=2) as response:
            first_line = response.read(256).decode("ascii", errors="replace").splitlines()[0]
    except Exception:
        return None
    match = re.search(r"Active connections:\s*(\d+)", first_line)
    return int(match.group(1)) if match else None


def available_memory_mb() -> int | None:
    try:
        values = Path("/proc/meminfo").read_text(encoding="ascii").splitlines()
    except OSError:
        return None
    for line in values:
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return None


def write_status(path: str | None, payload: dict[str, object]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def main() -> int:
    args = parse_args()
    now = datetime.now().astimezone()
    cutoff = now - timedelta(seconds=args.window_seconds)
    per_minute: Counter[str] = Counter()
    per_ip_minute: Counter[tuple[str, str]] = Counter()
    statuses: Counter[int] = Counter()
    rate_limited = 0
    parsed_requests = 0

    for line in tail_lines(Path(args.access_log), args.tail_lines):
        match = ACCESS_PATTERN.match(line)
        if not match:
            continue
        try:
            timestamp = datetime.strptime(match.group("timestamp"), "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            continue
        if timestamp < cutoff:
            continue
        minute = timestamp.strftime("%Y-%m-%dT%H:%M")
        status = int(match.group("status"))
        ip = match.group("ip")
        parsed_requests += 1
        per_minute[minute] += 1
        per_ip_minute[(ip, minute)] += 1
        statuses[status] += 1
        if status == 429 or "limit_req=REJECTED" in line or "limit_conn=REJECTED" in line:
            rate_limited += 1

    peak_requests = max(per_minute.values(), default=0)
    peak_ip_requests = max(per_ip_minute.values(), default=0)
    server_errors = sum(count for status, count in statuses.items() if status >= 500)
    connections = active_connections()
    memory_mb = available_memory_mb()
    load_one = os.getloadavg()[0]
    alerts: list[str] = []

    if peak_requests >= args.requests_per_minute:
        alerts.append(f"requests_per_minute={peak_requests}")
    if peak_ip_requests >= args.requests_per_ip_minute:
        alerts.append(f"requests_per_ip_minute={peak_ip_requests}")
    if rate_limited >= args.rate_limited:
        alerts.append(f"rate_limited={rate_limited}")
    if server_errors >= args.server_errors:
        alerts.append(f"server_errors={server_errors}")
    if connections is not None and connections >= args.active_connections:
        alerts.append(f"active_connections={connections}")
    if memory_mb is not None and memory_mb <= args.available_memory_mb:
        alerts.append(f"available_memory_mb={memory_mb}")
    if load_one >= args.load_one:
        alerts.append(f"load_one={load_one:.2f}")

    payload: dict[str, object] = {
        "checkedAt": now.isoformat(),
        "windowSeconds": args.window_seconds,
        "requests": parsed_requests,
        "peakRequestsPerMinute": peak_requests,
        "peakRequestsPerIpMinute": peak_ip_requests,
        "rateLimited": rate_limited,
        "serverErrors": server_errors,
        "activeConnections": connections,
        "availableMemoryMb": memory_mb,
        "loadOne": round(load_one, 2),
        "alerts": alerts,
    }
    write_status(args.status_file, payload)
    prefix = "SECURITY_ALERT" if alerts else "security_monitor_ok"
    print(f"{prefix} {json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}")
    return 2 if alerts and args.fail_on_alert else 0


if __name__ == "__main__":
    sys.exit(main())
