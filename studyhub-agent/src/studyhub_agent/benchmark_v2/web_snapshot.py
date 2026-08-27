from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from studyhub_agent.benchmark_v2.schema import load_jsonl, write_jsonl

SNAPSHOT_SCHEMA_VERSION = "studyhub.agentbench-web-snapshot.v2"
LOCK_SCHEMA_VERSION = "studyhub.agentbench-web-lock.v2"
ALLOWED_HOSTS = frozenset({"docs.python.org", "raw.githubusercontent.com"})


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


class _VisibleTextParser(HTMLParser):
    _IGNORED = frozenset({"script", "style", "svg", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in self._IGNORED:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def sanitize_payload(payload: bytes, content_type: str) -> str:
    decoded = payload.decode("utf-8", errors="replace")
    if "html" in content_type.casefold() or "<html" in decoded[:1000].casefold():
        parser = _VisibleTextParser()
        parser.feed(decoded)
        decoded = "\n".join(parser.parts)
    lines = [re.sub(r"\s+", " ", line).strip() for line in decoded.splitlines()]
    return "\n".join(line for line in lines if line)


def normalized_evidence_text(value: str) -> str:
    return re.sub(r"[^0-9a-z㐀-鿿]+", " ", value.casefold()).strip()


def _validate_source(source: dict[str, Any]) -> None:
    required = {
        "source_key",
        "split",
        "url",
        "publisher",
        "license_spdx",
        "license_url",
        "document_type",
    }
    missing = required - set(source)
    if missing:
        raise ValueError(f"web source missing fields: {sorted(missing)}")
    parsed = urlparse(str(source["url"]))
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"web source is not on the allowlist: {source['url']}")
    if source.get("is_target") and not source.get("support_needles"):
        raise ValueError(f"target source lacks support needles: {source['source_key']}")


def load_source_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "studyhub.agentbench-web-source-config.v2":
        raise ValueError(f"unsupported web source config: {value.get('schema_version')}")
    keys: set[str] = set()
    urls: set[str] = set()
    for source in value.get("sources", []):
        _validate_source(source)
        key = str(source["source_key"])
        url = str(source["url"])
        if key in keys or url in urls:
            raise ValueError(f"duplicate web source key or URL: {key}")
        keys.add(key)
        urls.add(url)
    return value


def _fetch_one(source: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        str(source["url"]),
        headers={"User-Agent": "StudyHub-AgentBench-v2-snapshot/1.0 (+https://study-hub.cn)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL allowlist checked above
        final_url = response.geturl()
        parsed = urlparse(final_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise RuntimeError(f"redirect left web snapshot allowlist: {final_url}")
        payload = response.read()
        content_type = response.headers.get("Content-Type", "text/plain")
    content = sanitize_payload(payload, content_type)
    if len(content) < 400:
        raise RuntimeError(f"web snapshot is unexpectedly short: {source['source_key']} ({len(content)} chars)")
    folded = normalized_evidence_text(content)
    missing_needles = [
        needle for needle in source.get("support_needles", []) if normalized_evidence_text(str(needle)) not in folded
    ]
    if missing_needles:
        raise RuntimeError(f"target support text missing for {source['source_key']}: {missing_needles}")
    source_id = f"web-v2:{hashlib.sha256(str(source['url']).encode()).hexdigest()[:20]}"
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source_id": source_id,
        "source_key": source["source_key"],
        "split": source["split"],
        "url": source["url"],
        "resolved_url": final_url,
        "title": source.get("title", source["source_key"]),
        "content": content,
        "content_sha256": sha256_bytes(content.encode()),
        "raw_sha256": sha256_bytes(payload),
        "raw_bytes": len(payload),
        "publisher": source["publisher"],
        "license_spdx": source["license_spdx"],
        "license_url": source["license_url"],
        "document_type": source["document_type"],
        "source_quality": "official_primary_documentation",
        "access_scope": "public_open_documentation",
        "is_target": bool(source.get("is_target", False)),
        "task_contract": source.get("task_contract"),
        "support_needles": list(source.get("support_needles", [])),
    }


def fetch_snapshot(
    *,
    config_path: Path,
    output_path: Path,
    lock_path: Path,
    timeout: float = 45.0,
    workers: int = 8,
    refresh_lock: bool = False,
) -> dict[str, Any]:
    config = load_source_config(config_path)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda source: _fetch_one(source, timeout=timeout), config["sources"]))
    rows.sort(key=lambda row: str(row["source_key"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, rows)
    lock = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "config_sha256": sha256_path(config_path),
        "snapshot_sha256": sha256_path(output_path),
        "source_count": len(rows),
        "sources": {
            str(row["source_key"]): {
                "url": row["url"],
                "resolved_url": row["resolved_url"],
                "content_sha256": row["content_sha256"],
                "raw_sha256": row["raw_sha256"],
                "license_spdx": row["license_spdx"],
            }
            for row in rows
        },
    }
    if lock_path.exists() and not refresh_lock:
        expected = json.loads(lock_path.read_text(encoding="utf-8"))
        if expected != lock:
            output_path.unlink(missing_ok=True)
            raise RuntimeError("web snapshot drifted from the pinned lock; review and use --refresh-lock deliberately")
    else:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lock


def validate_offline_snapshot(*, config_path: Path, output_path: Path, lock_path: Path) -> dict[str, Any]:
    config = load_source_config(config_path)
    if not output_path.exists() or not lock_path.exists():
        raise FileNotFoundError("web snapshot or lock missing; run fetch_web_snapshots.py without --offline")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise ValueError(f"unsupported web lock: {lock.get('schema_version')}")
    if lock.get("config_sha256") != sha256_path(config_path):
        raise RuntimeError("web source config hash differs from lock")
    if lock.get("snapshot_sha256") != sha256_path(output_path):
        raise RuntimeError("cached web snapshot hash differs from lock")
    rows = load_jsonl(output_path)
    if len(rows) != len(config["sources"]) or len(rows) != int(lock.get("source_count", -1)):
        raise RuntimeError("cached web snapshot source count differs from lock")
    for row in rows:
        expected = lock["sources"].get(str(row["source_key"]))
        if expected is None or row.get("content_sha256") != expected.get("content_sha256"):
            raise RuntimeError(f"cached web source differs from lock: {row.get('source_key')}")
    return lock
