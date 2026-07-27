"""Deterministic DeepResearch environment backed only by world-snapshot refs."""

from __future__ import annotations

import re

from app.agentic_platform.deepresearch.domain_router import ResearchEnvironmentError
from app.agentic_platform.deepresearch.state import EvidenceRecord, ResearchSourceRef, ResearchSourceType

from .clock import SnapshotClock
from .random_source import DeterministicRandomSource
from .world_snapshot import (
    ResolvedStudyHubWorld,
    StudyHubWorldSnapshot,
    WorldSnapshotArtifactStore,
)


class SnapshotResearchEnvironment:
    """Read-only research capability surface for arbitrary valid snapshot actions.

    Query ranking is computed from the frozen catalog/retriever data on every
    call.  It intentionally has no action-script lookup, network access, or
    fallback to a live material service.
    """

    def __init__(
        self,
        snapshot: StudyHubWorldSnapshot,
        artifact_store: WorldSnapshotArtifactStore,
        *,
        seed: int | None = None,
    ) -> None:
        self.world = ResolvedStudyHubWorld.resolve(snapshot, artifact_store)
        self.clock = SnapshotClock(snapshot.clock_state)
        self.random = DeterministicRandomSource(snapshot.random_seed if seed is None else seed)
        self._materials = {item.material_id: item for item in self.world.catalog.items}
        self._permissions = {item.material_id: item.allowed for item in self.world.permissions.records}
        self._retriever_terms = {item.material_id: tuple(item.terms) for item in self.world.retriever.entries}
        self._pages = {(item.material_id, item.page): item for item in self.world.pdf_page_index.pages}

    async def search_internal(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        normalized = _normalize_query(query)
        if not normalized:
            raise ResearchEnvironmentError("invalid_query", "A non-empty research query is required.", recoverable=False)
        return [self._source_for_material(material_id) for material_id in self.ranked_material_ids(normalized, limit=limit)]

    def ranked_material_ids(self, query: str, *, limit: int) -> list[int]:
        normalized = _normalize_query(query)
        if not normalized:
            return []
        ranked: list[tuple[int, tuple[int, str], int]] = []
        for material_id, material in self._materials.items():
            if not self._permissions.get(material_id, False):
                continue
            score = self._material_score(material_id, normalized)
            if score <= 0:
                continue
            ranked.append((score, self.random.rank_key("research.search_internal", normalized, material_id), material_id))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        safe_limit = max(1, min(limit, 12))
        return [material_id for _score, _tie, material_id in ranked[:safe_limit]]

    async def read_internal(self, source_ids: list[str], query: str, *, page_limit: int) -> list[EvidenceRecord]:
        if not source_ids:
            raise ResearchEnvironmentError("invalid_internal_source", "No internal source IDs were supplied.", recoverable=False)
        material_ids = [_parse_material_source_id(value) for value in source_ids]
        if len(material_ids) != len(set(material_ids)):
            raise ResearchEnvironmentError("duplicate_internal_source", "Internal source IDs must be unique.", recoverable=False)
        unknown = [material_id for material_id in material_ids if material_id not in self._materials]
        if unknown:
            raise ResearchEnvironmentError("invalid_material", "A requested material is absent from this snapshot.", recoverable=False)
        denied = [material_id for material_id in material_ids if not self._permissions.get(material_id, False)]
        if denied:
            raise ResearchEnvironmentError("permission_denied", "A requested material is not permitted in this snapshot.", recoverable=False)

        normalized = _normalize_query(query)
        candidates = [page for page in self.world.pdf_page_index.pages if page.material_id in material_ids]
        readable = [page for page in candidates if not page.corrupt and page.excerpt is not None]
        if not readable:
            code = "pdf_corrupt" if candidates and all(page.corrupt for page in candidates) else "source_unreadable"
            raise ResearchEnvironmentError(code, "Requested snapshot PDF evidence is not readable.", recoverable=True)
        ranked = [
            (
                self._page_score(page.material_id, page.page, normalized),
                self.random.rank_key("research.read_internal", normalized, page.material_id, page.page),
                page,
            )
            for page in readable
        ]
        ranked.sort(key=lambda item: (-item[0], item[1], item[2].material_id, item[2].page))
        safe_limit = max(1, min(page_limit, 500))
        return [self._evidence_for_page(page) for _score, _tie, page in ranked[:safe_limit]]

    async def search_web(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del query, limit
        raise ResearchEnvironmentError("snapshot_web_disabled", "Snapshot environments do not access the Web.", recoverable=False)

    async def read_web(self, source_ids: list[str], query: str) -> list[EvidenceRecord]:
        del source_ids, query
        raise ResearchEnvironmentError("snapshot_web_disabled", "Snapshot environments do not access the Web.", recoverable=False)

    async def search_scholar(self, query: str, *, limit: int) -> list[ResearchSourceRef]:
        del query, limit
        raise ResearchEnvironmentError("snapshot_scholar_disabled", "Snapshot environments do not access Scholar.", recoverable=False)

    def is_material_allowed(self, material_id: int) -> bool:
        return bool(self._permissions.get(material_id, False))

    def material(self, material_id: int):
        return self._materials.get(material_id)

    def pages_for_materials(self, material_ids: list[int]):
        return [page for page in self.world.pdf_page_index.pages if page.material_id in material_ids]

    def pdf_page(self, material_id: int, page: int):
        return self._pages.get((material_id, page))

    def _source_for_material(self, material_id: int) -> ResearchSourceRef:
        material = self._materials[material_id]
        return ResearchSourceRef(
            source_id=f"material:{material_id}",
            source_type=ResearchSourceType.INTERNAL_MATERIAL,
            title=material.title,
            source_uri=f"snapshot://materials/{material_id}",
            material_id=material_id,
            reliability=0.8,
            access_scope="snapshot:materials.read",
        )

    def _evidence_for_page(self, page) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=f"snapshot-evidence-{page.material_id}-{page.page}",
            source_type=ResearchSourceType.INTERNAL_PDF,
            source_uri=f"snapshot://materials/{page.material_id}/pages/{page.page}",
            title=page.title,
            material_id=page.material_id,
            page=page.page,
            excerpt=page.excerpt or "[corrupt snapshot page]",
            reliability=0.85,
            access_scope="snapshot:materials.read",
            retrieved_at=self.clock.now,
        )

    def _material_score(self, material_id: int, query: str) -> int:
        material = self._materials[material_id]
        text = " ".join(
            [
                material.title,
                material.description or "",
                *material.tags,
                material.school or "",
                material.college or "",
                material.major or "",
                material.course_category or "",
                *self._retriever_terms.get(material_id, ()),
            ]
        ).lower()
        return _query_score(query, text)

    def _page_score(self, material_id: int, page_number: int, query: str) -> int:
        page = next(item for item in self.world.pdf_page_index.pages if item.material_id == material_id and item.page == page_number)
        text = " ".join(
            [
                page.title,
                page.excerpt or "",
                *page.anchor_terms,
                *page.question_types,
                *page.question_numbers,
                *page.solution_signals,
            ]
        ).lower()
        return _query_score(query, text)


def _parse_material_source_id(value: str) -> int:
    if not value.startswith("material:"):
        raise ResearchEnvironmentError("invalid_internal_source", "Snapshot source IDs must use material:<id>.", recoverable=False)
    try:
        material_id = int(value.removeprefix("material:"))
    except ValueError as exc:
        raise ResearchEnvironmentError("invalid_internal_source", "Snapshot material source ID is invalid.", recoverable=False) from exc
    if material_id <= 0:
        raise ResearchEnvironmentError("invalid_internal_source", "Snapshot material source ID is invalid.", recoverable=False)
    return material_id


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split()).strip()


def _query_terms(query: str) -> set[str]:
    latin_terms = re.findall(r"[a-z0-9_]+", query.lower())
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", query))
    terms = set(latin_terms)
    if cjk:
        terms.add(cjk)
        terms.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
        terms.update(cjk)
    return {term for term in terms if term}


def _query_score(query: str, text: str) -> int:
    if not query:
        return 0
    score = 12 if query in text else 0
    for term in _query_terms(query):
        if term in text:
            score += max(1, min(6, len(term)))
    return score
