from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
from types import ModuleType


def _load_monitor() -> ModuleType:
    script = Path(__file__).parents[2] / "scripts" / "security" / "runtime-abuse-monitor.py"
    spec = importlib.util.spec_from_file_location("studyhub_runtime_abuse_monitor", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metrics_summary_keeps_only_bounded_error_fingerprints() -> None:
    monitor = _load_monitor()
    payload = monitor.parse_application_metrics(
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
    monitor = _load_monitor()
    old_file = tmp_path / "runtime-history-2026-07-01.jsonl"
    old_file.write_text("{}\n", encoding="utf-8")
    now = datetime.fromisoformat("2026-08-16T12:00:00+08:00")

    monitor.append_history(str(tmp_path), now=now, retention_days=14, payload={"checkedAt": now.isoformat()})

    target = tmp_path / "runtime-history-2026-08-16.jsonl"
    assert json.loads(target.read_text(encoding="utf-8"))["checkedAt"] == now.isoformat()
    assert not old_file.exists()
