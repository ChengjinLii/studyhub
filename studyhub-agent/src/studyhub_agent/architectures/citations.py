import re
from dataclasses import dataclass

_CITATION = re.compile(r"\[([0-9]+)[:\uFF1A]([0-9]+)\]")


@dataclass(frozen=True, slots=True)
class CitationReport:
    ok: bool
    cited: tuple[tuple[int, int], ...]
    unread: tuple[tuple[int, int], ...]
    missing: bool
    invalid: bool = False


def _parse(text: str) -> tuple[tuple[tuple[int, int], ...], bool]:
    pairs = []
    invalid = False
    for material, page in _CITATION.findall(text):
        # Bound model-supplied numbers before int/JSON conversion; never crash an episode on them.
        if len(material) > 20 or len(page) > 20:
            invalid = True
            continue
        pairs.append((int(material), int(page)))
    return tuple(dict.fromkeys(pairs)), invalid


def parse_citations(text: str) -> tuple[tuple[int, int], ...]:
    return _parse(text)[0]


def check_citations(answer: str, read_pages: frozenset[tuple[int, int]]) -> CitationReport:
    cited, invalid = _parse(answer)
    unread = tuple(pair for pair in cited if pair not in read_pages)
    missing = bool(read_pages) and not cited
    return CitationReport(
        ok=not unread and not missing and not invalid, cited=cited, unread=unread, missing=missing, invalid=invalid
    )
