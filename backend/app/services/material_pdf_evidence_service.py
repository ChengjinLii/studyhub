from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import re
from typing import Any

from app.core.config import Settings
from app.integrations.material_asset_store import MaterialAssetStore
from app.models.materials import MaterialRecord
from app.services.agent_material_signal_service import safe_material_value
from app.services.read_support import ROLE_ADMIN, ROLE_DEVELOPER, has_role


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
    "不会",
    "怎么做",
    "这份资料",
    "这几份",
    "讲什么",
    "内容是什么",
    "概括",
    "适合",
    "适合我",
    "该不该看",
    "值得看",
    "能不能看",
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

SOURCE_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("past_exam", ("真题", "往年", "历年", "试卷", "期末", "期中")),
    ("answer_explanation", ("解析", "答案", "标答", "参考答案")),
    ("lecture_notes", ("讲义", "课件", "笔记")),
    ("study_outline", ("速成", "提纲", "复习")),
    ("exercise", ("习题", "练习", "例题", "作业")),
)

VISUAL_SIGNAL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("公式", ("公式", "方程", "推导", "等式", "=", "∑", "∫")),
    ("图示", ("图示", "框图", "流程图", "示意图", "频谱图", "波形图", "如图", "见图", "下图", "上图")),
    ("表格", ("表格", "对照表", "统计表", "真值表", "数据表")),
    ("图片题", ("图片", "插图", "配图", "图题", "读图题", "看图", "如图", "见图", "下图", "上图")),
)

SOURCE_TYPE_ANCHOR_TERMS: dict[str, tuple[str, ...]] = {
    "past_exam": ("真题", "往年", "历年", "试卷", "期末", "期中"),
    "answer_explanation": ("解析", "答案", "标答", "参考答案"),
    "lecture_notes": ("讲义", "课件", "笔记"),
    "study_outline": ("速成", "提纲", "复习"),
    "exercise": ("习题", "练习", "例题", "作业"),
}

PDF_EVIDENCE_SCHEMA = "material-page-evidence-v1"


@dataclass(frozen=True, slots=True)
class MaterialPageChunk:
    page: int
    text: str
    years: tuple[str, ...]
    question_types: tuple[str, ...]
    knowledge_signals: tuple[str, ...]
    chapter_signals: tuple[str, ...]
    solution_signals: tuple[str, ...]
    question_numbers: tuple[str, ...]
    source_type: str
    score_points: tuple[int, ...]
    difficulty_signals: tuple[str, ...]
    visual_signals: tuple[str, ...]


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
    chapter_signals: tuple[str, ...] = ()
    solution_signals: tuple[str, ...] = ()
    question_numbers: tuple[str, ...] = ()
    source_type: str = "unknown"
    score_points: tuple[int, ...] = ()
    difficulty_signals: tuple[str, ...] = ()
    visual_signals: tuple[str, ...] = ()
    anchor_terms: tuple[str, ...] = ()
    anchor_text: str = ""

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": PDF_EVIDENCE_SCHEMA,
            "evidence_id": self.evidence_id(),
            "material_id": self.material_id,
            "title": self.title,
            "page": self.page,
            "text": self.text,
            "provenance": {
                "source": "pdf_page_chunk",
                "persistence": "not_persisted",
                "cacheScope": "bounded_in_memory_for_free_materials",
            },
        }
        if self.years:
            payload["years"] = list(self.years)
        if self.question_types:
            payload["question_types"] = list(self.question_types)
        if self.knowledge_signals:
            payload["knowledge_signals"] = list(self.knowledge_signals)
        if self.chapter_signals:
            payload["chapter_signals"] = list(self.chapter_signals)
        if self.solution_signals:
            payload["solution_signals"] = list(self.solution_signals)
        if self.question_numbers:
            payload["question_numbers"] = list(self.question_numbers)
        if self.source_type != "unknown":
            payload["source_type"] = self.source_type
        if self.score_points:
            payload["score_points"] = list(self.score_points)
        if self.difficulty_signals:
            payload["difficulty_signals"] = list(self.difficulty_signals)
        if self.visual_signals:
            payload["visual_signals"] = list(self.visual_signals)
        if self.anchor_terms:
            payload["anchor_terms"] = list(self.anchor_terms)
        if self.anchor_text:
            payload["anchor_text"] = self.anchor_text
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
        if self.question_numbers:
            payload["question_numbers"] = list(self.question_numbers)
        if self.source_type != "unknown":
            payload["source_type"] = self.source_type
        return payload

    def evidence_id(self) -> str:
        fingerprint_basis = {
            "schema": PDF_EVIDENCE_SCHEMA,
            "material_id": int(self.material_id),
            "title": self.title,
            "page": int(self.page),
            "text": self.text,
            "years": list(self.years),
            "question_types": list(self.question_types),
            "knowledge_signals": list(self.knowledge_signals),
            "chapter_signals": list(self.chapter_signals),
            "solution_signals": list(self.solution_signals),
            "question_numbers": list(self.question_numbers),
            "source_type": self.source_type,
            "score_points": list(self.score_points),
            "difficulty_signals": list(self.difficulty_signals),
            "visual_signals": list(self.visual_signals),
            "anchor_terms": list(self.anchor_terms),
            "anchor_text": self.anchor_text,
        }
        serialized = json.dumps(fingerprint_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


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
        current_user_role_mask: int | None = None,
        force: bool = False,
        max_materials: int | None = None,
        max_results: int | None = None,
        page_numbers: set[int] | None = None,
    ) -> list[MaterialPageEvidence]:
        if not self.settings.ai_agent_pdf_evidence_enabled or (not force and not self.should_load_evidence(query)):
            return []
        material_limit = max(
            0,
            int(
                max_materials
                if max_materials is not None
                else self.settings.ai_agent_pdf_evidence_max_materials or 0
            ),
        )
        if material_limit <= 0:
            return []
        all_evidence: list[MaterialPageEvidence] = []
        scanned = 0
        for material in materials:
            if scanned >= material_limit:
                break
            if not self._can_read_pdf_material(material, current_user_id, current_user_role_mask):
                continue
            scanned += 1
            all_evidence.extend(
                self.collect_for_material(
                    material,
                    query,
                    cacheable=bool(safe_material_value(material, "is_free", True)),
                    max_results=max_results,
                    page_numbers=page_numbers,
                )
            )
        all_evidence.sort(key=lambda item: (-item.score, item.material_id, item.page))
        result_limit = max(
            1,
            int(max_results if max_results is not None else self.settings.ai_agent_pdf_evidence_max_pages),
        )
        return all_evidence[:result_limit]

    def collect_for_material(
        self,
        material: MaterialRecord,
        query: str,
        *,
        cacheable: bool | None = None,
        max_results: int | None = None,
        page_numbers: set[int] | None = None,
    ) -> list[MaterialPageEvidence]:
        key = str(safe_material_value(material, "file_storage_key") or "").strip()
        if not key:
            return []
        should_cache = bool(safe_material_value(material, "is_free", True)) if cacheable is None else cacheable
        chunks = self._load_page_chunks(key, cacheable=should_cache)
        if not chunks:
            return []
        query_terms = _query_terms(query)
        evidence: list[MaterialPageEvidence] = []
        for chunk in chunks:
            if page_numbers and chunk.page not in page_numbers:
                continue
            if not chunk.text.strip():
                continue
            anchor_terms = tuple(_anchor_terms(chunk, query_terms))
            evidence.append(
                MaterialPageEvidence(
                    material_id=int(material.id),
                    title=str(safe_material_value(material, "title") or f"资料 #{material.id}"),
                    page=chunk.page,
                    text=chunk.text,
                    score=_score_page(chunk, query_terms),
                    years=chunk.years,
                    question_types=chunk.question_types,
                    knowledge_signals=chunk.knowledge_signals,
                    chapter_signals=chunk.chapter_signals,
                    solution_signals=chunk.solution_signals,
                    question_numbers=chunk.question_numbers,
                    source_type=chunk.source_type,
                    score_points=chunk.score_points,
                    difficulty_signals=chunk.difficulty_signals,
                    visual_signals=chunk.visual_signals,
                    anchor_terms=anchor_terms,
                    anchor_text=_anchor_text(chunk.text, anchor_terms),
                )
            )
        evidence.sort(key=lambda item: (-item.score, item.page))
        result_limit = max(
            1,
            int(max_results if max_results is not None else self.settings.ai_agent_pdf_evidence_max_pages),
        )
        return evidence[:result_limit]

    def _load_page_chunks(self, key: str, *, cacheable: bool) -> tuple[MaterialPageChunk, ...]:
        max_pages = max(
            1,
            int(
                getattr(
                    self.settings,
                    "ai_agent_pdf_extract_max_pages",
                    self.settings.ai_agent_pdf_evidence_max_pages,
                )
                or self.settings.ai_agent_pdf_evidence_max_pages
                or 1
            ),
        )
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

    def _can_read_pdf_material(
        self,
        material: MaterialRecord,
        current_user_id: int | None,
        current_user_role_mask: int | None = None,
    ) -> bool:
        if not _looks_like_pdf(material):
            return False
        if not str(safe_material_value(material, "file_storage_key") or "").strip():
            return False
        if has_role(current_user_role_mask, ROLE_ADMIN) or has_role(current_user_role_mask, ROLE_DEVELOPER):
            return True
        if bool(safe_material_value(material, "is_free", True)):
            return True
        return current_user_id is not None and _safe_int(safe_material_value(material, "uploader_id")) == current_user_id


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
        if not compact or not _looks_like_readable_page_text(compact):
            continue
        chunks.append(
            MaterialPageChunk(
                page=page_number,
                text=compact,
                years=tuple(_extract_years(compact)),
                question_types=tuple(_extract_question_types(compact)),
                knowledge_signals=tuple(_extract_knowledge_signals(compact)),
                chapter_signals=tuple(_extract_chapter_signals(compact)),
                solution_signals=tuple(_extract_solution_signals(compact)),
                question_numbers=tuple(_extract_question_numbers(compact)),
                source_type=_classify_source_type(compact),
                score_points=tuple(_extract_score_points(compact)),
                difficulty_signals=tuple(_extract_difficulty_signals(compact)),
                visual_signals=tuple(_extract_visual_signals(compact)),
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
    file_type = str(safe_material_value(material, "file_type") or "").strip().lower()
    filename = str(safe_material_value(material, "original_filename") or "").strip().lower()
    key = str(safe_material_value(material, "file_storage_key") or "").strip().lower()
    return file_type == "pdf" or filename.endswith(".pdf") or key.endswith(".pdf")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
    score += len(chunk.chapter_signals)
    score += len(chunk.solution_signals) * 2
    score += len(chunk.question_numbers) * 2
    score += len(chunk.score_points) * 2
    score += len(chunk.difficulty_signals)
    score += len(chunk.visual_signals)
    if chunk.source_type in {"past_exam", "answer_explanation"}:
        score += 3
    return score


def _compact_text(text: str, *, max_chars: int = 700) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:max_chars]


def _looks_like_readable_page_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 12:
        return False
    meaningful = sum(1 for char in compact if _is_cjk(char) or char.isascii() and char.isalnum())
    other_letters = sum(1 for char in compact if char.isalpha() and not (_is_cjk(char) or char.isascii()))
    punctuation = sum(1 for char in compact if not char.isalnum() and not _is_cjk(char))
    if meaningful < 8:
        return False
    if other_letters > max(4, int(meaningful * 0.15)):
        return False
    return meaningful / max(1, len(compact) - min(punctuation, len(compact) // 3)) >= 0.34


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


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


def _extract_chapter_signals(text: str) -> list[str]:
    result: list[str] = []
    patterns = (
        r"第\s*[0-9一二三四五六七八九十]{1,4}\s*[章节]\s*[\u4e00-\u9fffA-Za-z0-9（）()、:：·\-]{0,24}",
        r"(?:模块|专题|单元)\s*[0-9一二三四五六七八九十]{1,4}\s*[\u4e00-\u9fffA-Za-z0-9（）()、:：·\-]{0,24}",
        r"\b(?:chapter|section|unit)\s*[0-9]{1,3}[A-Za-z0-9 .:_-]{0,24}",
    )
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            cleaned = _compact_text(str(match), max_chars=36).strip(" :：、-")
            if cleaned and cleaned not in result:
                result.append(cleaned)
            if len(result) >= 6:
                return result
    return result


def _extract_solution_signals(text: str) -> list[str]:
    normalized = text.lower()
    result: list[str] = []
    patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("参考答案", ("参考答案", "标准答案", "答案", "标答")),
        ("解题步骤", ("解题步骤", "解答步骤", "解题过程", "步骤", "过程")),
        ("解析说明", ("解析", "讲解", "说明", "详解")),
        ("评分标准", ("评分标准", "给分点", "得分点", "采分点")),
        ("易错点", ("易错", "常见错误", "注意", "陷阱")),
        ("最终结果", ("最终结果", "结果为", "答案为", "所以")),
    )
    for label, aliases in patterns:
        if any(alias.lower() in normalized for alias in aliases) and label not in result:
            result.append(label)
    return result[:6]


def _extract_question_numbers(text: str) -> list[str]:
    patterns = (
        r"第\s*([0-9一二三四五六七八九十]{1,3})\s*[题問问]",
        r"(?<!\d)([0-9]{1,2})\s*[\.、)]\s*(?:[^\s，。；：:]{0,12})",
        r"[Qq]uestion\s*([0-9]{1,2})",
        r"\b[Qq]\s*([0-9]{1,2})\b",
    )
    result: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text):
            value = str(match).strip()
            label = f"第{value}题"
            if label not in result:
                result.append(label)
            if len(result) >= 8:
                return result
    return result


def _extract_score_points(text: str) -> list[int]:
    result: list[int] = []
    for match in re.findall(r"(?<!\d)(\d{1,2})\s*分(?!钟)", text):
        value = int(match)
        if 0 < value <= 100 and value not in result:
            result.append(value)
        if len(result) >= 8:
            break
    return result


def _extract_difficulty_signals(text: str) -> list[str]:
    normalized = text.lower()
    result: list[str] = []
    patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("基础", ("基础", "简单", "容易", "入门")),
        ("中等", ("中等", "常规", "典型")),
        ("综合", ("综合", "综合题", "跨章节")),
        ("偏难", ("较难", "偏难", "难度较大", "压轴", "提高题")),
    )
    for label, aliases in patterns:
        if any(alias.lower() in normalized for alias in aliases) and label not in result:
            result.append(label)
    return result[:4]


def _extract_visual_signals(text: str) -> list[str]:
    normalized = text.lower()
    result: list[str] = []
    for label, aliases in VISUAL_SIGNAL_PATTERNS:
        if any(alias.lower() in normalized for alias in aliases) and label not in result:
            result.append(label)
    return result[:4]


def _anchor_terms(chunk: MaterialPageChunk, query_terms: list[str]) -> list[str]:
    normalized = chunk.text.lower()
    result: list[str] = []

    def add(value: str) -> None:
        cleaned = str(value).strip()
        if not cleaned or cleaned in result:
            return
        if cleaned.lower() in normalized:
            result.append(cleaned)

    for term in query_terms:
        add(term)
    for values in (
        chunk.question_numbers,
        chunk.question_types,
        chunk.years,
        chunk.knowledge_signals,
        chunk.chapter_signals,
        chunk.solution_signals,
        tuple(f"{value}分" for value in chunk.score_points),
        chunk.difficulty_signals,
        chunk.visual_signals,
        SOURCE_TYPE_ANCHOR_TERMS.get(chunk.source_type, ()),
    ):
        for value in values:
            add(str(value))
            if len(result) >= 8:
                return result
    return result


def _anchor_text(text: str, anchor_terms: tuple[str, ...], *, max_chars: int = 240) -> str:
    if not anchor_terms:
        return ""
    compact = _compact_text(text, max_chars=max(700, max_chars))
    if not compact:
        return ""
    normalized = compact.lower()
    match_index: int | None = None
    match_end = 0
    for term in anchor_terms:
        index = normalized.find(term.lower())
        if index < 0:
            continue
        if match_index is None or index < match_index:
            match_index = index
            match_end = index + len(term)
    if match_index is None:
        return compact[:max_chars]
    start = max(0, match_index - 60)
    end = min(len(compact), max(match_end + 160, start + max_chars))
    end = min(len(compact), end)
    snippet = compact[start:end].strip()
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(compact):
        snippet = f"{snippet}..."
    return snippet


def _classify_source_type(text: str) -> str:
    normalized = text.lower()
    best_label = "unknown"
    best_hits = 0
    for label, aliases in SOURCE_TYPE_PATTERNS:
        hits = sum(1 for alias in aliases if alias.lower() in normalized)
        if hits > best_hits:
            best_label = label
            best_hits = hits
    return best_label
