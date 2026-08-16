from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta, timezone
import importlib.util
import json
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
        alert_confirm_runs=3,
        recovery_confirm_runs=2,
        env_file=str(tmp_path / ".env"),
        alert_email=["admin-one@example.com", "admin-two@example.com"],
    )


def test_notification_confirms_alerts_and_recovery_before_sending(tmp_path: Path, monkeypatch) -> None:
    deliveries: list[str] = []

    def capture_email(**kwargs) -> None:
        deliveries.append(kwargs["subject"])

    monkeypatch.setattr(runtime_monitor, "send_email", capture_email)
    args = _notification_args(tmp_path)
    started_at = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)

    first_observation = runtime_monitor.notify(
        args=args,
        now=started_at,
        alerts={"server_errors": "21"},
        payload={"serverErrors": 21},
    )
    second_observation = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=1),
        alerts={"server_errors": "21"},
        payload={"serverErrors": 21},
    )
    confirmed = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=2),
        alerts={"server_errors": "21"},
        payload={"serverErrors": 21},
    )
    duplicate = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=3),
        alerts={"server_errors": "25"},
        payload={"serverErrors": 25},
    )
    recovery_pending = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=4),
        alerts={},
        payload={},
    )
    recovered = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=5),
        alerts={},
        payload={},
    )

    assert first_observation == {"status": "pending_confirmation", "observedRuns": 1, "requiredRuns": 3}
    assert second_observation == {"status": "pending_confirmation", "observedRuns": 2, "requiredRuns": 3}
    assert confirmed == {"status": "sent", "type": "alert", "recipients": 2}
    assert duplicate == {"status": "deduplicated"}
    assert recovery_pending == {"status": "pending_recovery", "healthyRuns": 1, "requiredRuns": 2}
    assert recovered == {"status": "sent", "type": "recovery", "recipients": 2}
    assert len(deliveries) == 2
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

    runtime_monitor.notify(
        args=args,
        now=started_at,
        alerts={"cpu_percent": "99"},
        payload={},
    )
    runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=1),
        alerts={"cpu_percent": "99"},
        payload={},
    )
    first = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=2),
        alerts={"cpu_percent": "99"},
        payload={},
    )
    suppressed = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=3),
        alerts={"cpu_percent": "99"},
        payload={},
    )
    retried = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=7),
        alerts={"cpu_percent": "99"},
        payload={},
    )

    assert first["status"] == "failed"
    assert suppressed == {"status": "deduplicated"}
    assert retried["status"] == "failed"
    assert attempts == 2


def test_transient_alert_never_sends_alert_or_recovery(tmp_path: Path, monkeypatch) -> None:
    deliveries: list[str] = []
    monkeypatch.setattr(runtime_monitor, "send_email", lambda **kwargs: deliveries.append(kwargs["subject"]))
    args = _notification_args(tmp_path)
    started_at = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)

    pending = runtime_monitor.notify(
        args=args,
        now=started_at,
        alerts={"service_inactive:frontend": "inactive"},
        payload={},
    )
    healthy = runtime_monitor.notify(
        args=args,
        now=started_at + timedelta(minutes=1),
        alerts={},
        payload={},
    )

    assert pending == {"status": "pending_confirmation", "observedRuns": 1, "requiredRuns": 3}
    assert healthy == {"status": "idle"}
    assert deliveries == []


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


def test_resolve_alert_recipients_uses_private_env_and_deduplicates(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "STUDYHUB_ABUSE_MONITOR_ALERT_EMAILS='ops@example.com, admin@example.com;OPS@example.com'\n",
        encoding="utf-8",
    )

    assert runtime_monitor.resolve_alert_recipients(
        env_file=str(env_file),
        explicit=["temporary@example.com", "admin@example.com"],
    ) == [
        "temporary@example.com",
        "admin@example.com",
        "ops@example.com",
    ]


def test_resolve_alert_recipients_allows_no_configured_recipients(tmp_path: Path) -> None:
    assert runtime_monitor.resolve_alert_recipients(
        env_file=str(tmp_path / "missing.env"),
        explicit=[],
    ) == []


def test_metrics_summary_keeps_only_bounded_error_fingerprints() -> None:
    payload = runtime_monitor.parse_application_metrics(
        "\n".join(
            [
                "studyhub_process_start_time_seconds 123.5",
                'studyhub_http_requests_total{method="GET",route="/ok",status_code="200"} 7',
                'studyhub_http_requests_total{method="GET",route="/bad",status_code="500"} 2',
                'studyhub_errors_total{fingerprint="abc123",kind="valueerror",route="/bad",status_code="500"} 2',
            ]
        )
    )

    assert payload["available"] is True
    assert payload["requestsTotal"] == 9
    assert payload["serverErrorsTotal"] == 2
    assert payload["errorFingerprints"] == [
        {
            "fingerprint": "abc123",
            "kind": "valueerror",
            "route": "/bad",
            "statusCode": "500",
            "count": 2,
        }
    ]


def test_history_is_partitioned_by_day_and_pruned(tmp_path: Path) -> None:
    old_file = tmp_path / "runtime-history-2026-07-01.jsonl"
    old_file.write_text("{}\n", encoding="utf-8")
    now = datetime.fromisoformat("2026-08-16T12:00:00+08:00")

    runtime_monitor.append_history(
        str(tmp_path),
        now=now,
        retention_days=14,
        payload={"checkedAt": now.isoformat()},
    )

    target = tmp_path / "runtime-history-2026-08-16.jsonl"
    assert json.loads(target.read_text(encoding="utf-8"))["checkedAt"] == now.isoformat()
    assert not old_file.exists()
