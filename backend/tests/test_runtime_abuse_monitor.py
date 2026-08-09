from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "security" / "runtime-abuse-monitor.py"
SPEC = importlib.util.spec_from_file_location("runtime_abuse_monitor", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
runtime_monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_monitor)


def _notification_args(tmp_path: Path) -> Namespace:
    return Namespace(
        alert_state_file=str(tmp_path / "alert-state.json"),
        alert_cooldown_seconds=3600,
        alert_retry_seconds=300,
        env_file=str(tmp_path / ".env"),
        alert_email=["admin-one@example.com", "admin-two@example.com"],
    )


def test_notification_deduplicates_changed_alerts_and_recovery(tmp_path: Path, monkeypatch) -> None:
    deliveries: list[str] = []

    def capture_email(**kwargs) -> None:
        deliveries.append(kwargs["subject"])

    monkeypatch.setattr(runtime_monitor, "send_email", capture_email)
    args = _notification_args(tmp_path)
    started_at = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)

    first = runtime_monitor.notify(
        args=args,
        now=started_at,
        alerts={"server_errors": "21"},
        payload={"serverErrors": 21},
    )
    duplicate = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=1),
        alerts={"server_errors": "25"},
        payload={"serverErrors": 25},
    )
    changed = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=2),
        alerts={"server_errors": "25", "service_inactive:nginx": "inactive"},
        payload={"serverErrors": 25},
    )
    recovered = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=3),
        alerts={},
        payload={},
    )

    assert first == {"status": "sent", "type": "alert", "recipients": 2}
    assert duplicate == {"status": "deduplicated"}
    assert changed == {"status": "sent", "type": "alert", "recipients": 2}
    assert recovered == {"status": "sent", "type": "recovery", "recipients": 2}
    assert len(deliveries) == 3
    assert "Runtime recovered" in deliveries[-1]


def test_notification_failure_is_retried_after_retry_window(tmp_path: Path, monkeypatch) -> None:
    attempts = 0

    def fail_email(**kwargs) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("smtp unavailable")

    monkeypatch.setattr(runtime_monitor, "send_email", fail_email)
    args = _notification_args(tmp_path)
    started_at = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)

    first = runtime_monitor.notify(
        args=args,
        now=started_at,
        alerts={"cpu_percent": "99"},
        payload={},
    )
    suppressed = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=1),
        alerts={"cpu_percent": "99"},
        payload={},
    )
    retried = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=5),
        alerts={"cpu_percent": "99"},
        payload={},
    )

    assert first["status"] == "failed"
    assert suppressed == {"status": "deduplicated"}
    assert retried["status"] == "failed"
    assert attempts == 2


def test_load_env_file_accepts_exported_and_quoted_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nexport STUDYHUB_SMTP_HOST=smtp.example.com\nSTUDYHUB_SMTP_FROM_EMAIL='noreply@example.com'\n",
        encoding="utf-8",
    )

    assert runtime_monitor.load_env_file(str(env_file)) == {
        "STUDYHUB_SMTP_HOST": "smtp.example.com",
        "STUDYHUB_SMTP_FROM_EMAIL": "noreply@example.com",
    }
