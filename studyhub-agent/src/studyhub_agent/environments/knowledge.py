from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from studyhub_agent.contracts.episode import EpisodeSpec, Observation, ToolCall
from studyhub_agent.contracts.knowledge import ListInput, ReadInput, SearchInput
from studyhub_agent.environments.base import EnvironmentInfraError
from studyhub_agent.knowledge.providers import KnowledgeBackendError
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.tools.knowledge import KNOWLEDGE_TOOLS


class KnowledgeEnvironment:
    def __init__(self, retriever: KnowledgeRetriever) -> None:
        self.retriever = retriever
        self._started = False
        self._exposed: set[str] = set()
        self._calls: list[str] = []

    def reset(self, spec: EpisodeSpec) -> None:
        self._started = True
        self._exposed = set()
        self._calls = []

    def tool_specs(self):
        return KNOWLEDGE_TOOLS

    def execute(self, call: ToolCall) -> Observation:
        if not self._started:
            raise RuntimeError("KnowledgeEnvironment.execute called before reset")
        self._calls.append(call.name)
        try:
            payload, evidence_ids = self._execute(call)
        except KnowledgeBackendError as exc:
            raise EnvironmentInfraError(str(exc)) from exc
        except (ValueError, ValidationError) as exc:
            error = "invalid_arguments" if isinstance(exc, ValidationError) else str(exc)
            return Observation(
                call_id=call.call_id, name=call.name, ok=False, payload={"error": error}, error_code="tool_error"
            )
        self._exposed.update(evidence_ids)
        return Observation(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            payload=payload,
            details={"evidence_ids": evidence_ids, "corpus_fingerprint": self.retriever.fingerprint},
        )

    def _execute(self, call: ToolCall) -> tuple[dict, list[str]]:
        if call.name == "search_knowledge":
            args = SearchInput.model_validate(call.arguments)
            result = self.retriever.search(**args.model_dump())
            payload = result.model_dump(mode="json")
            for row, hit in zip(payload["hits"], result.hits, strict=True):
                row["evidence"]["citation"] = hit.evidence.citation
            return payload, [hit.evidence.chunk_id for hit in result.hits]
        if call.name == "read_document":
            args = ReadInput.model_validate(call.arguments)
            evidence = self.retriever.read(args.id, offset=args.offset, limit=args.limit, context=args.context)
            total = sum(row.document_id == args.id for row in self.retriever.chunks.values())
            next_offset = args.offset + len(evidence)
            return {
                "evidence": [row.model_dump() | {"citation": row.citation} for row in evidence],
                "next_offset": next_offset if evidence and next_offset < total else None,
            }, [row.chunk_id for row in evidence]
        if call.name == "list_documents":
            args = ListInput.model_validate(call.arguments)
            rows = sorted(
                (row for row in self.retriever.documents.values() if args.keyword.casefold() in row.title.casefold()),
                key=lambda row: row.document_id,
            )
            selected = rows[args.offset : args.offset + args.limit]
            next_offset = args.offset + len(selected)
            return {
                "documents": [
                    {key: getattr(row, key) for key in ("document_id", "knowledge_base_id", "title", "revision")}
                    for row in selected
                ],
                "next_offset": next_offset if next_offset < len(rows) else None,
            }, []
        raise ValueError("unknown_tool")

    def trace(self) -> dict[str, Any]:
        return {**self.retriever.configuration, "tool_calls": list(self._calls), "evidence_ids": sorted(self._exposed)}
