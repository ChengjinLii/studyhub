from __future__ import annotations

from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.environment import ReplayableAgentEnvironment, ReplayIndex
from studyhub_agent.benchmark_v1.schema import (
    BENCHMARK_VERSION as V1_BENCHMARK_VERSION,
)
from studyhub_agent.benchmark_v1.schema import (
    ENVIRONMENT_SCHEMA_VERSION as V1_ENVIRONMENT_SCHEMA_VERSION,
)
from studyhub_agent.benchmark_v2.schema import BENCHMARK_VERSION, ENVIRONMENT_SCHEMA_VERSION


class ReplayableAgentEnvironmentV2(ReplayableAgentEnvironment):
    """V2 replay environment with discovery and observation-dependent source gates."""

    def __init__(self, environment: dict[str, Any], *, root: Path) -> None:
        if environment.get("schema_version") != ENVIRONMENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported environment schema: {environment.get('schema_version')}")
        if environment.get("benchmark_version") != BENCHMARK_VERSION:
            raise ValueError(f"unsupported benchmark version: {environment.get('benchmark_version')}")
        original = dict(environment)
        compatibility = dict(environment)
        compatibility["schema_version"] = V1_ENVIRONMENT_SCHEMA_VERSION
        compatibility["benchmark_version"] = V1_BENCHMARK_VERSION
        super().__init__(compatibility, root=root)
        self.environment = original
        self._direct_read_allowlist = set(map(str, original.get("direct_read_allowlist", [])))

    def _unlocked(self, document: dict[str, Any]) -> bool:
        prerequisites = set(map(str, document.get("unlock_after_source_ids", [])))
        return prerequisites <= self.trace.read_source_ids

    def _knowledge_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = int(arguments.get("limit", 5))
        visible = [row for row in self._documents.values() if self._can_read(row) and self._unlocked(row)]
        hits = ReplayIndex(visible).search(str(arguments["query"]), limit=limit)
        results = []
        for score, row in hits:
            source_id = str(row["source_id"])
            self.trace.discovered_source_ids.add(source_id)
            results.append(
                {
                    "source_id": source_id,
                    "material_id": row.get("material_id"),
                    "title": row.get("title", ""),
                    "snippet": str(row.get("text", ""))[:320],
                    "score": score,
                    "source_quality": row.get("source_quality", "studyhub_free_preview"),
                    "citation": f"[{source_id}]",
                }
            )
        return {
            "ok": True,
            "query": arguments["query"],
            "results": results,
            "returned_source_ids": [row["source_id"] for row in results],
            "retrieval_backend": "deterministic_bm25_mixed_zh_en_v2",
        }

    def _knowledge_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source_id = str(arguments["source_id"])
        if source_id not in self.trace.discovered_source_ids and source_id not in self._direct_read_allowlist:
            return self._policy_error("source_not_discovered", source_id=source_id)
        document = self._documents.get(source_id)
        if document is not None and not self._unlocked(document):
            return self._policy_error("source_not_unlocked", source_id=source_id)
        return super()._knowledge_read(arguments)
