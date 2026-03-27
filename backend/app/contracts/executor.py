from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from app.contracts.models import ContractSample, ResponseSnapshot
from app.core.multipart import build_multipart_parts


class SupportsRequest(Protocol):
    def request(self, method: str, url: str, **kwargs: Any): ...


def _build_request_kwargs(sample: ContractSample) -> dict[str, Any]:
    request_spec = sample.request
    kind = request_spec.get("request_kind", "none")
    kwargs: dict[str, Any] = {
        "params": request_spec.get("query"),
        "headers": sample.request_headers or None,
        "follow_redirects": False,
    }

    if sample.request_form:
        kwargs["data"] = sample.request_form
        return kwargs

    if sample.request_multipart:
        data, files = build_multipart_parts(sample.request_multipart)
        kwargs["data"] = data or None
        kwargs["files"] = files or None
        return kwargs

    if kind == "json":
        kwargs["json"] = request_spec.get("json")
    elif kind == "form":
        kwargs["data"] = request_spec.get("form")

    return kwargs


def snapshot_response(response: Any) -> ResponseSnapshot:
    header_lists: dict[str, list[str]] = {}
    for key in response.headers.keys():
        lower = key.lower()
        values = response.headers.get_list(key) if hasattr(response.headers, "get_list") else [response.headers.get(key)]
        header_lists[lower] = [value for value in values if value is not None]

    headers = {key.lower(): value for key, value in response.headers.items()}
    content_type = headers.get("content-type", "")

    json_body = None
    text_body = None
    if "application/json" in content_type and response.content:
        try:
            json_body = response.json()
        except Exception:  # noqa: BLE001
            text_body = response.text
    elif content_type.startswith("text/") or not content_type:
        text_body = response.text

    binary_meta = None
    if json_body is None and text_body is None:
        binary_meta = {
            "content_type": content_type or None,
            "content_length": headers.get("content-length") or str(len(response.content)),
            "content_disposition": headers.get("content-disposition"),
            "location": headers.get("location"),
        }

    return ResponseSnapshot(
        status_code=response.status_code,
        headers=headers,
        header_lists=header_lists,
        json_body=json_body,
        text_body=text_body,
        binary_meta=binary_meta,
    )


class SyncRequestExecutor:
    def __init__(self, client: SupportsRequest) -> None:
        self.client = client

    def execute(self, sample: ContractSample) -> ResponseSnapshot:
        kwargs = _build_request_kwargs(sample)
        response = self.client.request(sample.request["method"], sample.request["path"], **kwargs)
        return snapshot_response(response)


def build_httpx_executor(base_url: str, timeout_seconds: float = 10.0) -> tuple[httpx.Client, SyncRequestExecutor]:
    client = httpx.Client(base_url=base_url, timeout=timeout_seconds, follow_redirects=False)
    return client, SyncRequestExecutor(client)
