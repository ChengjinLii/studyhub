from __future__ import annotations

import re

import jieba

WHITESPACE_RE = re.compile(r"\s+")
ASCII_TOKEN_RE = re.compile(r"[a-zA-Z]+(?:[&+._-][a-zA-Z0-9]+)*|\d+(?:[-./]\d+)*")
CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")


def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.replace("\x00", " ")).strip()


def mixed_tokens(text: str) -> list[str]:
    normalized = normalize_text(text).lower()
    tokens = [token.strip() for token in jieba.cut(normalized, cut_all=False) if token.strip()]
    tokens.extend(match.group(0).lower() for match in ASCII_TOKEN_RE.finditer(normalized))
    for match in CJK_RUN_RE.finditer(normalized):
        value = match.group(0)
        tokens.extend(value[index : index + 2] for index in range(max(0, len(value) - 1)))
    return tokens


def split_text(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("Expected max_chars > overlap_chars >= 0")
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        hard_end = min(len(normalized), start + max_chars)
        end = hard_end
        if hard_end < len(normalized):
            boundary = max(
                normalized.rfind(mark, start + max_chars // 2, hard_end) for mark in ("。", "！", "？", ";", "；", "\n")
            )
            if boundary > start:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks
