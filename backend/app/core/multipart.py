from __future__ import annotations

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
        content = part.get("content")
        if content is None:
            size = int(part.get("size", 16))
            content = "x" * size
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = bytes(content)
        files.append((name, (filename, content_bytes, content_type)))

    return data, files
