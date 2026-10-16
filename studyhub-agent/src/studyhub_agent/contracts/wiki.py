from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from studyhub_agent.contracts.knowledge import KnowledgeModel, digest


class WikiFact(KnowledgeModel):
    kind: Literal["entity", "concept"]
    name: str = Field(min_length=1, max_length=160)
    aliases: tuple[str, ...] = Field(default=(), max_length=20)
    claim: str = Field(min_length=1, max_length=2000)
    quote: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def meaningful(self) -> WikiFact:
        if not all(value.strip() for value in (self.name, self.claim, self.quote)):
            raise ValueError("empty wiki fact")
        if any(not alias.strip() or len(alias) > 160 for alias in self.aliases):
            raise ValueError("invalid wiki alias")
        return self


class WikiMapRecord(KnowledgeModel):
    chunk_id: str
    document_id: str
    revision: str
    knowledge_base_id: str
    extractor: str
    facts: tuple[WikiFact, ...] = Field(max_length=32)


class WikiSource(KnowledgeModel):
    document_id: str
    chunk_id: str
    revision: str
    page_start: int | None = None
    page_end: int | None = None
    quote: str


class WikiClaim(KnowledgeModel):
    text: str
    sources: tuple[WikiSource, ...]


class WikiPage(KnowledgeModel):
    page_id: str
    knowledge_base_id: str
    kind: Literal["entity", "concept"]
    name: str
    aliases: tuple[str, ...] = ()
    claims: tuple[WikiClaim, ...]
    body: str
    revision: str

    @model_validator(mode="after")
    def content_revision(self) -> WikiPage:
        payload = self.model_dump_json(exclude={"revision"})
        if self.revision != digest(payload):
            raise ValueError("wiki page revision does not match its content")
        return self


class WikiSnapshot(KnowledgeModel):
    schema_version: Literal["studyhub.wiki.v1"] = "studyhub.wiki.v1"
    corpus_fingerprint: str
    extractor: str
    knowledge_base_ids: tuple[str, ...]
    document_ids: tuple[str, ...] | None = None
    records: tuple[WikiMapRecord, ...]
    pages: tuple[WikiPage, ...]

    @model_validator(mode="after")
    def unique_records(self) -> WikiSnapshot:
        if len({r.chunk_id for r in self.records}) != len(self.records):
            raise ValueError("duplicate wiki map record")
        if len({p.page_id for p in self.pages}) != len(self.pages):
            raise ValueError("duplicate wiki page")
        return self
