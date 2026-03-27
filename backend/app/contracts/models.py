from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ContractSample:
    sample_id: str
    bundle: str
    directory: Path
    request: dict[str, Any]
    request_kind: str | None
    response_kind: str | None
    request_headers: dict[str, str]
    request_form: dict[str, Any] | None
    request_multipart: dict[str, Any] | None
    expected_status: dict[str, Any] | None
    expected_headers: dict[str, Any] | None
    expected_json: Any | None
    expected_text: str | None
    expected_binary: dict[str, Any] | None
    notes: str | None


@dataclass(slots=True)
class ResponseSnapshot:
    status_code: int
    headers: dict[str, str]
    header_lists: dict[str, list[str]]
    json_body: Any | None
    text_body: str | None
    binary_meta: dict[str, Any] | None


@dataclass(slots=True)
class SampleResult:
    sample_id: str
    bundle: str
    request_kind: str | None
    response_kind: str | None
    dimensions: list[str]
    passed: bool
    diffs: list[str]
    candidate: ResponseSnapshot
    baseline: ResponseSnapshot | None = None
