from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from studyhub_agent.environments.replay.snapshot import SnapshotMaterial

_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+")
_CHINESE_RUN = re.compile(r"[㐀-鿿]+")
_K1 = 1.5
_B = 0.75


def mixed_tokens(text: str) -> list[str]:
    normalized = text.casefold()
    tokens = _LATIN_OR_NUMBER.findall(normalized)
    for run in _CHINESE_RUN.findall(normalized):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    return tokens


class Bm25Index:
    """Deterministic BM25 over material metadata (title, course, school, summary, tags)."""

    def __init__(self, rows: Sequence[SnapshotMaterial]) -> None:
        self._rows = tuple(rows)
        self._frequencies = tuple(Counter(mixed_tokens(_document_text(row))) for row in self._rows)
        self._lengths = tuple(sum(freq.values()) for freq in self._frequencies)
        total = len(self._rows)
        self._average = sum(self._lengths) / total if total else 0.0
        document_frequency: Counter[str] = Counter()
        for frequencies in self._frequencies:
            document_frequency.update(frequencies.keys())
        self._idf = {
            term: math.log(1 + (total - count + 0.5) / (count + 0.5)) for term, count in document_frequency.items()
        }

    def search(self, query: str, *, limit: int) -> list[tuple[float, SnapshotMaterial]]:
        terms = mixed_tokens(query)
        if not terms or not self._rows:
            return []
        scored: list[tuple[float, int, SnapshotMaterial]] = []
        for row, frequencies, length in zip(self._rows, self._frequencies, self._lengths, strict=True):
            score = 0.0
            for term in terms:
                frequency = frequencies.get(term, 0)
                if frequency:
                    denominator = frequency + _K1 * (1 - _B + _B * length / max(self._average, 1e-9))
                    score += self._idf.get(term, 0.0) * frequency * (_K1 + 1) / denominator
            if score > 0:
                scored.append((round(score, 6), row.material_id, row))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(score, row) for score, _, row in scored[:limit]]


def _document_text(row: SnapshotMaterial) -> str:
    return " ".join([row.title, row.course, row.school, row.summary, *row.tags])
