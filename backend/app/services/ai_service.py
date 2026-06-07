from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import get_runtime_metrics
from app.core.security import build_cookie_header
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
        personal_memory_enabled: bool = True,
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
            memory_context = (
                self._collect_memory_context(
                    session,
                    query=payload.query,
                    materials=materials,
                    current_user_id=current_user_id,
                    pdf_evidence=pdf_evidence,
                )
                if personal_memory_enabled
                else None
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
            recommendations = [self._recommendation_payload(material, payload.query, pdf_evidence) for material in materials[:3]]
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
            followup_questions = self._local_followup_questions(
                query_plan=query_plan,
                pdf_evidence=pdf_evidence,
                recommendations=recommendations,
                memory_context=memory_context,
            )
            body = {
                "recommendations": recommendations,
                "answer": llm_body.get("answer")
                if llm_body
                else self._build_local_answer(
                    payload.query,
                    recommendations,
                    pdf_evidence,
                    memory_context,
                    query_plan=query_plan,
                    course_memory_card=course_memory_card,
                ),
                "followup_questions": followup_questions,
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

    def resolve_personal_memory_enabled(self, raw_cookie: str | None) -> bool:
        if raw_cookie is None:
            return True
        return raw_cookie.strip().lower() not in {"0", "false", "disabled", "off", "no"}

    def memory_cookie_name(self) -> str:
        return get_settings().ai_agent_memory_cookie_name

    def write_personal_memory_preference_cookie(self, response: Any, *, enabled: bool) -> None:
        settings = get_settings()
        response.headers.append(
            "set-cookie",
            build_cookie_header(
                settings.ai_agent_memory_cookie_name,
                "enabled" if enabled else "disabled",
                max_age=settings.remember_cookie_ttl_seconds,
                path=settings.cookie_path,
                same_site=settings.cookie_same_site,
                secure=settings.resolved_cookie_secure,
            ),
        )

    def memory_preference_payload(self, *, enabled: bool) -> dict[str, Any]:
        return {
            "personalMemoryEnabled": enabled,
            "mode": "read_only_derived",
            "scope": "current_browser",
            "privacyBoundary": "This preference only controls whether the StudyHub Agent uses derived personal memory for this browser session.",
        }

    def preview_memory(
        self,
        session: Session,
        *,
        current_user_id: int,
        personal_memory_enabled: bool,
    ) -> dict[str, Any]:
        settings = get_settings()
        controls = {
            "canView": True,
            "canDisableCurrentBrowser": True,
            "canDeletePersistedMemory": False,
            "deleteExplanation": "当前 StudyHub Agent 个人记忆为只读派生上下文，尚未持久化保存用户对话记忆；因此本阶段没有可删除的 Agent 专属持久化记忆。",
        }
        base_payload: dict[str, Any] = {
            "mode": "read_only_derived",
            "sourceTypes": ["account_profile", "candidate_material_interactions", "visible_material_metadata"],
            "controls": controls,
            "privacyBoundary": "Only the current authenticated user's derived profile and material interaction signals are shown; private memory is not mixed into platform collective memory.",
        }
        if not settings.ai_agent_memory_context_enabled or not self.memory_service:
            return {
                **base_payload,
                "personalMemoryEnabled": False,
                "disabledReason": "global_disabled",
                "personalMemory": None,
                "platformMemoryPreview": {},
            }
        if not personal_memory_enabled:
            return {
                **base_payload,
                "personalMemoryEnabled": False,
                "disabledReason": "user_preference",
                "personalMemory": None,
                "platformMemoryPreview": {},
            }

        max_materials = max(1, int(settings.ai_agent_memory_max_materials or 1))
        materials = self.material_repo.list_visible_materials_for_agent_memory(session, limit=max_materials)
        memory_context = self._collect_memory_context(
            session,
            query="个人学习偏好和资料推荐",
            materials=materials,
            current_user_id=current_user_id,
            pdf_evidence=[],
        )
        return {
            **base_payload,
            "personalMemoryEnabled": True,
            "personalMemory": memory_context.user if memory_context else {},
            "platformMemoryPreview": memory_context.platform if memory_context else {},
            "candidateMaterialCount": len(materials),
        }

    def _recommendation_payload(
        self,
        material: MaterialRecord,
        query: str,
        pdf_evidence: list[MaterialPageEvidence] | None = None,
    ) -> dict[str, Any]:
        return {
            "material_id": material.id,
            "title": self._safe_text(material, "title"),
            "tags": self._loads(self._safe_text(material, "tags_json")),
            "reason": self._build_reason(material, query, pdf_evidence),
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
            self._compact_recommendation_payload(material, query, pdf_evidence)
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

    def _compact_recommendation_payload(
        self,
        material: MaterialRecord,
        query: str,
        pdf_evidence: list[MaterialPageEvidence] | None = None,
    ) -> dict[str, Any]:
        description = self._safe_text(material, "description").replace("\n", " ").strip()
        return {
            "material_id": material.id,
            "title": self._safe_text(material, "title"),
            "reason": self._build_reason(material, query, pdf_evidence),
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
        query_plan: AgentQueryPlan | None = None,
        course_memory_card: CourseMemoryCard | None = None,
    ) -> str:
        if not recommendations:
            return f"我没有在平台资料库里找到足够贴近「{query}」的候选。你可以补充课程名、考试范围、题型或学校专业，我再帮你缩小检索。"
        titles = "、".join(f"《{item.get('title') or '资料'}》" for item in recommendations)
        profile_hint = self._local_profile_hint(memory_context)
        if pdf_evidence:
            sources = "；".join(f"《{item.title}》第 {item.page} 页" for item in pdf_evidence[:3])
            evidence_summary = self._local_evidence_summary(pdf_evidence, course_memory_card)
            sequence_hint = self._local_sequence_hint(query_plan, course_memory_card)
            return (
                f"我先基于 StudyHub 资料库找到 {titles}，并读取到相关 PDF 页级证据：{sources}。"
                f"{evidence_summary}{profile_hint}{sequence_hint}"
            )
        return f"我先基于 StudyHub 资料库找到 {titles}。{profile_hint}建议先用最匹配的资料建立知识框架，再结合真题或经验内容做查漏补缺。"

    def _local_evidence_summary(
        self,
        pdf_evidence: list[MaterialPageEvidence],
        course_memory_card: CourseMemoryCard | None,
    ) -> str:
        years = _evidence_values(pdf_evidence, "years")
        question_types = _course_card_values(course_memory_card, "question_type_distribution") or _evidence_values(pdf_evidence, "question_types")
        knowledge_signals = _course_card_values(course_memory_card, "knowledge_signals") or _evidence_values(pdf_evidence, "knowledge_signals")
        parts: list[str] = []
        if years:
            parts.append(f"年份信号包括 {_join_values(years)}")
        if question_types:
            parts.append(f"题型集中在 {_join_values(question_types)}")
        if knowledge_signals:
            parts.append(f"高频知识点包括 {_join_values(knowledge_signals)}")
        if not parts:
            return "这些页面可以先用来确认题型和高频知识点。"
        return f"从这些页面看，{'；'.join(parts)}。"

    def _local_sequence_hint(
        self,
        query_plan: AgentQueryPlan | None,
        course_memory_card: CourseMemoryCard | None,
    ) -> str:
        if course_memory_card and course_memory_card.recommended_sequence:
            return f"建议按这个顺序处理：{_join_values(list(course_memory_card.recommended_sequence)[:3])}。"
        if query_plan and query_plan.intent == "exam_trend_analysis":
            return "建议先按题型归类，再对照年份趋势刷题查漏补缺。"
        if query_plan and query_plan.intent == "study_plan":
            return "建议先建立知识框架，再刷真题或例题，最后复盘薄弱点。"
        return "建议先用这些页面确认题型和高频知识点，再结合真题或经验内容做查漏补缺。"

    def _local_followup_questions(
        self,
        *,
        query_plan: AgentQueryPlan | None,
        pdf_evidence: list[MaterialPageEvidence],
        recommendations: list[dict[str, Any]],
        memory_context: AgentMemoryContext | None,
    ) -> list[str]:
        if query_plan is None:
            return _default_followups()
        has_pdf = bool(pdf_evidence)
        has_questions = any(item.question_numbers for item in pdf_evidence)
        intent = query_plan.intent
        questions: list[str]
        if intent == "exam_trend_analysis":
            questions = [
                "要不要我按年份整理常考题型？",
                "是否需要把这些资料整理成两周复习顺序？",
            ]
            if has_questions:
                questions.append("要不要我按题号列出优先复盘清单？")
        elif intent == "study_plan":
            questions = [
                "你的考试日期和每天可复习时间是多少？",
                "要不要我按基础薄弱和冲刺刷题分阶段安排？",
            ]
            if recommendations:
                questions.append("是否需要我把推荐资料排成每日学习顺序？")
        elif intent == "pdf_summary":
            questions = [
                "要不要我继续按章节或页码拆解这份资料？",
                "是否需要标出最适合先看的重点页面？",
            ]
        elif intent == "problem_tutoring":
            questions = [
                "你卡住的是概念理解、公式推导还是计算步骤？",
                "要不要我按同类题型再找几页练习？",
            ]
        else:
            questions = _default_followups()
        if has_pdf and intent not in {"exam_trend_analysis", "pdf_summary", "problem_tutoring"}:
            questions.append("要不要我基于已读取页码继续归纳重点？")
        if memory_context and memory_context.user:
            questions.append("是否需要结合你的专业和年级调整推荐顺序？")
        return _dedupe_questions(questions)[:3] or _default_followups()

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

    def _build_reason(
        self,
        material: MaterialRecord,
        query: str,
        pdf_evidence: list[MaterialPageEvidence] | None = None,
    ) -> str:
        parts = []
        evidence_items = _evidence_for_material(pdf_evidence or [], material)
        if evidence_items:
            pages = _evidence_pages(evidence_items)
            if pages:
                parts.append(f"已读取 PDF 第 {_join_values(pages)} 页证据")
            years = _material_evidence_values(evidence_items, "years")
            question_types = _material_evidence_values(evidence_items, "question_types")
            question_numbers = _material_evidence_values(evidence_items, "question_numbers")
            knowledge_signals = _material_evidence_values(evidence_items, "knowledge_signals")
            if years:
                parts.append(f"年份信号：{_join_values(years[:3])}")
            if question_types:
                parts.append(f"题型信号：{_join_values(question_types[:3])}")
            if question_numbers:
                parts.append(f"题号信号：{_join_values(question_numbers[:3])}")
            elif knowledge_signals:
                parts.append(f"知识点信号：{_join_values(knowledge_signals[:3])}")
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


def _evidence_values(pdf_evidence: list[MaterialPageEvidence], field: str) -> list[str]:
    values: list[str] = []
    for item in pdf_evidence:
        raw_values = getattr(item, field, ())
        if not isinstance(raw_values, tuple):
            continue
        for value in raw_values:
            cleaned = str(value).strip()
            if cleaned and cleaned not in values:
                values.append(cleaned)
            if len(values) >= 6:
                return values
    return values


def _evidence_for_material(
    pdf_evidence: list[MaterialPageEvidence],
    material: MaterialRecord,
) -> list[MaterialPageEvidence]:
    try:
        material_id = int(material.id)
    except (TypeError, ValueError):
        return []
    return [item for item in pdf_evidence if int(item.material_id) == material_id]


def _evidence_pages(pdf_evidence: list[MaterialPageEvidence]) -> list[str]:
    pages: list[str] = []
    for item in pdf_evidence:
        page = str(item.page).strip()
        if page and page not in pages:
            pages.append(page)
        if len(pages) >= 3:
            break
    return pages


def _material_evidence_values(pdf_evidence: list[MaterialPageEvidence], field: str) -> list[str]:
    values: list[str] = []
    for item in pdf_evidence:
        raw_values = getattr(item, field, ())
        if not isinstance(raw_values, tuple):
            continue
        for value in raw_values:
            cleaned = str(value).strip()
            if cleaned and cleaned not in values:
                values.append(cleaned)
            if len(values) >= 6:
                return values
    return values


def _course_card_values(course_memory_card: CourseMemoryCard | None, field: str) -> list[str]:
    if course_memory_card is None:
        return []
    raw_items = getattr(course_memory_card, field, ())
    if not isinstance(raw_items, tuple):
        return []
    values: list[str] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if value and value not in values:
            values.append(value)
        if len(values) >= 6:
            break
    return values


def _join_values(values: list[str]) -> str:
    return "、".join(value for value in values if value)


def _default_followups() -> list[str]:
    return [
        "你更想要真题、笔记还是经验分享？",
        "是否需要限定学校、学院或专业？",
    ]


def _dedupe_questions(questions: list[str]) -> list[str]:
    result: list[str] = []
    for question in questions:
        cleaned = " ".join(str(question).split())
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result
