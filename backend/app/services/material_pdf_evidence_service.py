from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any

from app.core.config import Settings
from app.integrations.material_asset_store import MaterialAssetStore
from app.models.materials import MaterialRecord


PDF_EVIDENCE_QUERY_TERMS = (
    "pdf",
    "真题",
    "题型",
    "常考",
    "往年",
    "历年",
    "试卷",
    "考试",
    "解析",
    "分析",
    "总结",
    "讲解",
    "错题",
    "复习",
)

QUESTION_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("选择题", ("选择题", "单选", "多选", "选择")),
    ("填空题", ("填空题", "填空")),
    ("判断题", ("判断题", "判断")),
    ("简答题", ("简答题", "简答", "问答")),
    ("计算题", ("计算题", "计算", "求解", "推导")),
    ("证明题", ("证明题", "证明")),
    ("分析题", ("分析题", "分析")),
    ("实验题", ("实验题", "实验")),
    ("编程题", ("编程题", "程序", "代码")),
)

KNOWLEDGE_SIGNAL_TERMS = (
    "调制",
    "解调",
    "频谱",
    "带宽",
    "误码率",
    "匹配滤波",
    "判决",
    "信噪比",
    "傅里叶",
    "卷积",
    "链表",
    "二叉树",
    "排序",
    "积分",
    "微分",
    "极限",
    "概率",
    "分布",
)


@dataclass(frozen=True, slots=True)
class MaterialPageChunk:
    page: int
    text: str
    years: tuple[str, ...]
    question_types: tuple[str, ...]
    knowledge_signals: tuple[str, ...]


@dataclass(slots=True)
class MaterialPageEvidence:
    material_id: int
    title: str
    page: int
    text: str
    score: int
    years: tuple[str, ...] = ()
    question_types: tuple[str, ...] = ()
    knowledge_signals: tuple[str, ...] = ()

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "material_id": self.material_id,
            "title": self.title,
            "page": self.page,
            "text": self.text,
        }
        if self.years:
            payload["years"] = list(self.years)
        if self.question_types:
            payload["question_types"] = list(self.question_types)
        if self.knowledge_signals:
            payload["knowledge_signals"] = list(self.knowledge_signals)
        return payload

    def to_source_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "material_id": self.material_id,
            "title": self.title,
            "page": self.page,
            "excerpt": self.text,
        }
        if self.years:
            payload["years"] = list(self.years)
        if self.question_types:
            payload["question_types"] = list(self.question_types)
        return payload


class MaterialPdfEvidenceService:
    """Best-effort page-level PDF evidence for the StudyHub Agent.

    This first production-safe slice only reads free materials or materials owned
    by the current user. Paid-material purchase-aware evidence can be added once
    it shares the exact same authorization path as downloads.
    """

    def __init__(self, settings: Settings, asset_store: MaterialAssetStore) -> None:
        self.settings = settings
        self.asset_store = asset_store
        self._chunk_cache: OrderedDict[tuple[str, int, int], tuple[MaterialPageChunk, ...]] = OrderedDict()

    def should_load_evidence(self, query: str) -> bool:
        normalized = query.strip().lower()
        return bool(normalized) and any(term.lower() in normalized for term in PDF_EVIDENCE_QUERY_TERMS)

    def collect_for_materials(
        self,
        materials: list[MaterialRecord],
        query: str,
        *,
        current_user_id: int | None,
    ) -> list[MaterialPageEvidence]:
        if not self.settings.ai_agent_pdf_evidence_enabled or not self.should_load_evidence(query):
            return []
        max_materials = max(0, int(self.settings.ai_agent_pdf_evidence_max_materials or 0))
        if max_materials <= 0:
            return []
        all_evidence: list[MaterialPageEvidence] = []
        scanned = 0
        for material in materials:
            if scanned >= max_materials:
                break
            if not self._can_read_pdf_material(material, current_user_id):
                continue
            scanned += 1
            all_evidence.extend(self.collect_for_material(material, query, cacheable=bool(material.is_free)))
        all_evidence.sort(key=lambda item: (-item.score, item.material_id, item.page))
        return all_evidence[: max(1, self.settings.ai_agent_pdf_evidence_max_pages)]

    def collect_for_material(
        self,
        material: MaterialRecord,
        query: str,
        *,
        cacheable: bool | None = None,
    ) -> list[MaterialPageEvidence]:
        key = (material.file_storage_key or "").strip()
        if not key:
            return []
        should_cache = bool(material.is_free) if cacheable is None else cacheable
        chunks = self._load_page_chunks(key, cacheable=should_cache)
        if not chunks:
            return []
        query_terms = _query_terms(query)
        evidence = [
            MaterialPageEvidence(
                material_id=int(material.id),
                title=material.title or f"资料 #{material.id}",
                page=chunk.page,
                text=chunk.text,
                score=_score_page(chunk, query_terms),
                years=chunk.years,
                question_types=chunk.question_types,
                knowledge_signals=chunk.knowledge_signals,
            )
            for chunk in chunks
            if chunk.text.strip()
        ]
        evidence.sort(key=lambda item: (-item.score, item.page))
        return evidence[: max(1, self.settings.ai_agent_pdf_evidence_max_pages)]

    def _load_page_chunks(self, key: str, *, cacheable: bool) -> tuple[MaterialPageChunk, ...]:
        max_pages = max(1, int(self.settings.ai_agent_pdf_evidence_max_pages or 0))
        max_bytes = max(1, int(self.settings.ai_agent_pdf_evidence_max_bytes or 0))
        cache_key = (key, max_pages, max_bytes)
        cache_enabled = bool(getattr(self.settings, "ai_agent_pdf_extract_cache_enabled", True))
        if cacheable and cache_enabled:
            cached = self._chunk_cache.get(cache_key)
            if cached is not None:
                self._chunk_cache.move_to_end(cache_key)
                return cached
        try:
            pdf_bytes = self.asset_store.read_bytes(key, max_size_bytes=max_bytes)
        except Exception:
            return ()
        chunks = tuple(build_pdf_page_chunks(pdf_bytes, max_pages=max_pages))
        if cacheable and chunks and cache_enabled:
            self._chunk_cache[cache_key] = chunks
            self._chunk_cache.move_to_end(cache_key)
            max_entries = max(0, int(getattr(self.settings, "ai_agent_pdf_extract_cache_max_entries", 64) or 0))
            while max_entries > 0 and len(self._chunk_cache) > max_entries:
                self._chunk_cache.popitem(last=False)
            if max_entries <= 0:
                self._chunk_cache.clear()
        return chunks

    def _can_read_pdf_material(self, material: MaterialRecord, current_user_id: int | None) -> bool:
        if not _looks_like_pdf(material):
            return False
        if bool(material.is_free):
            return True
        return current_user_id is not None and int(material.uploader_id or 0) == current_user_id


def extract_pdf_page_texts(pdf_bytes: bytes, *, max_pages: int) -> list[tuple[int, str]]:
    pages = _extract_with_pypdf(pdf_bytes, max_pages=max_pages)
    if pages:
        return pages
    pages = _extract_with_pymupdf(pdf_bytes, max_pages=max_pages)
    if pages:
        return pages
    return _extract_with_simple_pdf_text_fallback(pdf_bytes, max_pages=max_pages)


def build_pdf_page_chunks(pdf_bytes: bytes, *, max_pages: int) -> list[MaterialPageChunk]:
    chunks: list[MaterialPageChunk] = []
    for page_number, text in extract_pdf_page_texts(pdf_bytes, max_pages=max_pages):
        compact = _compact_text(text)
        if not compact:
            continue
        chunks.append(
            MaterialPageChunk(
                page=page_number,
                text=compact,
                years=tuple(_extract_years(compact)),
                question_types=tuple(_extract_question_types(compact)),
                knowledge_signals=tuple(_extract_knowledge_signals(compact)),
            )
        )
    return chunks


def _extract_with_pypdf(pdf_bytes: bytes, *, max_pages: int) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except Exception:
        return []
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = []
        for index, page in enumerate(reader.pages[:max_pages], start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((index, text))
        return pages
    except Exception:
        return []


def _extract_with_pymupdf(pdf_bytes: bytes, *, max_pages: int) -> list[tuple[int, str]]:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:
        return []
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for index in range(min(max_pages, document.page_count)):
            text = document.load_page(index).get_text("text") or ""
            if text.strip():
                pages.append((index + 1, text))
        document.close()
        return pages
    except Exception:
        return []


def _extract_with_simple_pdf_text_fallback(pdf_bytes: bytes, *, max_pages: int) -> list[tuple[int, str]]:
    text = pdf_bytes.decode("latin-1", errors="ignore")
    page_segments = re.split(r"/Type\s*/Page\b", text)
    if len(page_segments) <= 1:
        page_segments = [text]
    pages: list[tuple[int, str]] = []
    page_number = 1
    for segment in page_segments:
        if len(pages) >= max_pages:
            break
        strings = [_decode_pdf_literal(match) for match in re.findall(r"\((?:\\.|[^\\)]){1,2000}\)", segment)]
        compact = _compact_text(" ".join(item for item in strings if item))
        if compact:
            pages.append((page_number, compact))
            page_number += 1
    return pages


def _decode_pdf_literal(value: str) -> str:
    body = value[1:-1]
    body = body.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    body = body.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t")
    try:
        repaired = body.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return body
    return repaired if repaired.strip() else body


def _looks_like_pdf(material: MaterialRecord) -> bool:
    file_type = (material.file_type or "").strip().lower()
    filename = (material.original_filename or "").strip().lower()
    key = (material.file_storage_key or "").strip().lower()
    return file_type == "pdf" or filename.endswith(".pdf") or key.endswith(".pdf")


def _query_terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query) if len(term.strip()) >= 2]


def _score_page(chunk: MaterialPageChunk, query_terms: list[str]) -> int:
    normalized = chunk.text.lower()
    score = 0
    for term in query_terms:
        score += normalized.count(term) * 10
    for term in ("真题", "题型", "解析", "答案", "常考", "考试", "例题", "选择", "填空", "计算", "证明"):
        if term in normalized:
            score += 4
    score += len(chunk.question_types) * 3
    score += len(chunk.years) * 2
    score += len(chunk.knowledge_signals)
    return score


def _compact_text(text: str, *, max_chars: int = 700) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:max_chars]


def _extract_years(text: str) -> list[str]:
    years = []
    for match in re.findall(r"(?<!\d)(20[0-3]\d)(?!\d)", text):
        if match not in years:
            years.append(match)
    return years[:5]


def _extract_question_types(text: str) -> list[str]:
    result: list[str] = []
    normalized = text.lower()
    for label, aliases in QUESTION_TYPE_PATTERNS:
        if any(alias.lower() in normalized for alias in aliases) and label not in result:
            result.append(label)
    return result[:5]


def _extract_knowledge_signals(text: str) -> list[str]:
    normalized = text.lower()
    result: list[str] = []
    for term in KNOWLEDGE_SIGNAL_TERMS:
        if term.lower() in normalized and term not in result:
            result.append(term)
    return result[:8]
