from __future__ import annotations

from typing import Any

from app.contracts.models import ContractSample, ResponseSnapshot


STABLE_HEADERS = {
    "content-type",
    "cache-control",
    "etag",
    "location",
    "content-disposition",
}


def expectation_from_sample(sample: ContractSample) -> dict[str, Any]:
    return {
        "status_code": (sample.expected_status or {}).get("status_code"),
        "headers": sample.expected_headers or {},
        "json_body": sample.expected_json,
        "text_body": sample.expected_text,
        "binary_meta": sample.expected_binary,
    }


def expectation_from_snapshot(snapshot: ResponseSnapshot) -> dict[str, Any]:
    headers = {
        name: {"equals": value}
        for name, value in snapshot.headers.items()
        if name in STABLE_HEADERS
    }
    headers["set-cookie"] = {"values": snapshot.header_lists.get("set-cookie", [])}
    return {
        "status_code": snapshot.status_code,
        "headers": headers,
        "json_body": snapshot.json_body,
        "text_body": snapshot.text_body,
        "binary_meta": snapshot.binary_meta,
    }


def compare_snapshot(actual: ResponseSnapshot, expected: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    expected_status = expected.get("status_code")
    if expected_status is not None and actual.status_code != expected_status:
        diffs.append(f"status_code mismatch: expected={expected_status} actual={actual.status_code}")

    for name, header_expectation in (expected.get("headers") or {}).items():
        actual_values = actual.header_lists.get(name.lower(), [])
        actual_value = actual.headers.get(name.lower())
        diffs.extend(_compare_header(name.lower(), actual_value, actual_values, header_expectation))

    expected_json = expected.get("json_body")
    expected_text = expected.get("text_body")
    expected_binary = expected.get("binary_meta")
    if expected_json is not None and actual.json_body != expected_json:
        diffs.append(f"json_body mismatch: expected={expected_json!r} actual={actual.json_body!r}")
    if expected_text is not None and (actual.text_body or "") != expected_text:
        diffs.append(f"text_body mismatch: expected={expected_text!r} actual={(actual.text_body or '')!r}")
    if expected_binary is not None and actual.binary_meta != expected_binary:
        diffs.append(f"binary_meta mismatch: expected={expected_binary!r} actual={actual.binary_meta!r}")

    return diffs


def _compare_header(name: str, actual_value: str | None, actual_values: list[str], expectation: Any) -> list[str]:
    diffs: list[str] = []
    if isinstance(expectation, str):
        if actual_value != expectation:
            diffs.append(f"header[{name}] mismatch: expected={expectation!r} actual={actual_value!r}")
        return diffs

    if not isinstance(expectation, dict):
        return diffs

    if expectation.get("present") and actual_value is None and not actual_values:
        diffs.append(f"header[{name}] expected to be present")
    if expectation.get("absent") and (actual_value is not None or actual_values):
        diffs.append(f"header[{name}] expected to be absent but actual={actual_values or actual_value!r}")
    if "equals" in expectation and actual_value != expectation["equals"]:
        diffs.append(f"header[{name}] mismatch: expected={expectation['equals']!r} actual={actual_value!r}")
    if "contains" in expectation:
        expected_substring = expectation["contains"]
        if actual_value is None or expected_substring not in actual_value:
            diffs.append(f"header[{name}] missing substring {expected_substring!r} in {actual_value!r}")
    if "count" in expectation and len(actual_values) != int(expectation["count"]):
        diffs.append(f"header[{name}] count mismatch: expected={expectation['count']} actual={len(actual_values)}")
    if "values" in expectation and actual_values != list(expectation["values"]):
        diffs.append(f"header[{name}] values mismatch: expected={expectation['values']!r} actual={actual_values!r}")
    return diffs
