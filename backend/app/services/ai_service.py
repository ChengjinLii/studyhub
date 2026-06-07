from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import get_runtime_metrics
from app.models.materials import MaterialRecord
from app.repos.material_repo import MaterialRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.ai import AiChatRequestPayload, AiRecommendRequestPayload
from app.services.agent_course_memory_service import AgentCourseMemoryService, CourseMemoryCard
from app.services.agent_memory_service import AgentMemoryContext, AgentMemoryService
from app.services.agent_query_planner_service import AgentQueryPlan, AgentQueryPlannerService
from app.services.agent_safety_service import AgentSafetyService
from app.services.material_pdf_evidence_service import MaterialPageEvidence, MaterialPdfEvidenceService
from app.services.read_support import parse_iso_datetime


QUERY_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "通信原理": ("通信原理", "cps"),
    "cps": ("通信原理", "cps"),
    "信号与系统": ("信号与系统", "signals", "signal"),
    "数据结构": ("数据结构",),
    "链表": ("链表", "linked list", "linked-list"),
    "高数下": ("高数下", "高等数学下", "微积分ii", "微积分2", "微积分Ⅱ"),
    "高数": ("高数", "高等数学", "微积分"),
    "高等数学": ("高等数学", "高数", "微积分"),
    "微积分": ("微积分", "高等数学", "高数"),
    "概率论": ("概率论",),
    "真题": ("真题", "往年卷", "历年", "期末考题"),
    "历年": ("历年", "往年", "真题"),
    "期末": ("期末", "期末考", "期末考试"),
    "期中": ("期中", "期中考"),
    "解析": ("解析", "答案", "标答"),
    "笔记": ("笔记", "讲义", "导图"),
    "速成": ("速成", "复习", "提纲"),
}

COURSE_QUERY_TERMS = {
    "通信原理",
    "cps",
    "信号与系统",
    "数据结构",
    "链表",
    "高数下",
    "高数",
    "高等数学",
    "微积分",
    "概率论",
}

LOW_VALUE_QUERY_TERMS = {
    "一般",
    "两周",
    "多久",
    "考试",
    "复习",
    "资料",
    "相关",
    "怎么",
    "如何",
    "帮我",
    "找到",
    "当前",
    "基础",
    "更有效",
}

CHAT_COMPLETIONS_AGENT_PROVIDERS = {"custom", "openai-compatible", "openai_compatible"}
SUB2API_AGENT_PROVIDERS = {"sub2api", "codex-sub2api", "codex_sub2api"}


class AiService:
    """StudyHub AI compatibility layer with optional external agent providers."""

    def __init__(
        self,
        read_repo: ReadApiRepository,
        material_repo: MaterialRepository,
        pdf_evidence_service: MaterialPdfEvidenceService | None = None,
        memory_service: AgentMemoryService | None = None,
        query_planner_service: AgentQueryPlannerService | None = None,
        course_memory_service: AgentCourseMemoryService | None = None,
        safety_service: AgentSafetyService | None = None,
    ) -> None:
        self.read_repo = read_repo
        self.material_repo = material_repo
        self.pdf_evidence_service = pdf_evidence_service
        self.memory_service = memory_service
        self.query_planner_service = query_planner_service
        self.course_memory_service = course_memory_service
        self.safety_service = safety_service or AgentSafetyService()

    def chat(self, payload: AiChatRequestPayload) -> dict[str, Any]:
        latest_user_message = next((item.content.strip() for item in reversed(payload.messages) if item.role.lower() == "user"), "")
        if not latest_user_message:
            latest_user_message = payload.messages[-1].content.strip()
        content = (
            "当前为 StudyHub FastAPI 本地兼容回复。\n"
            f"你的问题是：{latest_user_message}\n"
            "Step 10 先保证接口契约、鉴权和错误语义稳定；真正的外部模型接入放到后续环境配置阶段。"
        )
        return {"content": content}

    def recommend(
        self,
        session: Session,
        payload: AiRecommendRequestPayload,
        *,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        settings = get_settings()
        provider = settings.ai_agent_provider.strip().lower() or "local"
        model_configured = self._is_agent_model_configured(settings)
        status = "local_fallback"
        pdf_evidence: list[MaterialPageEvidence] = []
        memory_context: AgentMemoryContext | None = None
        course_memory_card: CourseMemoryCard | None = None
        try:
            materials = self._rank_materials(session, payload.query, payload.filters or {})
            pdf_evidence = self._collect_pdf_evidence(materials, payload.query, current_user_id=current_user_id)
            memory_context = self._collect_memory_context(
                session,
                query=payload.query,
                materials=materials,
                current_user_id=current_user_id,
                pdf_evidence=pdf_evidence,
            )
            query_plan = self._build_query_plan(
                payload.query,
                materials=materials,
                pdf_evidence=pdf_evidence,
                memory_context=memory_context,
            )
            course_memory_card = self._build_course_memory_card(
                materials=materials,
                pdf_evidence=pdf_evidence,
                memory_context=memory_context,
                query_plan=query_plan,
            )
            recommendations = [self._recommendation_payload(material, payload.query) for material in materials[:3]]
            llm_body = self._generate_agent_recommendation(
                payload.query,
                materials,
                pdf_evidence=pdf_evidence,
                memory_context=memory_context,
                query_plan=query_plan,
                course_memory_card=course_memory_card,
            )
            if llm_body:
                status = "model_success"
                recommendations = self._merge_llm_recommendations(llm_body, recommendations)
            elif model_configured:
                status = "model_fallback"
            body = {
                "recommendations": recommendations,
                "answer": llm_body.get("answer")
                if llm_body
                else self._build_local_answer(payload.query, recommendations, pdf_evidence, memory_context),
                "followup_questions": [
                    "你更想要真题、笔记还是经验分享？",
                    "是否需要限定学校、学院或专业？",
                ],
            }
            if pdf_evidence:
                body["evidence_sources"] = [item.to_source_payload() for item in pdf_evidence]
            if llm_body and isinstance(llm_body.get("followup_questions"), list):
                body["followup_questions"] = [
                    str(item).strip()
                    for item in llm_body["followup_questions"]
                    if isinstance(item, (str, int, float)) and str(item).strip()
                ][:3] or body["followup_questions"]
            return {"output": f"<json>{json.dumps(body, ensure_ascii=False, separators=(',', ':'))}</json>"}
        except Exception:
            status = "error"
            raise
        finally:
            get_runtime_metrics().record_ai_agent_run(
                provider=provider,
                status=status,
                pdf_evidence=bool(pdf_evidence),
                memory_context=memory_context is not None,
                course_memory_card=course_memory_card is not None,
                duration_seconds=perf_counter() - started_at,
            )

    def _recommendation_payload(self, material: MaterialRecord, query: str) -> dict[str, Any]:
        return {
            "material_id": material.id,
            "title": self._safe_text(material, "title"),
            "tags": self._loads(self._safe_text(material, "tags_json")),
            "reason": self._build_reason(material, query),
            "summary": self._safe_text(material, "description"),
        }

    def _collect_pdf_evidence(
        self,
        materials: list[MaterialRecord],
        query: str,
        *,
        current_user_id: int | None,
    ) -> list[MaterialPageEvidence]:
        if not self.pdf_evidence_service:
            return []
        try:
            return self.pdf_evidence_service.collect_for_materials(
                materials,
                query,
                current_user_id=current_user_id,
            )
        except Exception:
            return []

    def _collect_memory_context(
        self,
        session: Session,
        *,
        query: str,
        materials: list[MaterialRecord],
        current_user_id: int | None,
        pdf_evidence: list[MaterialPageEvidence],
    ) -> AgentMemoryContext | None:
        if not self.memory_service:
            return None
        try:
            context = self.memory_service.collect(
                session,
                query=query,
                materials=materials,
                current_user_id=current_user_id,
                pdf_evidence=pdf_evidence,
            )
        except Exception:
            return None
        return None if context.is_empty() else context

    def _build_query_plan(
        self,
        query: str,
        *,
        materials: list[MaterialRecord],
        pdf_evidence: list[MaterialPageEvidence],
        memory_context: AgentMemoryContext | None,
    ) -> AgentQueryPlan | None:
        if not self.query_planner_service:
            return None
        try:
            return self.query_planner_service.build_plan(
                query,
                materials=materials,
                pdf_evidence=pdf_evidence,
                memory_context=memory_context,
            )
        except Exception:
            return None

    def _build_course_memory_card(
        self,
        *,
        materials: list[MaterialRecord],
        pdf_evidence: list[MaterialPageEvidence],
        memory_context: AgentMemoryContext | None,
        query_plan: AgentQueryPlan | None,
    ) -> CourseMemoryCard | None:
        if not self.course_memory_service:
            return None
        try:
            return self.course_memory_service.build_card(
                materials=materials,
                pdf_evidence=pdf_evidence,
                memory_context=memory_context,
                query_plan=query_plan,
            )
        except Exception:
            return None

    def _generate_agent_recommendation(
        self,
        query: str,
        materials: list[MaterialRecord],
        *,
        pdf_evidence: list[MaterialPageEvidence],
        memory_context: AgentMemoryContext | None,
        query_plan: AgentQueryPlan | None,
        course_memory_card: CourseMemoryCard | None,
    ) -> dict[str, Any] | None:
        settings = get_settings()
        if not self._is_agent_model_configured(settings):
            return None

        context_materials = materials[: min(3, max(1, settings.ai_agent_max_context_materials))]
        candidates = [
            self._compact_recommendation_payload(material, query)
            for material in context_materials
        ]
        system_prompt = (
            "你是 StudyHub 学习辅导 Agent。你只能基于给定的 StudyHub 候选资料回答，"
            "不要编造不存在的资料。用户可能需要资料推荐、真题讲解思路、复习规划或错题辅导。"
            "如果候选资料不足，要明确说明并追问课程范围。"
            "如果提供了 pdf_evidence，你必须优先基于这些页级证据总结，并在关键结论中引用资料名和页码。"
            "如果提供了 memory_context，你可以用平台集体记忆增强课程/题型判断，用用户个人记忆做个性化建议；"
            "但不能把用户个人记忆写入或表述成平台集体结论。"
            "如果提供了 query_plan，你必须按照该意图和 evidence_tasks 组织回答；"
            "如果提供了 course_memory_card，你可以用它总结课程级年份、题型、知识点和推荐顺序；"
            "不要输出 memory_context、query_plan、candidate_materials、pdf_evidence 或 privacy_boundary 等内部字段名。"
            "必须输出严格 JSON，不要输出 Markdown，不要包裹代码块。"
        )
        user_prompt = {
            "user_query": query,
            "query_plan": query_plan.to_prompt_payload() if query_plan else {},
            "candidate_materials": candidates,
            "pdf_evidence": [item.to_prompt_payload() for item in pdf_evidence],
            "memory_context": memory_context.to_prompt_payload() if memory_context else {},
            "course_memory_card": course_memory_card.to_prompt_payload() if course_memory_card else {},
            "output_schema": {
                "answer": "面向学生的自然语言回答，先遵循 query_plan 的意图与任务，再结合资料、PDF 证据、课程记忆卡片和可用记忆上下文说明下一步怎么学。",
                "recommendations": [
                    {
                        "material_id": "候选资料中的 material_id",
                        "reason": "为什么推荐这份资料，必须贴合用户问题",
                    }
                ],
                "evidence_sources": [{"material_id": "候选资料中的 material_id", "page": "页码", "title": "资料名"}],
                "followup_questions": ["最多 3 个追问或下一步学习动作"],
            },
        }
        try:
            content = self._call_agent_model(settings, system_prompt, user_prompt)
        except Exception:
            return None

        parsed = self._loads_object(content)
        if not parsed:
            return None
        return self.safety_service.sanitize_recommendation_body(
            parsed,
            candidate_materials=context_materials,
            pdf_evidence=pdf_evidence,
        )

    def _is_agent_model_configured(self, settings: Any) -> bool:
        provider = settings.ai_agent_provider.strip().lower()
        if provider not in CHAT_COMPLETIONS_AGENT_PROVIDERS | SUB2API_AGENT_PROVIDERS:
            return False
        return bool(settings.ai_agent_base_url and settings.ai_agent_api_key and settings.ai_agent_model)

    def _call_agent_model(self, settings: Any, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        provider = settings.ai_agent_provider.strip().lower()
        if provider in SUB2API_AGENT_PROVIDERS:
            return self._call_sub2api_responses_api(settings, system_prompt, user_prompt)
        return self._call_chat_completions_api(settings, system_prompt, user_prompt)

    def _call_chat_completions_api(self, settings: Any, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        with httpx.Client(timeout=max(10.0, settings.ai_agent_timeout_seconds), trust_env=False) as client:
            response = client.post(
                f"{settings.ai_agent_base_url.rstrip('/')}/chat/completions",
                headers=self._agent_headers(settings.ai_agent_api_key),
                json={
                    "model": settings.ai_agent_model,
                    "temperature": 0.2,
                    "max_tokens": 900,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "thinking": {"type": "disabled"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
            return self._extract_chat_content(response.json())

    def _call_sub2api_responses_api(self, settings: Any, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        with httpx.Client(timeout=max(10.0, settings.ai_agent_timeout_seconds), trust_env=False) as client:
            response = client.post(
                f"{settings.ai_agent_base_url.rstrip('/')}/responses",
                headers=self._agent_headers(settings.ai_agent_api_key),
                json={
                    "model": settings.ai_agent_model,
                    "instructions": system_prompt,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": json.dumps(user_prompt, ensure_ascii=False),
                                }
                            ],
                        }
                    ],
                    "max_output_tokens": 900,
                    "reasoning": {"effort": "none"},
                    "store": False,
                },
            )
            response.raise_for_status()
            return self._extract_sub2api_content(response.text)

    def _agent_headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _compact_recommendation_payload(self, material: MaterialRecord, query: str) -> dict[str, Any]:
        description = self._safe_text(material, "description").replace("\n", " ").strip()
        return {
            "material_id": material.id,
            "title": self._safe_text(material, "title"),
            "reason": self._build_reason(material, query),
            "summary": description[:180],
        }

    def _merge_llm_recommendations(self, body: dict[str, Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {int(item["material_id"]): dict(item) for item in fallback if item.get("material_id") is not None}
        merged: list[dict[str, Any]] = []
        raw_items = body.get("recommendations")
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                material_id = self._safe_int(raw_item.get("material_id") or raw_item.get("materialId") or raw_item.get("id"))
                if material_id is None or material_id not in by_id:
                    continue
                item = dict(by_id[material_id])
                if isinstance(raw_item.get("reason"), str) and raw_item["reason"].strip():
                    item["reason"] = raw_item["reason"].strip()
                merged.append(item)
        for item in fallback:
            if len(merged) >= 3:
                break
            if not any(existing.get("material_id") == item.get("material_id") for existing in merged):
                merged.append(item)
        return merged[:3]

    def _build_local_answer(
        self,
        query: str,
        recommendations: list[dict[str, Any]],
        pdf_evidence: list[MaterialPageEvidence] | None = None,
        memory_context: AgentMemoryContext | None = None,
    ) -> str:
        if not recommendations:
            return f"我没有在平台资料库里找到足够贴近「{query}」的候选。你可以补充课程名、考试范围、题型或学校专业，我再帮你缩小检索。"
        titles = "、".join(f"《{item.get('title') or '资料'}》" for item in recommendations)
        profile_hint = self._local_profile_hint(memory_context)
        if pdf_evidence:
            sources = "；".join(f"《{item.title}》第 {item.page} 页" for item in pdf_evidence[:3])
            return f"我先基于 StudyHub 资料库找到 {titles}，并读取到相关 PDF 页级证据：{sources}。{profile_hint}建议先用这些页面确认题型和高频知识点，再结合真题或经验内容做查漏补缺。"
        return f"我先基于 StudyHub 资料库找到 {titles}。{profile_hint}建议先用最匹配的资料建立知识框架，再结合真题或经验内容做查漏补缺。"

    def _local_profile_hint(self, memory_context: AgentMemoryContext | None) -> str:
        if not memory_context or not memory_context.user:
            return ""
        profile = memory_context.user.get("profile")
        if not isinstance(profile, dict):
            return ""
        parts = [
            str(profile.get(key)).strip()
            for key in ("school", "college", "major", "grade_stages")
            if profile.get(key)
        ]
        if not parts:
            return ""
        return f"我会优先按你的{'/'.join(parts[:3])}背景来判断匹配度。"

    def _extract_chat_content(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        return first.get("text") if isinstance(first.get("text"), str) else ""

    def _extract_sub2api_content(self, payload: str) -> str:
        text = payload.strip()
        if not text:
            return ""
        parsed = self._loads_object(text)
        if parsed:
            content = self._extract_response_output_text(parsed)
            if content:
                return content
        chunks: list[str] = []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            raw_data = line.removeprefix("data:").strip()
            if not raw_data or raw_data == "[DONE]":
                continue
            try:
                event = json.loads(raw_data)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "response.output_text.done" and isinstance(event.get("text"), str):
                return event["text"]
            if event.get("type") == "response.output_text.delta" and isinstance(event.get("delta"), str):
                chunks.append(event["delta"])
            if event.get("type") == "response.completed" and isinstance(event.get("response"), dict):
                content = self._extract_response_output_text(event["response"])
                if content:
                    return content
        return "".join(chunks)

    def _extract_response_output_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return output_text
        output = payload.get("output")
        if not isinstance(output, list):
            return ""
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        return "".join(parts)

    def _loads_object(self, value: str) -> dict[str, Any] | None:
        body = value.strip()
        if body.startswith("```"):
            body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body, flags=re.IGNORECASE | re.DOTALL).strip()
        start = body.find("{")
        end = body.rfind("}")
        if start >= 0 and end > start:
            body = body[start : end + 1]
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _safe_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _rank_materials(self, session: Session, query: str, filters: dict[str, Any]) -> list[MaterialRecord]:
        seed = self.read_repo.load_seed()
        self.material_repo.ensure_seed_bootstrap(session, seed)
        normalized_query = query.strip().lower()
        school = str(filters.get("school")).strip() if filters.get("school") else None
        major = str(filters.get("major")).strip() if filters.get("major") else None
        query_terms = self._query_terms(normalized_query)
        scored_items = []
        for item in self.material_repo.list_visible_materials(session):
            score = self._score(item, query_terms, normalized_query, school=school, major=major)
            course_score = self._course_score(item, query_terms)
            scored_items.append((score, course_score, item))
        course_items = [(score, item) for score, course_score, item in scored_items if course_score > 0]
        if course_items:
            items = course_items
        else:
            items = [(score, item) for score, _, item in scored_items]
        positive_items = [(score, item) for score, item in items if score > 0]
        items = positive_items or items
        items.sort(
            key=lambda scored_item: (
                -scored_item[0],
                -int(scored_item[1].download_count or 0),
                -parse_iso_datetime(scored_item[1].created_at.isoformat() if scored_item[1].created_at else None).timestamp(),
            )
        )
        if positive_items:
            return [item for _, item in items]
        return []

    def _score(self, material: MaterialRecord, query_terms: list[str], query: str, *, school: str | None, major: str | None) -> int:
        title = self._safe_text(material, "title").lower()
        haystack = self._material_haystack(material, title)
        score = 0
        for term in query_terms:
            aliases = QUERY_TERM_ALIASES.get(term, (term,))
            if any(alias.lower() in title for alias in aliases):
                score += 24
            elif any(alias.lower() in haystack for alias in aliases):
                score += 10
        if query and query in haystack:
            score += 16
        if school and self._safe_text(material, "school") == school:
            score += 3
        if major and major in self._safe_text(material, "major"):
            score += 4
        return score

    def _course_score(self, material: MaterialRecord, query_terms: list[str]) -> int:
        title = self._safe_text(material, "title").lower()
        haystack = self._material_haystack(material, title)
        score = 0
        for term in query_terms:
            if term not in COURSE_QUERY_TERMS:
                continue
            aliases = QUERY_TERM_ALIASES.get(term, (term,))
            if any(alias.lower() in title for alias in aliases):
                score += 2
            elif any(alias.lower() in haystack for alias in aliases):
                score += 1
        return score

    def _material_haystack(self, material: MaterialRecord, title: str | None = None) -> str:
        return " ".join(
            [
                title if title is not None else self._safe_text(material, "title").lower(),
                self._safe_text(material, "description").lower(),
                self._safe_text(material, "original_filename").lower(),
                self._safe_text(material, "keywords").lower(),
                " ".join(self._loads(self._safe_text(material, "tags_json"))).lower(),
                self._safe_text(material, "school").lower(),
                self._safe_text(material, "college").lower(),
                self._safe_text(material, "major").lower(),
            ]
        )

    def _query_terms(self, query: str) -> list[str]:
        terms: list[str] = []
        normalized = query.strip().lower()
        for term in QUERY_TERM_ALIASES:
            if term in normalized:
                terms.append(term)
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", normalized):
            if token in LOW_VALUE_QUERY_TERMS:
                continue
            if len(token) >= 2:
                terms.append(token)
        deduped: list[str] = []
        for term in terms:
            if term not in deduped:
                deduped.append(term)
        return deduped

    def _build_reason(self, material: MaterialRecord, query: str) -> str:
        parts = []
        school = self._safe_text(material, "school")
        major = self._safe_text(material, "major")
        title = self._safe_text(material, "title")
        description = self._safe_text(material, "description")
        if school:
            parts.append(f"同校资料：{school}")
        if major:
            parts.append(f"专业匹配：{major}")
        if query and query.lower() in (title + " " + description).lower():
            parts.append("标题或简介直接命中你的关键词")
        if not parts:
            parts.append("下载量和内容完整度在当前候选中更靠前")
        return "；".join(parts)

    def _safe_text(self, material: MaterialRecord, field: str) -> str:
        value = material.__dict__.get(field)
        if value is None:
            return ""
        return str(value)

    def _loads(self, value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed if isinstance(item, (str, int, float))]
