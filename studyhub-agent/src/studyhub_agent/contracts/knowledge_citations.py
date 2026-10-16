import re
from collections.abc import Iterable

from studyhub_agent.contracts.knowledge import CitationCheck

_REFERENCE = re.compile(r"\[(k_[^\]\s]*)\]")


def check_knowledge_citations(answer: str, available: Iterable[str]) -> CitationCheck:
    cited = tuple(dict.fromkeys(_REFERENCE.findall(answer)))
    allowed = set(available)
    unknown = tuple(key for key in cited if key not in allowed)
    missing = bool(allowed) and not cited
    return CitationCheck(ok=not unknown and not missing, cited=cited, unknown=unknown, missing=missing)
