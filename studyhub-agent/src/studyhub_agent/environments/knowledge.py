from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from studyhub_agent.contracts.episode import EpisodeSpec, Observation, ToolCall
from studyhub_agent.contracts.knowledge import ListInput, ReadInput, SearchInput, search_evidence
from studyhub_agent.contracts.wiki import WikiReadPageInput, WikiSearchInput
from studyhub_agent.environments.base import EnvironmentInfraError
from studyhub_agent.knowledge.providers import KnowledgeBackendError
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.tools.knowledge import KNOWLEDGE_TOOLS, WIKI_KNOWLEDGE_TOOLS


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
        return KNOWLEDGE_TOOLS + (WIKI_KNOWLEDGE_TOOLS if self.retriever.wiki is not None else ())

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
                for context, source in zip(row["context"], hit.context, strict=True):
                    context["citation"] = source.citation
            return payload, [row.chunk_id for row in search_evidence(result)]
        if call.name == "read_document":
            args = ReadInput.model_validate(call.arguments)
            evidence = self.retriever.read(
                args.id, offset=args.offset, limit=args.limit, context=args.context, query=args.query or None
            )
            next_offset = args.offset + len(evidence)
            if args.query:
                has_next = bool(self.retriever.read(args.id, offset=next_offset, limit=1, query=args.query or None))
            else:
                total = sum(row.document_id == args.id for row in self.retriever.chunks.values())
                has_next = bool(evidence) and next_offset < total
            return {
                "evidence": [row.model_dump() | {"citation": row.citation} for row in evidence],
                "next_offset": next_offset if has_next else None,
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
        if call.name == "wiki_search":
            args = WikiSearchInput.model_validate(call.arguments)
            if self.retriever.wiki is None:
                raise ValueError("wiki_unavailable")
            pages = self.retriever.wiki.search(args.query, args.limit)
            return {
                "pages": [
                    {
                        "page_id": page.page_id,
                        "name": page.name,
                        "kind": page.kind,
                        "aliases": list(page.aliases),
                        "revision": page.revision,
                        "claims_count": len(page.claims),
                    }
                    for page in pages
                ]
            }, []
        if call.name == "wiki_read_page":
            args = WikiReadPageInput.model_validate(call.arguments)
            if self.retriever.wiki is None:
                raise ValueError("wiki_unavailable")
            page = next((row for row in self.retriever.wiki.pages if row.page_id == args.page_id), None)
            if page is None:
                raise ValueError("wiki_page_not_found")
            claims, exposed = [], set()
            for claim in page.claims[args.offset : args.offset + args.limit]:
                sources = []
                # Bound each claim's sources; never hide that others were omitted.
                for source in claim.sources[:5]:
                    evidence = self.retriever.evidence(self.retriever.chunks[source.chunk_id])
                    sources.append(
                        {
                            "document_id": source.document_id,
                            "chunk_id": source.chunk_id,
                            "revision": source.revision,
                            "page_start": source.page_start,
                            "page_end": source.page_end,
                            "quote": source.quote,
                            "citation": evidence.citation,
                        }
                    )
                    exposed.add(evidence.chunk_id)
                claims.append(
                    {
                        "text": claim.text,
                        "sources": sources,
                        "sources_total": len(claim.sources),
                        "sources_truncated": len(claim.sources) > len(sources),
                    }
                )
            next_offset = args.offset + len(claims)
            payload = {
                "page_id": page.page_id,
                "name": page.name,
                "kind": page.kind,
                "aliases": list(page.aliases),
                "revision": page.revision,
                "claims": claims,
                "next_offset": next_offset if next_offset < len(page.claims) else None,
                "note": "Source citations refer only to displayed verbatim quotes; read_document checks context.",
            }
            if len(json.dumps(payload, ensure_ascii=False)) > 16000:
                raise ValueError("wiki_read_output_budget_exceeded")
            return payload, sorted(exposed)
        raise ValueError("unknown_tool")

    def trace(self) -> dict[str, Any]:
        return {**self.retriever.configuration, "tool_calls": list(self._calls), "evidence_ids": sorted(self._exposed)}
