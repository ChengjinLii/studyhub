from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.contracts.models import ContractSample


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").rstrip("\n")


def load_contract_samples(sample_dir: Path, selected_ids: set[str] | None = None) -> list[ContractSample]:
    samples: list[ContractSample] = []
    for request_path in sorted(sample_dir.rglob("request.json")):
        directory = request_path.parent
        request = _read_json(request_path) or {}
        sample_id = str(request.get("sample_id") or directory.name)
        if selected_ids and sample_id not in selected_ids:
            continue

        bundle = str(request.get("bundle") or directory.parent.name)
        sample = ContractSample(
            sample_id=sample_id,
            bundle=bundle,
            directory=directory,
            request=request,
            request_kind=request.get("request_kind"),
            response_kind=request.get("response_kind"),
            request_headers=_read_json(directory / "request.headers.json") or {},
            request_form=_read_json(directory / "request.form.json"),
            request_multipart=_read_json(directory / "request.multipart.json"),
            expected_status=_read_json(directory / "response.status.json"),
            expected_headers=_read_json(directory / "response.headers.json"),
            expected_json=_read_json(directory / "response.body.json"),
            expected_text=_read_text(directory / "response.body.txt"),
            expected_binary=_read_json(directory / "response.binary.json"),
            notes=_read_text(directory / "notes.md"),
        )
        samples.append(sample)
    return samples
