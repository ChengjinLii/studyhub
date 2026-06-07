from __future__ import annotations

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


@dataclass(slots=True)
class MaterialPageEvidence:
    material_id: int
    title: str
    page: int
    text: str
    score: int

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "title": self.title,
            "page": self.page,
            "text": self.text,
        }

    def to_source_payload(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "title": self.title,
            "page": self.page,
            "excerpt": self.text,
        }


class MaterialPdfEvidenceService:
    """Best-effort page-level PDF evidence for the StudyHub Agent.

    This first production-safe slice only reads free materials or materials owned
    by the current user. Paid-material purchase-aware evidence can be added once
    it shares the exact same authorization path as downloads.
    """

    def __init__(self, settings: Settings, asset_store: MaterialAssetStore) -> None:
        self.settings = settings
        self.asset_store = asset_store

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
            all_evidence.extend(self.collect_for_material(material, query))
        all_evidence.sort(key=lambda item: (-item.score, item.material_id, item.page))
        return all_evidence[: max(1, self.settings.ai_agent_pdf_evidence_max_pages)]

    def collect_for_material(self, material: MaterialRecord, query: str) -> list[MaterialPageEvidence]:
        key = (material.file_storage_key or "").strip()
        if not key:
            return []
        try:
            pdf_bytes = self.asset_store.read_bytes(key, max_size_bytes=self.settings.ai_agent_pdf_evidence_max_bytes)
        except Exception:
            return []
        pages = extract_pdf_page_texts(pdf_bytes, max_pages=max(1, self.settings.ai_agent_pdf_evidence_max_pages))
        if not pages:
            return []
        query_terms = _query_terms(query)
        evidence = [
            MaterialPageEvidence(
                material_id=int(material.id),
                title=material.title or f"资料 #{material.id}",
                page=page_number,
                text=_compact_text(text),
                score=_score_page(text, query_terms),
            )
            for page_number, text in pages
            if text.strip()
        ]
        evidence.sort(key=lambda item: (-item.score, item.page))
        return evidence[: max(1, self.settings.ai_agent_pdf_evidence_max_pages)]

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


def _score_page(text: str, query_terms: list[str]) -> int:
    normalized = text.lower()
    score = 0
    for term in query_terms:
        score += normalized.count(term) * 10
    for term in ("真题", "题型", "解析", "答案", "常考", "考试", "例题", "选择", "填空", "计算", "证明"):
        if term in normalized:
            score += 4
    return score


def _compact_text(text: str, *, max_chars: int = 700) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:max_chars]
