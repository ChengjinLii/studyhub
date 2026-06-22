from __future__ import annotations

import base64
from typing import Any


def build_multipart_parts(spec: dict[str, Any] | None) -> tuple[dict[str, str], list[tuple[str, tuple[str, bytes, str]]]]:
    """把样本描述文件转成 httpx 可提交的 multipart 结构。"""

    if not spec:
        return {}, []

    data: dict[str, str] = {}
    files: list[tuple[str, tuple[str, bytes, str]]] = []

    for part in spec.get("parts", []):
        name = part["name"]
        part_type = part.get("type", "field")
        if part_type == "field":
            data[name] = str(part.get("value", ""))
            continue

        filename = part.get("filename", "placeholder.bin")
        content_type = part.get("content_type", "application/octet-stream")
        content_base64 = part.get("content_base64")
        content = part.get("content")
        if content_base64 is not None:
            files.append((name, (filename, base64.b64decode(str(content_base64)), content_type)))
            continue
        if content is None:
            size = int(part.get("size", 16))
            content = "x" * size
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = bytes(content)
        files.append((name, (filename, content_bytes, content_type)))

    return data, files
