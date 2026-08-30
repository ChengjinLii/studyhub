#!/usr/bin/env python3
"""Build independent training tasks for Codex-driven Hermes rollouts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.data.select_runtime_sft_v3 import (  # noqa: E402
    normalized_text,
    public_benchmark_prompt_hashes,
    sha256,
)
from scripts.data.verify_teacher_trajectories import verify_run  # noqa: E402
from studyhub_agent.benchmark_v1.tool_contracts import tool_schemas  # noqa: E402
from training.rl.frozen_environment import FrozenTaskEnvironment  # noqa: E402

SCHEMA_VERSION = "studyhub.codex-hermes-training-tasks.v2"
DATASET_ID = "codex_hermes_teacher_v1"
TASK_DESIGN_REVISION = "semantic-diversity-v2"
DEFAULT_SEED = 20260827
FAMILY_WEIGHTS = {
    "rag_query_rewrite_citation": 0.20,
    "web_source_conflict_freshness": 0.15,
    "memory_personalization_privacy": 0.20,
    "cross_tool_composition": 0.15,
    "recovery_acl_provider_error": 0.15,
    "stateful_function": 0.10,
    "direct_abstention": 0.05,
}
CAPABILITIES = {
    "knowledge_search": "knowledge_search",
    "knowledge_read": "knowledge_read",
    "web_search": "replay_search",
    "web_extract": "evidence_fetch",
    "personal_memory_search": "replay_search",
    "collective_memory_search": "replay_search",
    "learning_profile_get": "function_call",
    "study_plan_update": "function_call",
    "material_bookmark_add": "function_call",
    "learning_progress_record": "function_call",
}
COURSES = (
    "通信原理",
    "高等数学",
    "概率论",
    "数据结构",
    "计算机网络",
    "数字电路",
    "信号与系统",
    "机器学习",
    "操作系统",
    "线性代数",
    "离散数学",
    "数据库系统",
    "编译原理",
    "计算机组成原理",
    "自动控制原理",
    "数字信号处理",
    "大学物理",
    "工程数学",
    "算法设计",
    "软件工程",
)
TOPICS = (
    "匹配滤波",
    "多元微分",
    "条件概率",
    "平衡树",
    "拥塞控制",
    "时序逻辑",
    "卷积性质",
    "正则化",
    "虚拟内存",
    "特征分解",
    "信道编码",
    "曲线积分",
    "贝叶斯估计",
    "图最短路",
    "流量控制",
    "组合逻辑",
    "频域采样",
    "梯度裁剪",
    "页面置换",
    "正交投影",
    "集合映射",
    "事务隔离",
    "语法分析",
    "流水线冒险",
    "根轨迹",
    "窗函数",
    "电磁感应",
    "拉普拉斯变换",
    "动态规划",
    "需求建模",
)
ACTIVITIES = (
    "先画系统框图",
    "先整理公式适用条件",
    "先做一组概念辨析题",
    "先手写关键数据结构",
    "先画协议状态转换图",
    "先检查时序约束",
    "先从图像理解卷积",
    "先比较训练与验证误差",
    "先画地址转换流程",
    "先核对矩阵维度",
    "先列出已知量和未知量",
    "先做一个反例检查边界",
    "先把定义改写成自己的话",
    "先比较两个易混淆概念",
    "先按时间顺序复盘执行过程",
    "先标记最容易出错的一步",
    "先用小规模样例手算",
    "先建立输入输出对照表",
    "先画出依赖关系图",
    "先归纳三条判定条件",
    "先检查单位和量纲",
    "先拆成基础题和综合题",
    "先复述算法不变量",
    "先把结论映射到实际场景",
    "先做一次无提示回忆",
    "先整理错误类型清单",
    "先验证一个极端情况",
    "先写出最短求解路径",
    "先给每个步骤补充理由",
    "先完成五分钟快速测验",
)
MATERIAL_KINDS = (
    "训练讲义",
    "错题精析",
    "公式手册",
    "实验指导",
    "复习路线",
    "例题集",
    "概念图谱",
    "专题笔记",
    "自测清单",
    "案例解析",
)
STUDY_CONTEXTS = (
    "期末复习",
    "章节预习",
    "错题回顾",
    "实验准备",
    "课程设计",
    "口试准备",
    "周末巩固",
    "概念查漏",
    "阶段自测",
    "跨章节串联",
)
NOTICE_KINDS = (
    "答疑安排",
    "实验验收",
    "课程设计评审",
    "期中复习课",
    "机房开放",
    "口试安排",
    "作业讲评",
    "补课通知",
)


@dataclass(slots=True)
class Scenario:
    task: dict[str, Any]
    environment: dict[str, Any]
    fixture: dict[str, Any]
    verifier: dict[str, Any]
    audit_actions: list[tuple[str, dict[str, Any]]]
    audit_final: str


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _stable_id(family: str, ordinal: int, seed: int) -> str:
    digest = hashlib.sha256(f"{DATASET_ID}:{TASK_DESIGN_REVISION}:{seed}:{family}:{ordinal}".encode()).hexdigest()[:18]
    return f"codex-train-{digest}"


def _pick(values: tuple[str, ...], *, family: str, ordinal: int, seed: int, label: str) -> str:
    digest = hashlib.sha256(f"{TASK_DESIGN_REVISION}:{seed}:{family}:{ordinal}:{label}".encode()).digest()
    return values[int.from_bytes(digest[:8], "big") % len(values)]


def _pick_int(size: int, *, family: str, ordinal: int, seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{TASK_DESIGN_REVISION}:{seed}:{family}:{ordinal}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _axes(family: str, ordinal: int, seed: int) -> tuple[str, str, str, str, str]:
    return (
        _pick(COURSES, family=family, ordinal=ordinal, seed=seed, label="course"),
        _pick(TOPICS, family=family, ordinal=ordinal, seed=seed, label="topic"),
        _pick(ACTIVITIES, family=family, ordinal=ordinal, seed=seed, label="activity"),
        _pick(MATERIAL_KINDS, family=family, ordinal=ordinal, seed=seed, label="material-kind"),
        _pick(STUDY_CONTEXTS, family=family, ordinal=ordinal, seed=seed, label="study-context"),
    )


def _allocate(total: int) -> dict[str, int]:
    raw = {family: total * weight for family, weight in FAMILY_WEIGHTS.items()}
    result = {family: int(value) for family, value in raw.items()}
    remaining = total - sum(result.values())
    order = sorted(raw, key=lambda family: (-(raw[family] - result[family]), family))
    for family in order[:remaining]:
        result[family] += 1
    return result


def _tools(names: list[str]) -> list[dict[str, Any]]:
    result = []
    frozen_names = [name for name in names if name != "web_extract"]
    rows = tool_schemas(frozen_names)
    if "web_extract" in names:
        rows.append(
            {
                "name": "web_extract",
                "description": "Extract clean content from up to five public URLs using the Hermes Web contract.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 5,
                        },
                        "char_limit": {"type": "integer", "minimum": 2000},
                    },
                    "required": ["urls"],
                },
            }
        )
    by_name = {row["name"]: row for row in rows}
    for name in names:
        row = by_name[name]
        copied = deepcopy(row)
        copied["capability"] = CAPABILITIES[copied["name"]]
        result.append(copied)
    return result


def _route(
    name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    *,
    flexible_fields: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "arguments": arguments, "result": result}
    if flexible_fields:
        row["argument_match"] = {
            "mode": "exact_except",
            "flexible_fields": flexible_fields,
        }
    return row


def _base_task(
    *,
    task_id: str,
    family: str,
    user_request: str,
    allowed_tools: list[str],
    source_group_id: str,
    minimum_citations: int = 0,
    minimum_state_changes: int = 0,
    max_steps: int = 8,
    max_tool_calls: int = 8,
) -> dict[str, Any]:
    return {
        "schema_version": "studyhub.codex-hermes-task.v1",
        "task_id": task_id,
        "family": family,
        "user_request": user_request,
        "allowed_tools": allowed_tools,
        "max_steps": max_steps,
        "max_tool_calls": max_tool_calls,
        "completion_contract": {
            "citation_format": "[source_id]",
            "minimum_grounded_citations": minimum_citations,
            "minimum_successful_state_changes": minimum_state_changes,
            "search_result_requires_read_or_fetch_before_citation": True,
        },
        "metadata": {
            "teacher_dataset": DATASET_ID,
            "environment_id": task_id,
            "source_group_id": source_group_id,
            "source_group_ids": [source_group_id],
            "source_origin": "independent_training_simulator",
            "source_license": "StudyHub-generated-training-simulator-v1",
            "benchmark_overlap": False,
            "environment_built_before_task": True,
            "split": "train",
        },
    }


def _base_verifier(
    *,
    task_id: str,
    family: str,
    source_group_id: str,
    reference_final: str,
    concept_groups: list[list[str]],
    allowed_citations: list[str] | None = None,
    minimum_citations: int = 0,
    tool_groups: list[list[str]] | None = None,
    markers: list[str] | None = None,
    forbidden_terms: list[str] | None = None,
    require_no_tools: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "studyhub.codex-hermes-verifier.v1",
        "verifier_mode": "path_agnostic_v2",
        "task_id": task_id,
        "family": family,
        "source_group_id": source_group_id,
        "reference_final": reference_final,
        "reference_final_sha256": hashlib.sha256(reference_final.encode()).hexdigest(),
        "required_answer_concept_groups": concept_groups,
        "allowed_citations": allowed_citations or [],
        "minimum_citations": minimum_citations,
        "required_any_tool_groups": tool_groups or [],
        "required_observation_markers": markers or [],
        "forbidden_answer_terms": forbidden_terms or [],
        "require_no_tools": require_no_tools,
        "allow_schema_retry": False,
        "benchmark_prompt_overlap": False,
    }


def _rag(ordinal: int, seed: int) -> Scenario:
    family = "rag_query_rewrite_citation"
    task_id = _stable_id(family, ordinal, seed)
    course, topic, activity, material_kind, context = _axes(family, ordinal, seed)
    minutes = 45 + 15 * _pick_int(8, family=family, ordinal=ordinal, seed=seed, label="minutes")
    title = f"{course}·{topic}{material_kind} {ordinal + 1:04d}"
    source_id = f"training-rag:{ordinal:04d}:primary"
    documents = [
        {
            "source_id": source_id,
            "title": title,
            "text": (
                f"课程：{course}。主题：{topic}。适用场景：{context}。"
                f"这份{material_kind}建议的首个复习动作是“{activity}”，"
                f"每周安排 {minutes} 分钟。训练版本标记 RAG-{ordinal:04d}。"
            ),
        }
    ]
    for offset in range(1, 4):
        other_course = _pick(
            COURSES,
            family=family,
            ordinal=ordinal,
            seed=seed,
            label=f"distractor-course-{offset}",
        )
        other_topic = _pick(
            TOPICS,
            family=family,
            ordinal=ordinal,
            seed=seed,
            label=f"distractor-topic-{offset}",
        )
        other_activity = _pick(
            ACTIVITIES,
            family=family,
            ordinal=ordinal,
            seed=seed,
            label=f"distractor-activity-{offset}",
        )
        documents.append(
            {
                "source_id": f"training-rag:{ordinal:04d}:distractor-{offset}",
                "title": f"{other_course} {other_topic} 辅助资料 {ordinal + offset:04d}",
                "text": f"该资料讨论 {other_topic}，建议活动为 {other_activity}。",
            }
        )
    source_group = f"codex-rag:{ordinal:04d}"
    request_templates = (
        "我在做{context}。请从 StudyHub 训练库定位《{title}》，核对首个复习动作和每周投入，并引用正文。",
        "请检索《{title}》而不是同名辅助材料，告诉我它建议先做什么、每周学多久，并给出来源引用。",
        "为了学习{topic}，请阅读《{title}》，提炼第一步行动和周学习分钟数；答案必须基于读到的资料。",
        "帮我确认《{title}》是否适合{context}：先查资料，再说明起始动作和时间安排，最后附引用。",
        "不要只看搜索摘要。找到《{title}》后读取内容，报告首个训练动作与每周计划时间并引用。",
        "我需要一条可执行的{course}复习建议。请以《{title}》为依据，给出第一步和每周分钟数。",
        "请在若干相近资料中锁定《{title}》，核验其{topic}学习建议，并用引用支持时间与动作。",
        "从 StudyHub 训练资料中查清《{title}》的使用方法：首要动作是什么，每周应投入多少分钟？",
    )
    template = request_templates[
        _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
    ]
    request = template.format(
        context=context,
        title=title,
        topic=topic,
        course=course,
    )
    final = f"《{title}》建议{activity}，每周安排 {minutes} 分钟。[{source_id}]"
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=["knowledge_search", "knowledge_read"],
            source_group_id=source_group,
            minimum_citations=1,
            max_steps=6,
            max_tool_calls=5,
        ),
        environment={
            "tools": _tools(["knowledge_search", "knowledge_read"]),
            "documents": documents,
        },
        fixture={"routes": []},
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[[activity], [str(minutes)]],
            allowed_citations=[source_id],
            minimum_citations=1,
            tool_groups=[["knowledge_search"], ["knowledge_read"]],
        ),
        audit_actions=[
            ("knowledge_search", {"query": title, "limit": 5}),
            ("knowledge_read", {"source_id": source_id}),
        ],
        audit_final=final,
    )


def _web(ordinal: int, seed: int) -> Scenario:
    family = "web_source_conflict_freshness"
    task_id = _stable_id(family, ordinal, seed)
    course, topic, _activity, _material_kind, context = _axes(family, ordinal, seed)
    month = 1 + _pick_int(9, family=family, ordinal=ordinal, seed=seed, label="month")
    day = 1 + _pick_int(24, family=family, ordinal=ordinal, seed=seed, label="day")
    date = f"2026-{month:02d}-{day:02d}"
    date_zh = f"2026年{month}月{day}日"
    building = _pick(("A", "B", "C", "D", "E"), family=family, ordinal=ordinal, seed=seed, label="building")
    room = f"{building}{200 + _pick_int(180, family=family, ordinal=ordinal, seed=seed, label='room')}"
    notice_kind = _pick(
        NOTICE_KINDS,
        family=family,
        ordinal=ordinal,
        seed=seed,
        label="notice-kind",
    )
    notice_id = f"WEB-{ordinal:04d}"
    official_url = f"https://official.example.edu/training/{ordinal:04d}"
    stale_url = f"https://archive.example.org/training/{ordinal:04d}"
    official_source = f"training-web:{ordinal:04d}:official"
    stale_source = f"training-web:{ordinal:04d}:stale"
    search_result = {
        "ok": True,
        "results": [
            {
                "url": official_url,
                "source_id": official_source,
                "title": f"{course}{notice_kind}·教务处更新",
                "snippet": f"{topic}相关的当前官方安排",
            },
            {
                "url": stale_url,
                "source_id": stale_source,
                "title": f"{course}{notice_kind}·历史转载",
                "snippet": f"{context}旧版页面，可能过期",
            },
        ],
    }
    official_page = {
        "source_id": official_source,
        "citation": f"[{official_source}]",
        "title": f"{course}{notice_kind}·教务处更新",
        "published_at": "2026-08-20",
        "text": (f"通知 {notice_id}：{course} 的{notice_kind}确认于 {date}，地点为 {room}。这是当前有效通知。"),
    }
    stale_page = {
        "source_id": stale_source,
        "citation": f"[{stale_source}]",
        "title": f"{course}{notice_kind}·历史转载",
        "published_at": "2025-08-20",
        "text": "旧安排为 2025-09-01，地点 B101；页面标注已过期。",
    }
    source_group = f"codex-web:{ordinal:04d}"
    request_templates = (
        "请查证{course}通知 {notice_id} 中当前有效的{notice_kind}日期和地点，优先采用最新官方来源并附引用。",
        "网上有新旧两版{course}{notice_kind}。请核对 {notice_id}，只报告现行日期、教室和官方依据。",
        "我在准备{context}，需要确认{course}{notice_kind}。请搜索并比较来源的新旧程度后给出日期和地点。",
        "请验证 {notice_id} 是否已更新：找到{course}{notice_kind}的官方页面，排除过期转载，并引用结论。",
        "不要沿用历史转载。请为{course}的{notice_kind}找到最新可信页面，回答何时、在哪里举行。",
        "围绕{topic}的安排可能有冲突。请查明 {notice_id} 的当前{notice_kind}时间与地点，并说明依据。",
    )
    template = request_templates[
        _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
    ]
    request = template.format(
        course=course,
        notice_id=notice_id,
        notice_kind=notice_kind,
        context=context,
        topic=topic,
    )
    final = f"{course}当前{notice_kind}日期是 {date}，地点 {room}。[{official_source}]"
    fixtures = {
        "routes": [
            _route(
                "web_search",
                {"query": f"{course} {notice_kind}", "limit": 5},
                search_result,
            ),
            _route("web_extract", {"urls": [official_url]}, official_page),
            _route(
                "web_extract",
                {"urls": [official_url], "char_limit": 2000},
                official_page,
                flexible_fields=["char_limit"],
            ),
            _route("web_extract", {"urls": [stale_url]}, stale_page),
            _route(
                "web_extract",
                {"urls": [stale_url], "char_limit": 2000},
                stale_page,
                flexible_fields=["char_limit"],
            ),
            _route(
                "web_extract",
                {"urls": [official_url, stale_url]},
                {"pages": [official_page, stale_page]},
            ),
            _route(
                "web_extract",
                {
                    "urls": [official_url, stale_url],
                    "char_limit": 2000,
                },
                {"pages": [official_page, stale_page]},
                flexible_fields=["char_limit"],
            ),
        ]
    }
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=["web_search", "web_extract"],
            source_group_id=source_group,
            minimum_citations=1,
            max_steps=6,
            max_tool_calls=5,
        ),
        environment={"tools": _tools(["web_search", "web_extract"]), "documents": []},
        fixture=fixtures,
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[[date, date_zh], [room]],
            allowed_citations=[official_source],
            minimum_citations=1,
            tool_groups=[["web_search"], ["web_extract"]],
            forbidden_terms=["2025-09-01", "B101"],
        ),
        audit_actions=[
            ("web_search", {"query": f"{course} 最新 {notice_kind}", "limit": 5}),
            ("web_extract", {"urls": [official_url]}),
        ],
        audit_final=final,
    )


def _memory(ordinal: int, seed: int) -> Scenario:
    family = "memory_personalization_privacy"
    task_id = _stable_id(family, ordinal, seed)
    course, topic, current, material_kind, context = _axes(family, ordinal, seed)
    stale = _pick(
        ACTIVITIES,
        family=family,
        ordinal=ordinal,
        seed=seed,
        label="stale-activity",
    )
    if stale == current:
        stale = ACTIVITIES[(ACTIVITIES.index(stale) + 1) % len(ACTIVITIES)]
    target_id = 700_000 + ordinal * 2
    other_id = target_id + 1
    target_source = f"training-memory:{ordinal:04d}:target"
    other_source = f"training-memory:{ordinal:04d}:other"
    target_title = f"{course}·{topic}{material_kind} {ordinal + 1:04d}"
    other_kind = _pick(
        MATERIAL_KINDS,
        family=family,
        ordinal=ordinal,
        seed=seed,
        label="alternative-kind",
    )
    if other_kind == material_kind:
        other_kind = MATERIAL_KINDS[(MATERIAL_KINDS.index(other_kind) + 1) % len(MATERIAL_KINDS)]
    other_title = f"{course}·{topic}{other_kind} {ordinal + 1:04d}"
    memory_result = {
        "ok": True,
        "memories": [
            {
                "scope": "current_user",
                "preference": current,
                "updated_at": "2026-08-20",
            },
            {
                "scope": "current_user",
                "preference": stale,
                "updated_at": "2025-03-01",
                "stale": True,
            },
        ],
        "cross_user_records": [],
    }
    source_group = f"codex-memory:{ordinal:04d}"
    request_templates = (
        "请结合我对{course}的当前偏好，在《{target_title}》和《{other_title}》中选一本用于{context}。先查记忆，再读资料并引用。",
        "我的学习偏好可能已经更新。请核对最新记忆，比较《{target_title}》与《{other_title}》，推荐更匹配{topic}的一本。",
        "不要使用过期偏好或其他用户数据。请按当前的“{current}”偏好阅读两份{course}·{topic}资料，"
        "为{context}给出带引用的推荐。",
        "为我的{context}挑选资料：先确认现行学习方式，再从《{target_title}》和《{other_title}》中选择并说明理由。",
        "请检查个人记忆的时效性，然后核对《{target_title}》与《{other_title}》；"
        "{topic}推荐应与“{current}”偏好一致且附来源。",
        "我想按“{current}”的习惯做{course}·{topic}{context}。请读取个人偏好和两份候选资料，排除过期偏好后做选择。",
    )
    template = request_templates[
        _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
    ]
    request = template.format(
        course=course,
        topic=topic,
        context=context,
        target_title=target_title,
        other_title=other_title,
        current=current,
    )
    final = f"当前偏好是“{current}”，因此推荐《{target_title}》。[{target_source}]"
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=[
                "personal_memory_search",
                "knowledge_search",
                "knowledge_read",
            ],
            source_group_id=source_group,
            minimum_citations=1,
            max_steps=8,
            max_tool_calls=6,
        ),
        environment={
            "tools": _tools(["personal_memory_search", "knowledge_search", "knowledge_read"]),
            "documents": [
                {
                    "source_id": target_source,
                    "material_id": target_id,
                    "title": target_title,
                    "text": f"这份{material_kind}围绕{topic}，首要使用方式是：{current}。适合{context}。",
                },
                {
                    "source_id": other_source,
                    "material_id": other_id,
                    "title": other_title,
                    "text": f"这份{other_kind}围绕{topic}，首要使用方式是：{stale}。适合旧学习计划。",
                },
            ],
        },
        fixture={
            "routes": [
                _route(
                    "personal_memory_search",
                    {"query": f"{course} 当前偏好", "limit": 5},
                    memory_result,
                )
            ]
        },
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[[current], [target_title]],
            allowed_citations=[target_source],
            minimum_citations=1,
            tool_groups=[
                ["personal_memory_search"],
                ["knowledge_search"],
                ["knowledge_read"],
            ],
            forbidden_terms=["cross_user", "其他用户"],
        ),
        audit_actions=[
            ("personal_memory_search", {"query": f"{course} 当前偏好", "limit": 5}),
            ("knowledge_search", {"query": target_title, "limit": 5}),
            ("knowledge_read", {"source_id": target_source}),
        ],
        audit_final=final,
    )


def _cross_tool(ordinal: int, seed: int) -> Scenario:
    family = "cross_tool_composition"
    task_id = _stable_id(family, ordinal, seed)
    course, topic, activity, material_kind, context = _axes(family, ordinal, seed)
    minutes = 75 + 15 * _pick_int(9, family=family, ordinal=ordinal, seed=seed, label="minutes")
    material_id = 720_000 + ordinal
    source_id = f"training-cross:{ordinal:04d}:material"
    title = f"{course}·{topic}{material_kind} {ordinal + 1:04d}"
    source_group = f"codex-cross:{ordinal:04d}"
    request_templates = (
        "找到《{title}》并核对内容，然后收藏它；再为“{topic}”建立每周 {minutes} 分钟计划。"
        "完成后引用资料并确认两项状态。",
        "我准备做{context}。请阅读《{title}》，将其加入收藏，并创建每周 {minutes} 分钟的{topic}计划。",
        "请把资料核验、收藏和计划更新组合完成：目标资料是《{title}》，计划主题为{topic}，每周 {minutes} 分钟。",
        "先确认《{title}》确实覆盖{topic}，再保存资料并更新学习计划；最终答复要带资料引用和状态。",
        "为{course}建立一条可执行流程：读《{title}》、收藏它、安排每周 {minutes} 分钟，并简要确认。",
        "我想从“{activity}”开始学习{topic}。请核对《{title}》后完成收藏与周计划更新，并引用依据。",
        "请完成跨工具任务：验证《{title}》，收藏材料，再把{topic}写入每周 {minutes} 分钟的计划。",
    )
    template = request_templates[
        _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
    ]
    request = template.format(
        title=title,
        topic=topic,
        minutes=minutes,
        context=context,
        course=course,
        activity=activity,
    )
    final = f"已收藏《{title}》，并建立每周 {minutes} 分钟的“{topic}”计划。[{source_id}]"
    plan_postcondition = f"plan:{ordinal:04d}:updated"
    bookmark_postcondition = f"bookmark:{material_id}:added"
    routes = [
        _route(
            "study_plan_update",
            {"topic": topic, "weekly_minutes": minutes, "resource_ids": [material_id]},
            {
                "postcondition": plan_postcondition,
                "weekly_minutes": minutes,
                "resource_ids": [material_id],
            },
            flexible_fields=["topic"],
        ),
        _route(
            "material_bookmark_add",
            {"material_id": material_id},
            {"postcondition": bookmark_postcondition, "material_id": material_id},
        ),
    ]
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=[
                "knowledge_search",
                "knowledge_read",
                "study_plan_update",
                "material_bookmark_add",
            ],
            source_group_id=source_group,
            minimum_citations=1,
            minimum_state_changes=2,
            max_steps=9,
            max_tool_calls=7,
        ),
        environment={
            "tools": _tools(
                [
                    "knowledge_search",
                    "knowledge_read",
                    "study_plan_update",
                    "material_bookmark_add",
                ]
            ),
            "documents": [
                {
                    "source_id": source_id,
                    "material_id": material_id,
                    "title": title,
                    "text": f"该{material_kind}围绕{topic}，建议{activity}，适合{context}；资料编号 {material_id}。",
                }
            ],
        },
        fixture={"routes": routes},
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[[title], [str(minutes)]],
            allowed_citations=[source_id],
            minimum_citations=1,
            markers=[plan_postcondition, bookmark_postcondition],
            tool_groups=[
                ["knowledge_read"],
                ["study_plan_update"],
                ["material_bookmark_add"],
            ],
        ),
        audit_actions=[
            ("knowledge_search", {"query": title, "limit": 5}),
            ("knowledge_read", {"source_id": source_id}),
            ("material_bookmark_add", {"material_id": material_id}),
            (
                "study_plan_update",
                {
                    "topic": topic,
                    "weekly_minutes": minutes,
                    "resource_ids": [material_id],
                },
            ),
        ],
        audit_final=final,
    )


def _recovery(ordinal: int, seed: int) -> Scenario:
    family = "recovery_acl_provider_error"
    task_id = _stable_id(family, ordinal, seed)
    course, topic, activity, material_kind, context = _axes(family, ordinal, seed)
    material_id = 740_000 + ordinal
    source_id = f"training-recovery:{ordinal:04d}:public"
    title = f"{course}·{topic}公开{material_kind} {ordinal + 1:04d}"
    source_group = f"codex-recovery:{ordinal:04d}"
    documents = [
        {
            "source_id": source_id,
            "material_id": material_id,
            "title": title,
            "text": f"公开资料覆盖{topic}，建议{activity}，可作为{context}的安全替代来源。",
        }
    ]
    if ordinal % 2 == 0:
        status_marker = "provider_temporarily_unavailable"
        service = _pick(
            ("外部目录", "校际索引", "课程镜像", "联合检索", "资料同步"),
            family=family,
            ordinal=ordinal,
            seed=seed,
            label="provider-service",
        )
        request_templates = (
            "先确认{service}是否可用；若当前不可用，请在 StudyHub 公开资料中找到{course}替代材料，"
            "优先核对《{title}》并引用。",
            "如果{service}返回临时故障，不要反复重试。请改查公开的《{title}》，说明其{topic}内容并提供依据。",
            "我需要为{context}寻找{course}资料。先检查{service}，失败时安全回退到公开材料并引用读取结果。",
            "请测试{service}一次；服务不可用时，使用 StudyHub 公开来源解决问题，目标资料为《{title}》。",
        )
        template = request_templates[
            _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
        ]
        request = template.format(
            service=service,
            course=course,
            title=title,
            topic=topic,
            context=context,
        )
        tools = ["learning_profile_get", "knowledge_search", "knowledge_read"]
        fixture = {
            "routes": [
                _route(
                    "learning_profile_get",
                    {},
                    {
                        "service": service,
                        "status": "unavailable",
                        "error": status_marker,
                    },
                )
            ]
        }
        marker = status_marker
        audit_actions = [
            ("learning_profile_get", {}),
            ("knowledge_search", {"query": title, "limit": 5}),
            ("knowledge_read", {"source_id": source_id}),
        ]
        tool_groups = [["learning_profile_get"], ["knowledge_read"]]
        forbidden = []
    else:
        private_source = f"training-private:{ordinal:04d}"
        private_marker = f"PRIVATE-PAYLOAD-{ordinal:04d}"
        request_templates = (
            "检查我保存的来源 {private_source} 是否可读；如果权限不足，不要猜内容，改用《{title}》并引用公开资料。",
            "请尝试访问 {private_source}。若收到权限拒绝，保持隐私边界并查找公开的《{title}》作为{context}替代。",
            "我不确定 {private_source} 的访问权限。请只检查一次；不可读时转向《{title}》，说明{topic}并引用。",
            "处理这个受限来源：{private_source}。禁止推测私有内容，权限不足就使用公开的《{title}》完成回答。",
        )
        template = request_templates[
            _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
        ]
        request = template.format(
            private_source=private_source,
            title=title,
            context=context,
            topic=topic,
        )
        tools = ["knowledge_search", "knowledge_read"]
        fixture = {
            "routes": [
                _route(
                    "knowledge_read",
                    {"source_id": private_source},
                    {
                        "ok": False,
                        "error": "permission_denied",
                        "source_id": private_source,
                    },
                )
            ]
        }
        marker = "permission_denied"
        audit_actions = [
            ("knowledge_read", {"source_id": private_source}),
            ("knowledge_search", {"query": title, "limit": 5}),
            ("knowledge_read", {"source_id": source_id}),
        ]
        tool_groups = [["knowledge_read"], ["knowledge_search"]]
        forbidden = [private_marker]
    final = f"外部来源当前不可用或无权读取；安全替代是《{title}》，主题为{topic}。[{source_id}]"
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=tools,
            source_group_id=source_group,
            minimum_citations=1,
            max_steps=8,
            max_tool_calls=6,
        ),
        environment={"tools": _tools(tools), "documents": documents},
        fixture=fixture,
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[[topic]],
            allowed_citations=[source_id],
            minimum_citations=1,
            markers=[marker],
            tool_groups=tool_groups,
            forbidden_terms=forbidden,
        ),
        audit_actions=audit_actions,
        audit_final=final,
    )


def _stateful(ordinal: int, seed: int) -> Scenario:
    family = "stateful_function"
    task_id = _stable_id(family, ordinal, seed)
    course, topic, activity, _material_kind, context = _axes(family, ordinal, seed)
    minutes = 90 + 15 * _pick_int(11, family=family, ordinal=ordinal, seed=seed, label="minutes")
    score = 55 + _pick_int(40, family=family, ordinal=ordinal, seed=seed, label="score")
    resource_id = 760_000 + ordinal
    source_group = f"codex-state:{ordinal:04d}"
    plan_marker = f"state-plan:{ordinal:04d}:updated"
    progress_marker = f"state-progress:{ordinal:04d}:recorded"
    request_templates = (
        "读取我的当前学习档案，然后为{course}的“{topic}”建立每周 {minutes} 分钟计划，"
        "关联资料 {resource_id}，并记录 review、分数 {score}。",
        "请先查看学习档案，再完成两项更新：把{topic}加入每周 {minutes} 分钟计划并关联 {resource_id}；"
        "进度记为 review/{score}。",
        "为{context}更新状态。核对当前档案后创建{topic}计划（每周 {minutes} 分钟、资源 {resource_id}），"
        "再写入复习分数 {score}。",
        "我刚完成{topic}练习。请读取档案，保存每周 {minutes} 分钟的新计划和资源 {resource_id}，"
        "并记录 review 状态与 {score} 分。",
        "按“{activity}”推进{course}：先获取档案，再更新{topic}学习计划和进度；最终确认分钟数、资料号和分数。",
        "请执行一次 read-modify-write：读取个人档案，为{topic}设置每周 {minutes} 分钟并关联 {resource_id}，"
        "随后记录 review/{score}。",
    )
    template = request_templates[
        _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
    ]
    request = template.format(
        course=course,
        topic=topic,
        minutes=minutes,
        resource_id=resource_id,
        score=score,
        context=context,
        activity=activity,
    )
    final = f"已为“{topic}”建立每周 {minutes} 分钟计划并关联资料 {resource_id}，同时记录 review 状态和分数 {score}。"
    routes = [
        _route(
            "learning_profile_get",
            {},
            {
                "profile_scope": "current_user",
                "course": course,
                "postcondition": "profile_loaded",
            },
        ),
        _route(
            "study_plan_update",
            {
                "topic": topic,
                "weekly_minutes": minutes,
                "resource_ids": [resource_id],
            },
            {
                "postcondition": plan_marker,
                "weekly_minutes": minutes,
                "resource_ids": [resource_id],
            },
            flexible_fields=["topic"],
        ),
        _route(
            "learning_progress_record",
            {"topic": topic, "status": "review", "score": score},
            {"postcondition": progress_marker, "status": "review", "score": score},
            flexible_fields=["topic"],
        ),
    ]
    tools = ["learning_profile_get", "study_plan_update", "learning_progress_record"]
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=tools,
            source_group_id=source_group,
            minimum_state_changes=2,
            max_steps=7,
            max_tool_calls=5,
        ),
        environment={"tools": _tools(tools), "documents": []},
        fixture={"routes": routes},
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[
                [topic],
                [str(minutes)],
                [str(resource_id)],
                ["review", "复习"],
                [str(score)],
            ],
            markers=[plan_marker, progress_marker],
            tool_groups=[
                ["learning_profile_get"],
                ["study_plan_update"],
                ["learning_progress_record"],
            ],
        ),
        audit_actions=[
            ("learning_profile_get", {}),
            (
                "study_plan_update",
                {
                    "topic": topic,
                    "weekly_minutes": minutes,
                    "resource_ids": [resource_id],
                },
            ),
            (
                "learning_progress_record",
                {"topic": topic, "status": "review", "score": score},
            ),
        ],
        audit_final=final,
    )


def _direct(ordinal: int, seed: int) -> Scenario:
    family = "direct_abstention"
    task_id = _stable_id(family, ordinal, seed)
    course, topic, activity, _material_kind, context = _axes(family, ordinal, seed)
    sessions = 2 + _pick_int(11, family=family, ordinal=ordinal, seed=seed, label="sessions")
    minutes = 20 + 5 * _pick_int(25, family=family, ordinal=ordinal, seed=seed, label="minutes")
    weeks = 1 + _pick_int(16, family=family, ordinal=ordinal, seed=seed, label="weeks")
    total = sessions * minutes * weeks
    source_group = f"codex-direct:{ordinal:04d}"
    request_templates = (
        "未来 {weeks} 周，我会在{context}中复习{course}的{topic}：每周 {sessions} 次、每次 {minutes} 分钟。"
        "总共多少分钟？",
        "我为{course}的{topic}安排了 {weeks} 周{context}计划：每周 {sessions} 个学习时段，"
        "每段 {minutes} 分钟。请直接算总分钟数。",
        "{context}期间，我复习{course}的{topic}共 {weeks} 周，每周 {sessions} 次、每次 {minutes} 分钟。"
        "总投入是多少分钟？",
        "为了在{context}中学习{course}的{topic}，我计划连续 {weeks} 周，每周 {sessions} 次，"
        "每次 {minutes} 分钟。请计算累计时长。",
        "按“{activity}”执行{course}的{topic}复习：{weeks} 周内每周 {sessions} 次，每次 {minutes} 分钟。总计多少分钟？",
        "不用查询资料也能完成：按“{activity}”学习{course}的{topic}，共 {weeks} 周、每周 {sessions} 次、"
        "每次 {minutes} 分钟，累计多久？",
    )
    template = request_templates[
        _pick_int(len(request_templates), family=family, ordinal=ordinal, seed=seed, label="request-template")
    ]
    request = template.format(
        weeks=weeks,
        sessions=sessions,
        minutes=minutes,
        course=course,
        context=context,
        topic=topic,
        activity=activity,
    )
    final = f"总复习时间是 {weeks} × {sessions} × {minutes} = {total} 分钟。"
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=[],
            source_group_id=source_group,
            max_steps=2,
            max_tool_calls=1,
        ),
        environment={"tools": [], "documents": []},
        fixture={"routes": []},
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[[str(total)], ["分钟"]],
            require_no_tools=True,
        ),
        audit_actions=[],
        audit_final=final,
    )


BUILDERS = {
    "rag_query_rewrite_citation": _rag,
    "web_source_conflict_freshness": _web,
    "memory_personalization_privacy": _memory,
    "cross_tool_composition": _cross_tool,
    "recovery_acl_provider_error": _recovery,
    "stateful_function": _stateful,
    "direct_abstention": _direct,
}


async def _audit_scenario(root: Path, scenario: Scenario) -> tuple[list[str], dict[str, Any]]:
    task = scenario.task
    environment = FrozenTaskEnvironment.from_root(root, task["task_id"], max_tool_calls=task["max_tool_calls"])
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "training environment executability audit"},
        {"role": "user", "content": task["user_request"]},
    ]
    for index, (name, arguments) in enumerate(scenario.audit_actions):
        call_id = f"audit_{index}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                ],
            }
        )
        observation = await environment.execute(name, arguments)
        messages.append(
            {
                "role": "tool",
                "name": name,
                "tool_call_id": call_id,
                "content": observation,
            }
        )
    messages.append({"role": "assistant", "content": scenario.audit_final})
    run = {
        "status": "COMPLETED",
        "final_answer": scenario.audit_final,
        "messages": messages,
        "controller": {
            "hermes_registry_dispatch": True,
            "controller_errors": [],
            "environment_errors": environment.trace.error_codes,
            "runtime_errors": environment.trace.runtime_errors,
            "invalid_tool_calls": environment.trace.invalid_tool_calls,
            "tool_calls": len(environment.trace.tool_calls),
            "read_source_ids": sorted(environment.trace.read_source_ids),
            "policy_corrections": [],
        },
        "provider_events": [],
    }
    return verify_run(run, task, scenario.verifier)


def _public_benchmark_prompts() -> list[str]:
    manifest = json.loads((PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json").read_text(encoding="utf-8"))
    prompts: list[str] = []
    for relative in sorted(manifest["public_files"]):
        if not relative.endswith("tasks.jsonl"):
            continue
        path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2" / relative
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            prompts.append(str(row.get("user_request") or row.get("request") or ""))
    return prompts


def _token_set(value: str) -> set[str]:
    return set(normalized_text(value).split())


def _jaccard(left: str, right: str) -> float:
    a = _token_set(left)
    b = _token_set(right)
    return len(a & b) / max(len(a | b), 1)


def _prompt_shape(value: str) -> str:
    return re.sub(r"\d+", "<number>", normalized_text(value))


def build(
    root: Path,
    *,
    total_tasks: int,
    seed: int,
    force: bool,
    ordinal_offset: int = 0,
) -> dict[str, Any]:
    if total_tasks < len(FAMILY_WEIGHTS):
        raise ValueError(f"--total-tasks must be at least {len(FAMILY_WEIGHTS)}")
    if ordinal_offset < 0:
        raise ValueError("--ordinal-offset must be nonnegative")
    if root.exists() and any((root / "raw_runs").glob("*.json")):
        raise RuntimeError("refusing to rebuild a root that already contains raw teacher runs")
    if root.exists() and not force:
        raise FileExistsError(f"output root exists; pass --force after checking it: {root}")
    if root.exists():
        shutil.rmtree(root)
    for name in ("environments", "fixtures", "verifiers", "raw_runs"):
        (root / name).mkdir(parents=True, exist_ok=True)

    counts = _allocate(total_tasks)
    scenarios: list[Scenario] = []
    for family, count in counts.items():
        scenarios.extend(BUILDERS[family](ordinal, seed) for ordinal in range(ordinal_offset, ordinal_offset + count))
    if len({row.task["task_id"] for row in scenarios}) != total_tasks:
        raise RuntimeError("task IDs are not unique")

    # Environments and hidden verifiers exist before public task specs are emitted.
    for scenario in scenarios:
        task_id = scenario.task["task_id"]
        _write_json(root / "environments" / f"{task_id}.json", scenario.environment)
        _write_json(root / "fixtures" / f"{task_id}.json", scenario.fixture)
        _write_json(root / "verifiers" / f"{task_id}.json", scenario.verifier)

    audit_failures: dict[str, list[str]] = {}
    for scenario in scenarios:
        failures, _diagnostics = asyncio.run(_audit_scenario(root, scenario))
        if failures:
            audit_failures[scenario.task["task_id"]] = failures
    if audit_failures:
        raise RuntimeError(f"training environment/verifier executability failed: {audit_failures}")

    tasks = sorted((scenario.task for scenario in scenarios), key=lambda row: row["task_id"])
    benchmark_manifest = json.loads(
        (PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json").read_text(encoding="utf-8")
    )
    benchmark_hashes, benchmark_rows = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark_manifest)
    prompt_hashes = [hashlib.sha256(normalized_text(row["user_request"]).encode()).hexdigest() for row in tasks]
    exact_overlap = sum(value in benchmark_hashes for value in prompt_hashes)
    public_prompts = _public_benchmark_prompts()
    maximum_near_overlap = max(
        (_jaccard(task["user_request"], benchmark) for task in tasks for benchmark in public_prompts),
        default=0.0,
    )
    if exact_overlap:
        raise RuntimeError(f"public benchmark prompt overlap detected: {exact_overlap}")
    if maximum_near_overlap >= 0.80:
        raise RuntimeError(f"near benchmark prompt overlap is too high: {maximum_near_overlap:.6f}")

    shape_counts: dict[str, dict[str, float | int]] = {}
    for family in sorted(FAMILY_WEIGHTS):
        requests = [row["user_request"] for row in tasks if row["family"] == family]
        shapes = [_prompt_shape(value) for value in requests]
        counts_by_shape: dict[str, int] = {}
        for shape in shapes:
            counts_by_shape[shape] = counts_by_shape.get(shape, 0) + 1
        unique = len(counts_by_shape)
        ratio = unique / max(len(shapes), 1)
        largest_share = max(counts_by_shape.values(), default=0) / max(len(shapes), 1)
        shape_counts[family] = {
            "rows": len(shapes),
            "digit_normalized_unique_shapes": unique,
            "digit_normalized_unique_ratio": round(ratio, 6),
            "largest_digit_normalized_shape_share": round(largest_share, 6),
        }
        if len(shapes) >= 20 and ratio < 0.75:
            raise RuntimeError(f"teacher task semantic diversity is too low: family={family} ratio={ratio:.6f}")

    _write_jsonl(root / "task_specs.jsonl", tasks)
    provenance = {
        "schema_version": "studyhub.codex-hermes-source-provenance.v1",
        "dataset_id": DATASET_ID,
        "task_design_revision": TASK_DESIGN_REVISION,
        "source": "independent deterministic training simulator",
        "license": "StudyHub-generated-training-simulator-v1",
        "revision": SCHEMA_VERSION,
        "construction": "environment_first_then_public_task",
        "reverse_replay_used": False,
        "benchmark_tasks_used_as_training_sources": False,
        "fresh_external_holdouts_opened": False,
        "hidden_verifier_visible_to_teacher": False,
    }
    _write_json(root / "source_provenance.json", provenance)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": ("PASS_READY_FOR_CODEX_PILOT" if total_tasks == 50 else "PASS_READY_FOR_COLLECTION"),
        "dataset_id": DATASET_ID,
        "seed": seed,
        "ordinal_offset": ordinal_offset,
        "ordinal_range_by_family": {
            family: [ordinal_offset, ordinal_offset + count - 1] for family, count in counts.items()
        },
        "tasks": total_tasks,
        "family_counts": counts,
        "environment_executable": total_tasks,
        "environment_executable_rate": 1.0,
        "path_agnostic_verifier": total_tasks,
        "exact_public_benchmark_overlap": exact_overlap,
        "maximum_public_benchmark_prompt_jaccard": round(maximum_near_overlap, 6),
        "public_benchmark_prompts_hashed_for_audit": benchmark_rows,
        "sealed_or_fresh_external_holdouts_opened": False,
        "legacy_reverse_replay_used": False,
        "source_groups": len({row["metadata"]["source_group_id"] for row in tasks}),
        "prompt_shape_audit": shape_counts,
        "task_specs_sha256": sha256(root / "task_specs.jsonl"),
        "source_provenance_sha256": sha256(root / "source_provenance.json"),
    }
    _write_json(root / "task-specs.manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/codex_hermes_teacher_v1",
    )
    parser.add_argument("--total-tasks", type=int, default=50)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--ordinal-offset", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            build(
                args.root,
                total_tasks=args.total_tasks,
                seed=args.seed,
                force=args.force,
                ordinal_offset=args.ordinal_offset,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
