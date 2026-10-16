from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PageSpan(KnowledgeModel):
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    method: Literal["native", "ocr"]


def source_revision(text: str, pages: tuple[PageSpan, ...], source_sha256: str | None, parser: str) -> str:
    if not pages and source_sha256 is None:
        return digest(text)
    return digest(
        json.dumps(
            [text, [page.model_dump() for page in pages], source_sha256, parser], ensure_ascii=False, sort_keys=True
        )
    )


class Document(KnowledgeModel):
    document_id: str
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(max_length=2_000_000)
    revision: str
    pages: tuple[PageSpan, ...] = ()
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parser: str = "text-v1"

    @model_validator(mode="after")
    def validate_identity(self) -> Document:
        expected = "d_" + digest(json.dumps([self.knowledge_base_id, self.source], ensure_ascii=False))[:32]
        if self.document_id != expected or self.revision != source_revision(
            self.text, self.pages, self.source_sha256, self.parser
        ):
            raise ValueError("document identity or source revision does not match its content")
        cursor = 0
        for number, page in enumerate(self.pages, 1):
            if page.page != number or page.start != cursor or not page.start <= page.end <= len(self.text):
                raise ValueError("invalid page source locator")
            cursor = page.end
        if self.pages and cursor != len(self.text):
            raise ValueError("page locators do not cover the source")
        return self


def page_range(document: Document, start: int, end: int) -> tuple[int | None, int | None]:
    pages = [page.page for page in document.pages if page.start < end and page.end > start]
    return (pages[0], pages[-1]) if pages else (None, None)


class Chunk(KnowledgeModel):
    chunk_id: str
    document_id: str
    revision: str
    parent_id: str
    ordinal: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    context_header: str = ""
    text: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_identity(self) -> Chunk:
        key = json.dumps([self.document_id, self.revision, self.start, self.end, self.context_header])
        if self.chunk_id != "k_" + digest(key)[:32] or self.end - self.start != len(self.text):
            raise ValueError("chunk identity or source offsets do not match its content")
        if self.line_end < self.line_start:
            raise ValueError("invalid source line range")
        return self


class ParentChunk(KnowledgeModel):
    parent_id: str
    document_id: str
    revision: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    context_header: str = ""
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_identity(self) -> ParentChunk:
        expected = "p_" + digest(f"{self.document_id}:{self.revision}:{self.start}:{self.end}")[:32]
        if self.parent_id != expected or self.end - self.start != len(self.text):
            raise ValueError("invalid parent identity or source offsets")
        return self


class Corpus(KnowledgeModel):
    schema_version: Literal["studyhub.knowledge.v1"] = "studyhub.knowledge.v1"
    chunker_version: Literal["heading-protected-v1"] = "heading-protected-v1"
    documents: tuple[Document, ...] = ()
    chunks: tuple[Chunk, ...] = ()
    parents: tuple[ParentChunk, ...] = ()

    @model_validator(mode="after")
    def validate_sources(self) -> Corpus:
        documents = {row.document_id: row for row in self.documents}
        if len(documents) != len(self.documents) or len({row.chunk_id for row in self.chunks}) != len(self.chunks):
            raise ValueError("duplicate document or chunk identity")
        ordinals: set[tuple[str, int]] = set()
        parents = {row.parent_id: row for row in self.parents}
        if len(parents) != len(self.parents):
            raise ValueError("duplicate parent identity")
        for parent in self.parents:
            document = documents.get(parent.document_id)
            if (
                document is None
                or parent.revision != document.revision
                or document.text[parent.start : parent.end] != parent.text
                or page_range(document, parent.start, parent.end) != (parent.page_start, parent.page_end)
            ):
                raise ValueError("parent source is missing or stale")
        for chunk in self.chunks:
            document = documents.get(chunk.document_id)
            if document is None or document.revision != chunk.revision:
                raise ValueError("chunk belongs to a missing or stale document revision")
            if document.text[chunk.start : chunk.end] != chunk.text:
                raise ValueError("chunk body differs from the original source")
            if page_range(document, chunk.start, chunk.end) != (chunk.page_start, chunk.page_end):
                raise ValueError("chunk page locator differs from the source")
            if parents:
                parent = parents.get(chunk.parent_id)
                if (
                    parent is None
                    or parent.document_id != chunk.document_id
                    or not parent.start <= chunk.start < chunk.end <= parent.end
                ):
                    raise ValueError("child has a missing or inconsistent parent")
            start_line = document.text.count("\n", 0, chunk.start) + 1
            end_line = start_line + chunk.text.count("\n") - int(chunk.text.endswith("\n"))
            if (chunk.line_start, chunk.line_end) != (start_line, end_line):
                raise ValueError("chunk line locator differs from the original source")
            ordinal = (chunk.document_id, chunk.ordinal)
            if ordinal in ordinals:
                raise ValueError("duplicate chunk ordinal")
            ordinals.add(ordinal)
        return self

    @property
    def fingerprint(self) -> str:
        return digest(self.model_dump_json())


class KnowledgeScope(KnowledgeModel):
    knowledge_base_ids: frozenset[str]
    document_ids: frozenset[str] | None = None

    def allows(self, document: Document) -> bool:
        return document.knowledge_base_id in self.knowledge_base_ids and (
            self.document_ids is None or document.document_id in self.document_ids
        )


class Evidence(KnowledgeModel):
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    revision: str
    title: str
    context_header: str
    text: str
    start: int
    end: int
    line_start: int
    line_end: int
    parent_id: str = ""
    page_start: int | None = None
    page_end: int | None = None

    @property
    def citation(self) -> str:
        return f"[{self.chunk_id}]"


class SearchHit(KnowledgeModel):
    evidence: Evidence
    score: float = Field(allow_inf_nan=False)
    channels: tuple[str, ...]
    context: tuple[Evidence, ...] = ()


class SearchResult(KnowledgeModel):
    query: str
    requested_mode: Literal["keyword", "semantic", "hybrid"]
    effective_mode: Literal["keyword", "semantic", "hybrid"]
    hits: tuple[SearchHit, ...]
    notices: tuple[str, ...] = ()


def search_evidence(result: SearchResult) -> tuple[Evidence, ...]:
    rows = {}
    for hit in result.hits:
        for evidence in (hit.evidence, *hit.context):
            rows.setdefault(evidence.chunk_id, evidence)
    return tuple(rows.values())


class CitationCheck(KnowledgeModel):
    ok: bool
    cited: tuple[str, ...]
    unknown: tuple[str, ...]
    missing: bool


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=2000, description="完整问题；精确匹配时填写关键词")
    mode: Literal["keyword", "semantic", "hybrid"] = Field(default="hybrid", description="检索方式")
    limit: int = Field(default=5, ge=1, le=30, description="最多返回的片段数量")


class ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128, description="检索结果中的文档 ID 或片段 ID")
    offset: int = Field(default=0, ge=0, description="文档内片段位置，从零开始")
    limit: int = Field(default=5, ge=1, le=20, description="文档分页大小")
    context: int = Field(default=0, ge=0, le=5, description="读取片段时两侧各扩展的邻近片段数")


class ListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    keyword: str = Field(default="", max_length=200, description="可选，按文档标题过滤")
    offset: int = Field(default=0, ge=0, description="文档列表位置，从零开始")
    limit: int = Field(default=10, ge=1, le=30, description="最多返回的文档数量")
