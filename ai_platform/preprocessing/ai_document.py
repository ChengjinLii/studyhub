from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


WHITESPACE_PATTERN = re.compile(r"\s+")
CONTACT_PATTERN = re.compile(
    r"(?P<email>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})|(?P<phone>1[3-9]\d{9})|(?P<qq>\b[1-9]\d{4,11}\b)"
)


@dataclass(frozen=True)
class SourceRecord:
    id: str
    type: str
    title: str
    body: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AIDocument:
    id: str
    source_id: str
    source_type: str
    title: str
    text: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sourceId": self.source_id,
            "sourceType": self.source_type,
            "title": self.title,
            "text": self.text,
            "metadata": self.metadata,
        }


def normalize_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value or "").strip()


def redact_contacts(value: str) -> str:
    return CONTACT_PATTERN.sub("[REDACTED_CONTACT]", value or "")


def build_ai_documents(records: list[SourceRecord], *, chunk_size: int = 280, overlap: int = 40) -> list[AIDocument]:
    documents: list[AIDocument] = []
    for record in records:
        cleaned_title = normalize_text(redact_contacts(record.title))
        cleaned_body = normalize_text(redact_contacts(record.body))
        metadata_text = " ".join(str(value) for value in record.metadata.values() if value)
        base_text = normalize_text(f"{cleaned_title} {cleaned_body} {redact_contacts(metadata_text)}")
        chunks = chunk_text(base_text, chunk_size=chunk_size, overlap=overlap)
        for index, chunk in enumerate(chunks):
            documents.append(
                AIDocument(
                    id=f"{record.type}:{record.id}:chunk:{index}",
                    source_id=record.id,
                    source_type=record.type,
                    title=cleaned_title,
                    text=chunk,
                    metadata={**record.metadata, "chunkIndex": index, "chunkCount": len(chunks)},
                )
            )
    return documents


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    normalized = normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]
    chunks: list[str] = []
    start = 0
    step = chunk_size - overlap
    while start < len(normalized):
        chunk = normalized[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(normalized):
            break
        start += step
    return chunks


def load_source_records(raw_items: list[dict[str, Any]]) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for item in raw_items:
        source_type = str(item.get("type") or item.get("sourceType") or "")
        if source_type not in {"material", "column", "request"}:
            raise ValueError(f"unsupported source type: {source_type}")
        body = str(item.get("text") or item.get("body") or item.get("description") or item.get("keyword") or "")
        records.append(
            SourceRecord(
                id=str(item["id"]),
                type=source_type,
                title=str(item.get("title") or item.get("course") or ""),
                body=body,
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return records
