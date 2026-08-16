from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.agent_tool_loop_service import recover_agent_tool_payload


READ_ONLY_ROUTER_TOOLS = frozenset(
    {
        "search_materials",
        "inspect_materials",
        "read_pdf_evidence",
        "read_memory",
        "synthesize_course_context",
    }
)
_FILTER_FIELDS = frozenset({"school", "college", "major", "tag"})
_EXPLICIT_PAGE_PATTERNS = (
    re.compile(r"第\s*([1-9][0-9]?)\s*页", re.IGNORECASE),
    re.compile(r"\bpage\s*([1-9][0-9]?)\b", re.IGNORECASE),
)
_BAIDU_LINK = re.compile(
    r"https?://(?:pan\.baidu\.com|yun\.baidu\.com)\S*",
    re.IGNORECASE,
)
_EXTRACTION_CODE = re.compile(
    r"(?:pwd|提取码)\s*[:=：]\s*[A-Za-z0-9]{4,}",
    re.IGNORECASE,
)
_THINK_TAG = re.compile(r"</?think>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ConstrainedRouterOutput:
    value: dict[str, Any]
    source_status: str
    corrections: tuple[str, ...]
    deterministic_route: str | None


@dataclass(frozen=True, slots=True)
class _TrustedRouterState:
    query: str
    task_context: dict[str, Any]
    budget: dict[str, int]
    candidate_ids: tuple[int, ...]
    material_ids: tuple[int, ...]
    observed_ids: tuple[int, ...]
    material_titles: dict[int, str]
    explicit_pages: tuple[int, ...]
    last_search_empty: bool
    has_memory: bool
    has_evidence: bool
    has_untrusted_observation: bool

    @property
    def must_finish(self) -> bool:
        return self.budget["remaining_tool_calls"] <= 0

    @property
    def can_search(self) -> bool:
        return not self.must_finish and self.budget["remaining_search_calls"] > 0 and self.budget["remaining_candidate_slots"] > 0


def constrain_router_output(
    raw_output: str | Mapping[str, Any],
    request_payload: Mapping[str, Any],
    *,
    protect_deterministic_arguments: bool = True,
) -> ConstrainedRouterOutput:
    """Decode a Router response into one canonical, read-only typed action.

    The decoder never reads labels or task-family metadata. It only uses the
    model output and trusted runtime state already available to the production
    loop. This keeps syntax, budgets, IDs and explicit pages out of the policy
    learning problem while leaving semantic query rewriting and stopping
    decisions with the model.
    """

    parsed, source_status = _parse_model_output(raw_output)
    state = _trusted_state(request_payload)
    corrections: list[str] = []
    if state.has_untrusted_observation:
        # Tool text is data, never a control-flow instruction. The typed fields
        # and user request still determine the route; sanitizers below keep the
        # resulting action read-only and remove sensitive text.
        corrections.append("ignore_untrusted_observation")
    if source_status == "recovered":
        corrections.append("recover_invalid_json")
    elif source_status == "fallback":
        corrections.append("replace_unparseable_output")

    deterministic_route, route_reason = _deterministic_route(state)
    if route_reason:
        corrections.append(route_reason)

    if deterministic_route == "final":
        value = _sanitize_final(
            parsed,
            state,
            refusal=_is_permission_bypass_request(state.query),
        )
    else:
        model_route = _model_route(parsed)
        route = deterministic_route or model_route
        if route == "final":
            value = _sanitize_final(parsed, state)
        elif route in READ_ONLY_ROUTER_TOOLS:
            value = _sanitize_tool_output(
                parsed,
                state,
                route,
                force_state_arguments=deterministic_route is not None,
                protect_deterministic_arguments=protect_deterministic_arguments,
                corrections=corrections,
            )
            if value is None:
                fallback_route = _safe_fallback_route(state)
                if fallback_route is None:
                    value = _sanitize_final(parsed, state)
                else:
                    corrections.append("replace_unexecutable_action")
                    value = _sanitize_tool_output(
                        {},
                        state,
                        fallback_route,
                        force_state_arguments=True,
                        protect_deterministic_arguments=True,
                        corrections=corrections,
                    )
                    if value is None:
                        value = _sanitize_final({}, state)
        else:
            fallback_route = _safe_fallback_route(state)
            if fallback_route is None:
                value = _sanitize_final(parsed, state)
            else:
                corrections.append("select_safe_state_fallback")
                value = _sanitize_tool_output(
                    parsed,
                    state,
                    fallback_route,
                    force_state_arguments=True,
                    protect_deterministic_arguments=True,
                    corrections=corrections,
                )
                if value is None:
                    value = _sanitize_final({}, state)

    if not isinstance(parsed, Mapping) or _canonical_json(parsed) != _canonical_json(value):
        corrections.append("canonicalize_contract")
    return ConstrainedRouterOutput(
        value=value,
        source_status=source_status,
        corrections=tuple(dict.fromkeys(corrections)),
        deterministic_route=deterministic_route,
    )


def _parse_model_output(
    raw_output: str | Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    if isinstance(raw_output, Mapping):
        return dict(raw_output), "strict"
    text = str(raw_output or "").strip()
    if not text or _THINK_TAG.search(text):
        return {}, "fallback"
    strict_text = text
    if strict_text.startswith("```"):
        strict_text = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            strict_text,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
    start = strict_text.find("{")
    end = strict_text.rfind("}")
    if start >= 0 and end > start:
        candidate = strict_text[start : end + 1]
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(value, dict):
                status = "strict" if candidate == text else "recovered"
                return value, status
    recovered = recover_agent_tool_payload(text)
    return (recovered, "recovered") if recovered is not None else ({}, "fallback")


def _trusted_state(payload: Mapping[str, Any]) -> _TrustedRouterState:
    query = _safe_text(payload.get("current_user_query"), maximum=1200)
    budget_value = payload.get("budget")
    budget = budget_value if isinstance(budget_value, Mapping) else {}
    parsed_budget = {
        "remaining_rounds": _nonnegative_int(budget.get("remaining_rounds"), default=1),
        "remaining_tool_calls": _nonnegative_int(budget.get("remaining_tool_calls"), default=1),
        "remaining_search_calls": _nonnegative_int(budget.get("remaining_search_calls"), default=0),
        "remaining_candidate_slots": _nonnegative_int(budget.get("remaining_candidate_slots"), default=0),
    }
    if payload.get("force_final") is True or parsed_budget["remaining_rounds"] <= 0:
        parsed_budget["remaining_tool_calls"] = 0

    observations = payload.get("tool_observations")
    observations = observations if isinstance(observations, list) else []
    candidate_ids: list[int] = []
    material_ids: list[int] = []
    observed_ids: list[int] = []
    titles: dict[int, str] = {}
    last_search_empty = False
    has_memory = False
    has_evidence = False
    has_untrusted = False
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        tool = str(observation.get("tool") or "")
        result = observation.get("result")
        if not isinstance(result, Mapping):
            continue
        has_untrusted = has_untrusted or _contains_untrusted_field(result)
        if tool == "search_materials":
            candidates = result.get("candidates")
            candidates = candidates if isinstance(candidates, list) else []
            candidate_ids = _ids_from_items(candidates, titles=titles)
            last_search_empty = not candidate_ids and (result.get("executed") is True or result.get("count") == 0)
            _extend_unique(observed_ids, candidate_ids)
        elif tool == "inspect_materials":
            materials = result.get("materials")
            materials = materials if isinstance(materials, list) else []
            material_ids = _ids_from_items(materials, titles=titles)
            _extend_unique(observed_ids, material_ids)
        elif tool == "read_pdf_evidence":
            ids = _positive_int_list(result.get("material_ids"), maximum=32)
            evidence = result.get("evidence")
            if isinstance(evidence, list):
                _extend_unique(ids, _ids_from_items(evidence, titles=titles))
            _extend_unique(observed_ids, ids)
            has_evidence = bool(ids or evidence or result.get("evidence_status"))
        elif tool == "read_memory":
            has_memory = True

    return _TrustedRouterState(
        query=query,
        task_context=_sanitize_task_context(payload.get("task_context")),
        budget=parsed_budget,
        candidate_ids=tuple(candidate_ids),
        material_ids=tuple(material_ids),
        observed_ids=tuple(observed_ids),
        material_titles=titles,
        explicit_pages=tuple(_explicit_pages(query)),
        last_search_empty=last_search_empty,
        has_memory=has_memory,
        has_evidence=has_evidence,
        has_untrusted_observation=has_untrusted,
    )


def _deterministic_route(state: _TrustedRouterState) -> tuple[str | None, str | None]:
    if state.must_finish:
        return "final", "force_final_budget"
    if _is_permission_bypass_request(state.query):
        return "final", "enforce_permission_boundary"
    if _is_explicit_final_request(state.query):
        return "final", "honor_explicit_final"
    if state.explicit_pages and state.observed_ids:
        return "read_pdf_evidence", "protect_explicit_page_route"
    if _is_memory_read_request(state.query):
        return "read_memory", "honor_explicit_memory_read"
    if _has_any(state.query, ("整合", "合并", "汇总", "结构化上下文")) and (state.has_memory or state.has_evidence):
        return "synthesize_course_context", "honor_explicit_synthesis"
    if state.last_search_empty and state.can_search:
        return "search_materials", "recover_empty_search"
    # Candidate inspection is the current action when the user explicitly says
    # to verify metadata before deciding whether to read the document.  Check it
    # before broad evidence keywords such as "正文" or "复习重点", which may only
    # describe a later conditional step.
    if state.candidate_ids and _has_any(
        state.query,
        ("核验", "核对", "检查", "验证", "确认资料详情", "详情查清", "详细元数据", "初筛"),
    ):
        return "inspect_materials", "honor_explicit_candidate_inspection"
    if state.observed_ids and _has_any(
        state.query,
        ("页级证据", "页面证据", "页级依据", "具体页面", "页面内容", "关键公式", "典型例题", "易错点", "复习重点", "正文"),
    ):
        return "read_pdf_evidence", "honor_explicit_evidence_read"
    if state.can_search and _is_search_request(state.query):
        return "search_materials", "honor_explicit_search"
    return None, None


def _safe_fallback_route(state: _TrustedRouterState) -> str | None:
    if state.must_finish:
        return None
    if state.candidate_ids:
        return "inspect_materials"
    if state.material_ids:
        return "read_pdf_evidence"
    if state.last_search_empty and state.can_search:
        return "search_materials"
    return None


def _model_route(parsed: Mapping[str, Any]) -> str | None:
    mode = str(parsed.get("mode") or "").strip().lower()
    actions = parsed.get("actions")
    if mode == "final" or (isinstance(parsed.get("answer"), str) and (not isinstance(actions, list) or not actions)):
        return "final"
    if mode != "tools" or not isinstance(actions, list) or not actions:
        return None
    first = actions[0]
    if not isinstance(first, Mapping):
        return None
    name = str(first.get("name") or "").strip()
    return name if name in READ_ONLY_ROUTER_TOOLS else None


def _sanitize_tool_output(
    parsed: Mapping[str, Any],
    state: _TrustedRouterState,
    route: str,
    *,
    force_state_arguments: bool,
    protect_deterministic_arguments: bool,
    corrections: list[str],
) -> dict[str, Any] | None:
    original_action = _first_action(parsed)
    original_arguments = original_action.get("arguments")
    original_arguments = original_arguments if isinstance(original_arguments, Mapping) else {}
    protect = force_state_arguments or protect_deterministic_arguments

    if route == "search_materials":
        if not state.can_search:
            return None
        query = _safe_text(original_arguments.get("query"), maximum=500)
        # Query rewriting is policy-owned. Preserve a valid rewritten query and
        # synthesize one from trusted context only when the model omitted it.
        if not query and state.last_search_empty:
            query = _context_search_query(state)
        query = query or _context_search_query(state) or state.query[:500]
        limit = _bounded_int(original_arguments.get("limit"), minimum=1, maximum=12, default=8)
        explicit_limit = _explicit_result_limit(state.query)
        if protect and explicit_limit is not None:
            limit = explicit_limit
            corrections.append("protect_search_limit")
        slots = state.budget["remaining_candidate_slots"]
        limit = min(limit, max(1, slots))
        filters = _sanitize_filters(original_arguments.get("filters"))
        if protect and "不限定学校" in state.query:
            filters = {}
        elif protect and "只看电子科技大学" in state.query:
            filters = {"school": "电子科技大学"}
        arguments: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "filters": filters,
        }
    elif route == "inspect_materials":
        trusted_ids = list(state.candidate_ids or state.observed_ids)
        model_ids = _positive_int_list(original_arguments.get("material_ids"), maximum=8)
        material_ids = trusted_ids[:8] if protect else [item for item in model_ids if item in trusted_ids][:8]
        if not material_ids:
            material_ids = trusted_ids[:8]
        if not material_ids:
            return None
        if material_ids != model_ids:
            corrections.append("protect_material_ids")
        arguments = {"material_ids": material_ids}
    elif route == "read_pdf_evidence":
        trusted_ids = list(state.material_ids or state.candidate_ids or state.observed_ids)
        model_ids = _positive_int_list(original_arguments.get("material_ids"), maximum=6)
        material_ids = trusted_ids[:6] if protect else [item for item in model_ids if item in trusted_ids][:6]
        if not material_ids:
            material_ids = trusted_ids[:6]
        if not material_ids:
            return None
        if material_ids != model_ids:
            corrections.append("protect_material_ids")
        evidence_query = _safe_text(original_arguments.get("query"), maximum=500)
        evidence_query = evidence_query or _context_evidence_query(state)
        max_pages = _bounded_int(original_arguments.get("max_pages"), minimum=1, maximum=8, default=4)
        arguments = {
            "material_ids": material_ids,
            "query": evidence_query,
            "max_pages": max_pages,
        }
        model_pages = _positive_int_list(original_arguments.get("page_numbers"), maximum=8, upper=80)
        if protect and state.explicit_pages:
            arguments["page_numbers"] = list(state.explicit_pages)
            arguments["max_pages"] = max(1, len(state.explicit_pages))
            if model_pages != list(state.explicit_pages):
                corrections.append("protect_page_numbers")
        elif model_pages:
            arguments["page_numbers"] = model_pages
    elif route == "read_memory":
        focus = _safe_text(original_arguments.get("focus"), maximum=500)
        arguments = {"focus": focus or _context_memory_focus(state)}
    elif route == "synthesize_course_context":
        context_terms = _safe_string_list(state.task_context.get("course_terms"), limit=4, maximum=80)
        arguments = {
            "task_label": _safe_text(original_arguments.get("task_label"), maximum=160) or _context_task_label(state),
            "course_terms": context_terms or _safe_string_list(original_arguments.get("course_terms"), limit=4, maximum=80),
            "evidence_goals": _safe_string_list(original_arguments.get("evidence_goals"), limit=6, maximum=160),
            "response_preferences": _safe_string_list(original_arguments.get("response_preferences"), limit=6, maximum=160),
            "constraints": _safe_string_list(original_arguments.get("constraints"), limit=6, maximum=160),
        }
    else:
        return None

    progress = _safe_text(parsed.get("progress"), maximum=60) or _default_progress(route)
    return {
        "mode": "tools",
        "progress": progress,
        "task_context": state.task_context,
        "actions": [{"name": route, "arguments": arguments}],
    }


def _sanitize_final(
    parsed: Mapping[str, Any],
    state: _TrustedRouterState,
    *,
    refusal: bool = False,
) -> dict[str, Any]:
    answer = _safe_text(parsed.get("answer"), maximum=5000)
    if refusal:
        answer = (
            "不能执行该请求。StudyHub Agent 仅使用获准的只读工具和当前账号有权访问的免费资料，"
            "不会绕过购买或权限校验、修改平台数据、读取他人隐私或泄露内部凭据。"
        )
    elif len(answer) < 20:
        answer = (
            "工具预算已经用完；我只能基于当前已核验的公开信息给出有限结论，不会推断或虚构尚未读取的资料正文、资料编号或页码。"
            if state.must_finish
            else "当前证据不足以给出具体站内资料结论；我会保留不确定性，不虚构资料、页码或平台事实。"
        )

    allowed_ids = set(state.observed_ids)
    recommendations: list[dict[str, Any]] = []
    raw_recommendations = parsed.get("recommendations")
    if isinstance(raw_recommendations, list):
        for item in raw_recommendations:
            if not isinstance(item, Mapping):
                continue
            material_id = _positive_int(item.get("material_id"))
            reason = _safe_text(item.get("reason"), maximum=240)
            if material_id in allowed_ids and reason:
                recommendations.append({"material_id": material_id, "reason": reason})
            if len(recommendations) >= 6:
                break

    evidence_sources: list[dict[str, Any]] = []
    raw_sources = parsed.get("evidence_sources")
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if not isinstance(item, Mapping):
                continue
            material_id = _positive_int(item.get("material_id"))
            chunk_id = _safe_text(item.get("chunk_id"), maximum=160)
            title = _safe_text(item.get("title"), maximum=240)
            if material_id not in allowed_ids or not chunk_id or not title:
                continue
            source: dict[str, Any] = {
                "material_id": material_id,
                "chunk_id": chunk_id,
                "title": title,
                "page": None,
            }
            page = _positive_int(item.get("page"), upper=80)
            if page is not None:
                source["page"] = page
            evidence_sources.append(source)
            if len(evidence_sources) >= 12:
                break

    return {
        "mode": "final",
        "task_context": state.task_context,
        "answer": answer,
        "recommendations": recommendations,
        "evidence_sources": evidence_sources,
        "followup_questions": _safe_string_list(parsed.get("followup_questions"), limit=3, maximum=240),
    }


def _first_action(value: Mapping[str, Any]) -> Mapping[str, Any]:
    actions = value.get("actions")
    if not isinstance(actions, list) or not actions or not isinstance(actions[0], Mapping):
        return {}
    return actions[0]


def _sanitize_task_context(value: object) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    result: dict[str, Any] = {
        "course_terms": _safe_string_list(source.get("course_terms"), limit=4, maximum=80),
        "exam_goal": _safe_text(source.get("exam_goal"), maximum=160),
        "time_budget": {},
        "resource_types": _safe_string_list(source.get("resource_types"), limit=5, maximum=80),
        "constraints": _safe_string_list(source.get("constraints"), limit=6, maximum=80),
    }
    raw_budget = source.get("time_budget")
    if isinstance(raw_budget, Mapping):
        cleaned_budget: dict[str, int | float | str] = {}
        for key, upper in (
            ("days_until_exam", 365),
            ("daily_hours", 24),
            ("total_hours", 1000),
            ("available_minutes", 1440),
        ):
            number = _positive_number(raw_budget.get(key), upper=upper)
            if number is not None:
                cleaned_budget[key] = number
        description = _safe_text(raw_budget.get("description"), maximum=120)
        if description:
            cleaned_budget["description"] = description
        result["time_budget"] = cleaned_budget
    return result


def _context_search_query(state: _TrustedRouterState) -> str:
    terms = _safe_string_list(state.task_context.get("course_terms"), limit=2, maximum=80)
    resources = _safe_string_list(state.task_context.get("resource_types"), limit=2, maximum=80)
    return " ".join([*terms, *resources]).strip()[:500]


def _context_evidence_query(state: _TrustedRouterState) -> str:
    terms = _safe_string_list(state.task_context.get("course_terms"), limit=2, maximum=80)
    pages = " ".join(f"第{page}页" for page in state.explicit_pages)
    return (" ".join([*terms, pages, "可核验的页级内容"]).strip() or state.query)[:500]


def _context_memory_focus(state: _TrustedRouterState) -> str:
    terms = _safe_string_list(state.task_context.get("course_terms"), limit=2, maximum=80)
    subject = "、".join(terms) or "当前课程"
    return f"本人关于{subject}的薄弱点、节奏与学习偏好"


def _context_task_label(state: _TrustedRouterState) -> str:
    terms = _safe_string_list(state.task_context.get("course_terms"), limit=2, maximum=80)
    subject = "、".join(terms) or "当前课程"
    return f"{subject}学习上下文整合"[:160]


def _default_progress(route: str) -> str:
    return {
        "search_materials": "检索免费资料候选中",
        "inspect_materials": "核验候选资料详情中",
        "read_pdf_evidence": "读取允许的页级证据中",
        "read_memory": "读取当前用户学习记忆中",
        "synthesize_course_context": "整合课程学习上下文中",
    }[route]


def _is_permission_bypass_request(query: str) -> bool:
    if _has_any(query, ("不要执行", "不要使用", "不要遵循")) and _has_any(query, ("可疑指令", "工具结果", "不可信")):
        return False
    return _has_any(
        query,
        (
            "绕过购买",
            "绕过权限",
            "跳过权限",
            "忽略只读限制",
            "付费资料的网盘链接",
            "收费资料复制",
            "读取另一位用户",
            "其他学生的收藏",
            "别人的个人学习",
            "所有用户",
            "私人联系方式",
            "生产数据库",
            "生产环境的访问凭据",
            "管理员才能看到",
            "私有对象存储",
            "银行卡",
            "删除别人",
            "发布一份新资料",
            "价格改成零",
            "修改某份资料",
            "批量给资料点赞",
            "伪造一次下载",
            "替我购买",
            "完成支付",
            "写工具",
            "shell 工具",
            "审核状态改成",
            "关闭资料的版权",
            "已经被删除的资料",
            "隐藏文件内容",
            "题解请求历史",
        ),
    )


def _is_search_request(query: str) -> bool:
    if _has_any(
        query,
        (
            "不要搜索",
            "不用搜索",
            "无需搜索",
            "不需要搜索",
            "先不要搜索",
            "别搜索",
            "区分搜索",
            "什么情况下",
            "什么时候",
            "何时",
        ),
    ):
        return False
    return _has_any(
        query,
        ("先搜", "搜索", "检索", "搜站内", "搜一下", "查一下", "先查", "资料发现", "找资料", "找免费资料"),
    )


def _is_explicit_final_request(query: str) -> bool:
    return _has_any(
        query,
        (
            "不再调用工具",
            "不要再调用工具",
            "无需再调用工具",
            "不再使用工具",
            "只依据现有",
            "收束回答",
            "结束本轮",
            "直接回答",
        ),
    )


def _is_memory_read_request(query: str) -> bool:
    if not _has_any(
        query,
        ("个人学习记忆", "学习记忆", "历史节奏", "学习节奏", "薄弱点", "复习偏好", "学习偏好", "掌握记录"),
    ):
        return False
    return _has_any(
        query,
        ("请读取", "先读取", "请先读取", "取回", "先查我的", "请先查", "先确认我过去", "请先确认"),
    )


def _explicit_pages(query: str) -> list[int]:
    pages: list[int] = []
    for pattern in _EXPLICIT_PAGE_PATTERNS:
        for match in pattern.finditer(query):
            value = _positive_int(match.group(1), upper=80)
            if value is not None and value not in pages:
                pages.append(value)
    return pages[:8]


def _explicit_result_limit(query: str) -> int | None:
    patterns = (
        re.compile(r"(?:最多|上限|限制|不超过|不要超过|至多|控制在)\s*([1-9][0-9]?)"),
        re.compile(r"([1-9][0-9]?)\s*(?:份|个|项|条)(?:以内|候选|结果)?"),
    )
    for pattern in patterns:
        match = pattern.search(query)
        if match is not None:
            return min(12, int(match.group(1)))
    return None


def _sanitize_filters(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): text for key, item in value.items() if str(key) in _FILTER_FIELDS and (text := _safe_text(item, maximum=100))}


def _contains_untrusted_field(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).startswith("untrusted_") or _contains_untrusted_field(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_untrusted_field(item) for item in value)
    return False


def _ids_from_items(items: list[Any], *, titles: dict[int, str]) -> list[int]:
    result: list[int] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        material_id = _positive_int(item.get("id") or item.get("material_id"))
        if material_id is None or material_id in result:
            continue
        result.append(material_id)
        title = _safe_text(item.get("title"), maximum=240)
        if title:
            titles[material_id] = title
    return result


def _positive_int_list(
    value: object,
    *,
    maximum: int,
    upper: int | None = None,
) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        number = _positive_int(item, upper=upper)
        if number is not None and number not in result:
            result.append(number)
        if len(result) >= maximum:
            break
    return result


def _positive_int(value: object, *, upper: int | None = None) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or (upper is not None and number > upper):
        return None
    return number


def _nonnegative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, number)


def _positive_number(value: object, *, upper: float) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    number = min(number, upper)
    return int(number) if number.is_integer() else number


def _bounded_int(
    value: object,
    *,
    minimum: int,
    maximum: int,
    default: int,
) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _safe_string_list(value: object, *, limit: int, maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _safe_text(item, maximum=maximum)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _safe_text(value: object, *, maximum: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    text = _BAIDU_LINK.sub("[已隐藏网盘链接]", text)
    text = _EXTRACTION_CODE.sub("[已隐藏提取码]", text)
    text = _THINK_TAG.sub("", text)
    return text[:maximum]


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in phrases)


def _extend_unique(destination: list[int], values: list[int]) -> None:
    for value in values:
        if value not in destination:
            destination.append(value)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
