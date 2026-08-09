#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json
import os
from pathlib import Path
import re
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import time
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


def percentage(value: str) -> float:
    parsed = float(value)
    if parsed <= 0 or parsed > 100:
        raise argparse.ArgumentTypeError("must be greater than 0 and at most 100")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check recent StudyHub traffic and host pressure.")
    parser.add_argument("--access-log", default="/var/log/nginx/access.log")
    parser.add_argument("--status-file")
    parser.add_argument("--alert-state-file")
    parser.add_argument("--env-file")
    parser.add_argument("--alert-email", action="append", default=[])
    parser.add_argument("--alert-cooldown-seconds", type=positive_int, default=3600)
    parser.add_argument("--alert-retry-seconds", type=positive_int, default=300)
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--probe-url", action="append", default=[])
    parser.add_argument("--filesystem", action="append", default=[])
    parser.add_argument("--certificate-file")
    parser.add_argument("--certificate-expiry-days", type=positive_int, default=21)
    parser.add_argument("--window-seconds", type=positive_int, default=300)
    parser.add_argument("--tail-lines", type=positive_int, default=100000)
    parser.add_argument("--requests-per-minute", type=positive_int, default=900)
    parser.add_argument("--requests-per-ip-minute", type=positive_int, default=300)
    parser.add_argument("--rate-limited", type=positive_int, default=20)
    parser.add_argument("--server-errors", type=positive_int, default=20)
    parser.add_argument("--active-connections", type=positive_int, default=800)
    parser.add_argument("--available-memory-mb", type=positive_int, default=256)
    parser.add_argument("--load-one", type=float, default=8.0)
    parser.add_argument("--cpu-percent", type=percentage, default=90.0)
    parser.add_argument("--disk-used-percent", type=percentage, default=90.0)
    parser.add_argument("--inode-used-percent", type=percentage, default=90.0)
    parser.add_argument("--test-notification", action="store_true")
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


def _read_cpu_totals() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()
        values = [int(value) for value in fields[1:]]
    except (OSError, ValueError, IndexError):
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent(sample_seconds: float = 0.1) -> float | None:
    first = _read_cpu_totals()
    if first is None:
        return None
    time.sleep(sample_seconds)
    second = _read_cpu_totals()
    if second is None:
        return None
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(100.0 * (total_delta - idle_delta) / total_delta, 2)


def filesystem_usage(path: str) -> dict[str, float | str] | None:
    try:
        usage = shutil.disk_usage(path)
        stats = os.statvfs(path)
    except OSError:
        return None
    inode_total = stats.f_files
    return {
        "path": path,
        "diskUsedPercent": round(100.0 * usage.used / usage.total, 2) if usage.total else 0.0,
        "inodeUsedPercent": round(100.0 * (inode_total - stats.f_ffree) / inode_total, 2) if inode_total else 0.0,
    }


def certificate_days_remaining(path: str) -> float | None:
    try:
        certificate = ssl._ssl._test_decode_cert(path)  # type: ignore[attr-defined]
        expires = datetime.strptime(certificate["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except (KeyError, OSError, TypeError, ValueError, ssl.SSLError):
        return None
    return round((expires - datetime.now(timezone.utc)).total_seconds() / 86400, 2)


def service_is_active(name: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", name],
            check=False,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def probe_url(url: str) -> str | None:
    request = Request(url, headers={"User-Agent": "StudyHub-Runtime-Monitor/1.0"})
    try:
        with urlopen(request, timeout=5) as response:
            status_code = response.status
            body = response.read(65536)
            content_type = response.headers.get_content_type()
    except Exception as exc:
        return type(exc).__name__
    if status_code < 200 or status_code >= 400:
        return f"http_{status_code}"
    if content_type == "application/json":
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "invalid_json"
        readiness = payload.get("data", {}).get("status") if isinstance(payload, dict) else None
        if readiness not in (None, "ok"):
            return f"status_{readiness}"
    return None


def load_env_file(path: str | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path:
        return values
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _env_bool(values: dict[str, str], key: str, default: bool) -> bool:
    raw = values.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def send_email(*, env_file: str | None, recipients: list[str], subject: str, body: str) -> None:
    settings = load_env_file(env_file)
    host = settings.get("STUDYHUB_SMTP_HOST", "")
    from_email = settings.get("STUDYHUB_SMTP_FROM_EMAIL", "")
    if not host or not from_email or not recipients:
        raise RuntimeError("SMTP host, sender, and alert recipients are required")
    port = int(settings.get("STUDYHUB_SMTP_PORT", "587"))
    timeout = int(settings.get("STUDYHUB_SMTP_TIMEOUT_SECONDS", "15"))
    use_ssl = _env_bool(settings, "STUDYHUB_SMTP_USE_SSL", False)
    starttls = _env_bool(settings, "STUDYHUB_SMTP_STARTTLS", True)
    username = settings.get("STUDYHUB_SMTP_USERNAME", "")
    password = settings.get("STUDYHUB_SMTP_PASSWORD", "")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
            if username:
                server.login(username, password)
            server.send_message(message)
        return
    with smtplib.SMTP(host, port, timeout=timeout) as server:
        if starttls:
            server.starttls(context=context)
        if username:
            server.login(username, password)
        server.send_message(message)


def read_json(path: str | None) -> dict[str, object]:
    if not path:
        return {}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_json(path: str | None, payload: dict[str, object]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def notify(
    *,
    args: argparse.Namespace,
    now: datetime,
    alerts: dict[str, str],
    payload: dict[str, object],
) -> dict[str, object]:
    state = read_json(args.alert_state_file)
    previous_codes = {str(code) for code in state.get("activeAlertCodes", [])}
    current_codes = set(alerts)
    last_attempt = _parse_time(state.get("lastAttemptAt"))
    last_sent = _parse_time(state.get("lastSentAt"))
    notification_type: str | None = None

    if current_codes:
        changed = current_codes != previous_codes
        cooldown_elapsed = last_sent is None or (now - last_sent).total_seconds() >= args.alert_cooldown_seconds
        retry_elapsed = last_attempt is None or (now - last_attempt).total_seconds() >= args.alert_retry_seconds
        if changed or (cooldown_elapsed and retry_elapsed):
            notification_type = "alert"
    elif previous_codes:
        notification_type = "recovery"

    notification: dict[str, object] = {"status": "deduplicated" if current_codes else "idle"}
    if notification_type is not None:
        state["lastAttemptAt"] = now.isoformat()
        hostname = socket.gethostname()
        if notification_type == "alert":
            subject = f"[StudyHub] Runtime alert on {hostname}"
            summary = "\n".join(f"- {code}: {value}" for code, value in sorted(alerts.items()))
            body = (
                "StudyHub runtime monitoring detected an abnormal condition.\n\n"
                f"Checked at: {now.isoformat()}\nHost: {hostname}\n\nAlerts:\n{summary}\n\n"
                f"Status snapshot:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
            )
        else:
            subject = f"[StudyHub] Runtime recovered on {hostname}"
            body = (
                "StudyHub runtime monitoring has recovered.\n\n"
                f"Checked at: {now.isoformat()}\nHost: {hostname}\n"
                f"Cleared alerts: {', '.join(sorted(previous_codes))}\n"
            )
        try:
            send_email(env_file=args.env_file, recipients=args.alert_email, subject=subject, body=body)
        except Exception as exc:
            notification = {"status": "failed", "type": notification_type, "error": type(exc).__name__}
        else:
            state["lastSentAt"] = now.isoformat()
            notification = {"status": "sent", "type": notification_type, "recipients": len(args.alert_email)}

    state["activeAlertCodes"] = sorted(current_codes)
    write_json(args.alert_state_file, state)
    return notification


def collect_traffic(args: argparse.Namespace, now: datetime) -> dict[str, int]:
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
    return {
        "requests": parsed_requests,
        "peakRequestsPerMinute": max(per_minute.values(), default=0),
        "peakRequestsPerIpMinute": max(per_ip_minute.values(), default=0),
        "rateLimited": rate_limited,
        "serverErrors": sum(count for status, count in statuses.items() if status >= 500),
    }


def main() -> int:
    args = parse_args()
    now = datetime.now().astimezone()
    if args.test_notification:
        send_email(
            env_file=args.env_file,
            recipients=args.alert_email,
            subject=f"[StudyHub] Monitoring notification test on {socket.gethostname()}",
            body=f"StudyHub monitoring email delivery is working.\nChecked at: {now.isoformat()}\n",
        )
        print(json.dumps({"notification": "sent", "recipients": len(args.alert_email)}))
        return 0

    traffic = collect_traffic(args, now)
    connections = active_connections()
    memory_mb = available_memory_mb()
    load_one = os.getloadavg()[0]
    cpu = cpu_percent()
    filesystems = [filesystem_usage(path) for path in (args.filesystem or ["/"])]
    filesystems = [item for item in filesystems if item is not None]
    services = {name: service_is_active(name) for name in args.service}
    probes = {url: probe_url(url) for url in args.probe_url}
    certificate_days = certificate_days_remaining(args.certificate_file) if args.certificate_file else None
    alerts: dict[str, str] = {}

    if traffic["peakRequestsPerMinute"] >= args.requests_per_minute:
        alerts["requests_per_minute"] = str(traffic["peakRequestsPerMinute"])
    if traffic["peakRequestsPerIpMinute"] >= args.requests_per_ip_minute:
        alerts["requests_per_ip_minute"] = str(traffic["peakRequestsPerIpMinute"])
    if traffic["rateLimited"] >= args.rate_limited:
        alerts["rate_limited"] = str(traffic["rateLimited"])
    if traffic["serverErrors"] >= args.server_errors:
        alerts["server_errors"] = str(traffic["serverErrors"])
    if connections is None:
        alerts["nginx_status_unavailable"] = "unknown"
    elif connections >= args.active_connections:
        alerts["active_connections"] = str(connections)
    if memory_mb is not None and memory_mb <= args.available_memory_mb:
        alerts["available_memory_mb"] = str(memory_mb)
    if load_one >= args.load_one:
        alerts["load_one"] = f"{load_one:.2f}"
    if cpu is not None and cpu >= args.cpu_percent:
        alerts["cpu_percent"] = f"{cpu:.2f}"
    for item in filesystems:
        path = str(item["path"])
        if float(item["diskUsedPercent"]) >= args.disk_used_percent:
            alerts[f"disk_used_percent:{path}"] = str(item["diskUsedPercent"])
        if float(item["inodeUsedPercent"]) >= args.inode_used_percent:
            alerts[f"inode_used_percent:{path}"] = str(item["inodeUsedPercent"])
    for name, active in services.items():
        if not active:
            alerts[f"service_inactive:{name}"] = "inactive"
    for url, error in probes.items():
        if error is not None:
            alerts[f"probe_failed:{url}"] = error
    if args.certificate_file:
        if certificate_days is None:
            alerts["certificate_probe_failed"] = args.certificate_file
        elif certificate_days <= args.certificate_expiry_days:
            alerts["certificate_days_remaining"] = str(certificate_days)

    payload: dict[str, object] = {
        "checkedAt": now.isoformat(),
        "windowSeconds": args.window_seconds,
        **traffic,
        "activeConnections": connections,
        "availableMemoryMb": memory_mb,
        "loadOne": round(load_one, 2),
        "cpuPercent": cpu,
        "filesystems": filesystems,
        "services": services,
        "probes": probes,
        "certificateDaysRemaining": certificate_days,
        "alerts": [f"{code}={value}" for code, value in sorted(alerts.items())],
    }
    payload["notification"] = notify(args=args, now=now, alerts=alerts, payload=payload)
    write_json(args.status_file, payload)
    prefix = "SECURITY_ALERT" if alerts else "security_monitor_ok"
    print(f"{prefix} {json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}")
    return 2 if alerts and args.fail_on_alert else 0


if __name__ == "__main__":
    sys.exit(main())
