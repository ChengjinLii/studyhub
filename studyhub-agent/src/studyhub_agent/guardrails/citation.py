from __future__ import annotations

import re
from dataclasses import dataclass

SOURCE_ID_PATTERN = re.compile(r"^material:[1-9][0-9]*:p(?:[1-9][0-9]*|none):c[0-9]+$")
INLINE_CITATION_PATTERN = re.compile(r"\[source:(material:[1-9][0-9]*:p(?:[1-9][0-9]*|none):c[0-9]+)\]")


@dataclass(frozen=True, slots=True)
class CitationValidation:
    cited: tuple[str, ...]
    invalid: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.invalid


def extract_citations(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(INLINE_CITATION_PATTERN.findall(text)))


def validate_citations(text: str, visible_source_ids: set[str]) -> CitationValidation:
    cited = extract_citations(text)
    invalid = tuple(
        source_id
        for source_id in cited
        if not SOURCE_ID_PATTERN.fullmatch(source_id) or source_id not in visible_source_ids
    )
    return CitationValidation(cited=cited, invalid=invalid)
