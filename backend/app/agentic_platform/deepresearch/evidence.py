from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from app.agentic_platform.domain.hashing import canonical_hash

from .state import EvidenceRecord, ResearchSourceRef, ResearchSourceType


def source_from_internal_material(item: dict[str, Any]) -> ResearchSourceRef:
    material_id = int(item["id"])
    title = str(item.get("title") or f"资料 #{material_id}").strip()[:512]
    return ResearchSourceRef(
        source_id=f"material:{material_id}",
        source_type=ResearchSourceType.INTERNAL_MATERIAL,
        title=title or f"资料 #{material_id}",
        source_uri=f"studyhub://materials/{material_id}",
        material_id=material_id,
        reliability=_internal_reliability(item),
        access_scope="admin:materials.read",
    )


def evidence_from_internal_pdf(item: Any) -> EvidenceRecord:
    material_id = int(item.material_id)
    page = int(item.page)
    excerpt = " ".join(str(item.text).split()).strip()[:3_000]
    evidence_id = str(getattr(item, "evidence_id", lambda: "")() or "").strip()
    if not evidence_id:
        evidence_id = f"evidence_{canonical_hash({'material': material_id, 'page': page, 'text': excerpt})[:24]}"
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_type=ResearchSourceType.INTERNAL_PDF,
        source_uri=f"studyhub://materials/{material_id}/pages/{page}",
        title=str(item.title).strip()[:512] or f"资料 #{material_id}",
        material_id=material_id,
        page=page,
        excerpt=excerpt or "[unreadable page excerpt]",
        reliability=_pdf_reliability(item),
        access_scope="admin:materials.read",
    )


def source_coverage(evidence: Iterable[EvidenceRecord]) -> dict[str, int]:
    counts = Counter(record.source_type.value for record in evidence)
    return dict(sorted(counts.items()))


def evidence_by_id(evidence: Iterable[EvidenceRecord]) -> dict[str, EvidenceRecord]:
    return {record.evidence_id: record for record in evidence}


def _internal_reliability(item: dict[str, Any]) -> float:
    rating = float(item.get("ratingAvg", item.get("rating_avg", 0.0)) or 0.0)
    downloads = int(item.get("downloadCount", item.get("download_count", 0)) or 0)
    base = 0.55 + min(max(rating, 0.0), 5.0) / 20.0
    if downloads > 0:
        base += min(downloads, 1_000) / 20_000.0
    return min(0.9, max(0.2, base))


def _pdf_reliability(item: Any) -> float:
    score = int(getattr(item, "score", 0) or 0)
    source_type = str(getattr(item, "source_type", "") or "")
    base = 0.65 + min(max(score, 0), 100) / 400.0
    if source_type in {"past_exam", "answer_explanation"}:
        base += 0.05
    return min(0.98, base)
