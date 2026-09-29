from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "runtime" / "summarize_runtime_history.py"
SPEC = importlib.util.spec_from_file_location("summarize_runtime_history", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sample(checked_at: datetime, *, process_start=100.0, requests=10, errors=0):
    return {
        "checkedAt": checked_at.isoformat(),
        "_checkedAt": checked_at,
        "peakRequestsPerMinute": requests,
        "peakRequestsPerIpMinute": requests,
        "rateLimited": 0,
        "serverErrors": errors,
        "availableMemoryMb": 2048,
        "loadOne": 0.25,
        "cpuPercent": 5.0,
        "filesystems": [{"path": "/", "diskUsedPercent": 80.5}],
        "services": {"studyhub-backend.service": True},
        "probes": {"http://127.0.0.1:8311/api/readyz": None},
        "alerts": [],
        "application": {
            "processStartTimeSeconds": process_start,
            "requestsTotal": requests,
            "serverErrorsTotal": errors,
        },
    }


def test_summary_uses_counter_deltas_and_tracks_restarts():
    start = datetime(2026, 9, 26, tzinfo=UTC)
    samples = [
        _sample(start, requests=10),
        _sample(start + timedelta(minutes=1), requests=18, errors=1),
        _sample(start + timedelta(minutes=2), process_start=200, requests=3),
        _sample(start + timedelta(minutes=3), process_start=200, requests=9, errors=2),
    ]

    payload = MODULE.summarize(samples, days=1)

    assert payload["sampleCount"] == 4
    assert payload["summary"]["applicationRestartCount"] == 1
    assert payload["days"][0]["observedApplicationRequestDelta"] == 14
    assert payload["days"][0]["observedApplicationErrorDelta"] == 3


def test_loader_skips_malformed_lines(tmp_path):
    history = tmp_path / "runtime-history-2026-09-26.jsonl"
    history.write_text(
        "not-json\n" + json.dumps(_sample(datetime(2026, 9, 26, tzinfo=UTC)), default=str) + "\n",
        encoding="utf-8",
    )

    samples, malformed = MODULE.load_history(tmp_path)

    assert len(samples) == 1
    assert malformed == 1
