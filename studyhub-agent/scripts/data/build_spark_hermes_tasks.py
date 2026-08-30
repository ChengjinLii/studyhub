#!/usr/bin/env python3
"""Build independent training tasks for Codex-Spark driven Hermes rollouts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
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

SCHEMA_VERSION = "studyhub.spark-hermes-training-tasks.v1"
DATASET_ID = "spark_hermes_teacher_v1"
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
    "web_fetch": "evidence_fetch",
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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _stable_id(family: str, ordinal: int, seed: int) -> str:
    digest = hashlib.sha256(f"{DATASET_ID}:{seed}:{family}:{ordinal}".encode()).hexdigest()[:18]
    return f"spark-train-{digest}"


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
    for row in tool_schemas(names):
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
        row["argument_match"] = {"mode": "exact_except", "flexible_fields": flexible_fields}
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
        "schema_version": "studyhub.spark-hermes-task.v1",
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
        "schema_version": "studyhub.spark-hermes-verifier.v1",
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
    course = COURSES[ordinal % len(COURSES)]
    topic = TOPICS[ordinal % len(TOPICS)]
    activity = ACTIVITIES[ordinal % len(ACTIVITIES)]
    minutes = 45 + 15 * (ordinal % 6)
    title = f"{course} {topic} 训练讲义 {ordinal + 1:03d}"
    source_id = f"training-rag:{ordinal:04d}:primary"
    documents = [
        {
            "source_id": source_id,
            "title": title,
            "text": (
                f"课程：{course}。主题：{topic}。本讲义建议的首个复习动作是“{activity}”，"
                f"每周安排 {minutes} 分钟。训练版本标记 RAG-{ordinal:04d}。"
            ),
        }
    ]
    for offset in range(1, 4):
        other = (ordinal + offset) % len(COURSES)
        documents.append(
            {
                "source_id": f"training-rag:{ordinal:04d}:distractor-{offset}",
                "title": f"{COURSES[other]} 辅助资料 {ordinal + offset:03d}",
                "text": f"该资料讨论 {TOPICS[other]}，建议活动为 {ACTIVITIES[other]}。",
            }
        )
    source_group = f"spark-rag:{ordinal:04d}"
    request = f"请在 StudyHub 训练资料中找到《{title}》，说明首个复习动作和每周分钟数，并引用读到的资料。"
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
        environment={"tools": _tools(["knowledge_search", "knowledge_read"]), "documents": documents},
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
    course = COURSES[ordinal % len(COURSES)]
    date = f"2026-{(ordinal % 9) + 1:02d}-{(ordinal % 24) + 1:02d}"
    room = f"A{200 + ordinal % 70}"
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
                "title": f"{course} 教务处最新通知",
                "snippet": "官方更新页",
            },
            {
                "url": stale_url,
                "source_id": stale_source,
                "title": f"{course} 历史转载",
                "snippet": "旧版转载，可能过期",
            },
        ],
    }
    official_page = {
        "source_id": official_source,
        "citation": f"[{official_source}]",
        "title": f"{course} 教务处最新通知",
        "published_at": "2026-08-20",
        "text": f"{course} 答疑安排确认于 {date}，地点为 {room}。这是当前有效通知。",
    }
    stale_page = {
        "source_id": stale_source,
        "citation": f"[{stale_source}]",
        "title": f"{course} 历史转载",
        "published_at": "2025-08-20",
        "text": "旧安排为 2025-09-01，地点 B101；页面标注已过期。",
    }
    source_group = f"spark-web:{ordinal:04d}"
    request = f"请查证 {course} 当前有效的答疑日期和地点。优先使用最新的官方来源并附引用。"
    final = f"{course} 当前答疑日期是 {date}，地点 {room}。[{official_source}]"
    fixtures = {
        "routes": [
            _route("web_search", {"query": f"{course} 答疑", "limit": 5}, search_result),
            _route("web_fetch", {"url": official_url}, official_page),
            _route("web_fetch", {"url": stale_url}, stale_page),
        ]
    }
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=["web_search", "web_fetch"],
            source_group_id=source_group,
            minimum_citations=1,
            max_steps=6,
            max_tool_calls=5,
        ),
        environment={"tools": _tools(["web_search", "web_fetch"]), "documents": []},
        fixture=fixtures,
        verifier=_base_verifier(
            task_id=task_id,
            family=family,
            source_group_id=source_group,
            reference_final=final,
            concept_groups=[[date], [room]],
            allowed_citations=[official_source],
            minimum_citations=1,
            tool_groups=[["web_search"], ["web_fetch"]],
            forbidden_terms=["2025-09-01", "B101"],
        ),
        audit_actions=[
            ("web_search", {"query": f"{course} 最新答疑", "limit": 5}),
            ("web_fetch", {"url": official_url}),
        ],
        audit_final=final,
    )


def _memory(ordinal: int, seed: int) -> Scenario:
    family = "memory_personalization_privacy"
    task_id = _stable_id(family, ordinal, seed)
    course = COURSES[ordinal % len(COURSES)]
    current = ACTIVITIES[ordinal % len(ACTIVITIES)]
    stale = ACTIVITIES[(ordinal + 3) % len(ACTIVITIES)]
    target_id = 700_000 + ordinal * 2
    other_id = target_id + 1
    target_source = f"training-memory:{ordinal:04d}:target"
    other_source = f"training-memory:{ordinal:04d}:other"
    target_title = f"{course} {current} 实践册"
    other_title = f"{course} {stale} 速览"
    memory_result = {
        "ok": True,
        "memories": [
            {"scope": "current_user", "preference": current, "updated_at": "2026-08-20"},
            {"scope": "current_user", "preference": stale, "updated_at": "2025-03-01", "stale": True},
        ],
        "cross_user_records": [],
    }
    source_group = f"spark-memory:{ordinal:04d}"
    request = (
        f"请根据我当前而不是过期的学习偏好，从《{target_title}》和《{other_title}》中推荐一本。"
        "先核对个人记忆和资料内容，并引用推荐资料。"
    )
    final = f"当前偏好是“{current}”，因此推荐《{target_title}》。[{target_source}]"
    return Scenario(
        task=_base_task(
            task_id=task_id,
            family=family,
            user_request=request,
            allowed_tools=["personal_memory_search", "knowledge_search", "knowledge_read"],
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
                    "text": f"这份实践册的首要使用方式是：{current}。适合 {course} 复习。",
                },
                {
                    "source_id": other_source,
                    "material_id": other_id,
                    "title": other_title,
                    "text": f"这份速览的首要使用方式是：{stale}。适合 {course} 复习。",
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
            tool_groups=[["personal_memory_search"], ["knowledge_search"], ["knowledge_read"]],
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
    course = COURSES[ordinal % len(COURSES)]
    topic = TOPICS[ordinal % len(TOPICS)]
    minutes = 90 + 15 * (ordinal % 5)
    material_id = 720_000 + ordinal
    source_id = f"training-cross:{ordinal:04d}:material"
    title = f"{course} {topic} 分步训练"
    source_group = f"spark-cross:{ordinal:04d}"
    request = (
        f"找到《{title}》并核对内容，然后收藏它；再为“{topic}”建立每周 {minutes} 分钟的学习计划。"
        "完成后引用资料并简要确认两项状态。"
    )
    final = f"已收藏《{title}》，并建立每周 {minutes} 分钟的“{topic}”计划。[{source_id}]"
    plan_postcondition = f"plan:{ordinal:04d}:updated"
    bookmark_postcondition = f"bookmark:{material_id}:added"
    routes = [
        _route(
            "study_plan_update",
            {"topic": topic, "weekly_minutes": minutes, "resource_ids": [material_id]},
            {"postcondition": plan_postcondition, "weekly_minutes": minutes, "resource_ids": [material_id]},
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
            allowed_tools=["knowledge_search", "knowledge_read", "study_plan_update", "material_bookmark_add"],
            source_group_id=source_group,
            minimum_citations=1,
            minimum_state_changes=2,
            max_steps=9,
            max_tool_calls=7,
        ),
        environment={
            "tools": _tools(["knowledge_search", "knowledge_read", "study_plan_update", "material_bookmark_add"]),
            "documents": [
                {
                    "source_id": source_id,
                    "material_id": material_id,
                    "title": title,
                    "text": f"该资料用分步练习覆盖 {topic}，资料编号 {material_id}。",
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
            tool_groups=[["knowledge_read"], ["study_plan_update"], ["material_bookmark_add"]],
        ),
        audit_actions=[
            ("knowledge_search", {"query": title, "limit": 5}),
            ("knowledge_read", {"source_id": source_id}),
            ("material_bookmark_add", {"material_id": material_id}),
            (
                "study_plan_update",
                {"topic": topic, "weekly_minutes": minutes, "resource_ids": [material_id]},
            ),
        ],
        audit_final=final,
    )


def _recovery(ordinal: int, seed: int) -> Scenario:
    family = "recovery_acl_provider_error"
    task_id = _stable_id(family, ordinal, seed)
    course = COURSES[ordinal % len(COURSES)]
    material_id = 740_000 + ordinal
    source_id = f"training-recovery:{ordinal:04d}:public"
    title = f"{course} 公开替代资料 {ordinal + 1:03d}"
    source_group = f"spark-recovery:{ordinal:04d}"
    documents = [
        {
            "source_id": source_id,
            "material_id": material_id,
            "title": title,
            "text": f"公开资料覆盖 {TOPICS[ordinal % len(TOPICS)]}，可作为安全替代来源。",
        }
    ]
    if ordinal % 2 == 0:
        status_marker = "provider_temporarily_unavailable"
        request = (
            f"先确认外部目录服务是否可用；若当前不可用，请在 StudyHub 公开资料中找到 {course} 的替代资料，"
            "说明主题并引用。"
        )
        tools = ["learning_profile_get", "knowledge_search", "knowledge_read"]
        fixture = {
            "routes": [
                _route(
                    "learning_profile_get",
                    {},
                    {"service": "external_catalog", "status": "unavailable", "error": status_marker},
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
        request = (
            f"检查我保存的来源 {private_source} 是否可读；如果权限不足，不要猜内容，改用《{title}》并引用公开资料。"
        )
        tools = ["knowledge_search", "knowledge_read"]
        fixture = {
            "routes": [
                _route(
                    "knowledge_read",
                    {"source_id": private_source},
                    {"ok": False, "error": "permission_denied", "source_id": private_source},
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
    final = (
        f"外部来源当前不可用或无权读取；安全替代是《{title}》，主题为 {TOPICS[ordinal % len(TOPICS)]}。[{source_id}]"
    )
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
            concept_groups=[[title], [TOPICS[ordinal % len(TOPICS)]]],
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
    course = COURSES[ordinal % len(COURSES)]
    topic = TOPICS[ordinal % len(TOPICS)]
    minutes = 120 + 15 * (ordinal % 5)
    score = 55 + ordinal % 35
    source_group = f"spark-state:{ordinal:04d}"
    plan_marker = f"state-plan:{ordinal:04d}:updated"
    progress_marker = f"state-progress:{ordinal:04d}:recorded"
    request = (
        f"读取我的当前学习档案，然后为 {course} 的“{topic}”建立每周 {minutes} 分钟计划，"
        f"并把该主题记录为 review、分数 {score}。完成后确认结果。"
    )
    final = f"已为“{topic}”建立每周 {minutes} 分钟计划，并记录 review 状态和分数 {score}。"
    routes = [
        _route(
            "learning_profile_get",
            {},
            {"profile_scope": "current_user", "course": course, "postcondition": "profile_loaded"},
        ),
        _route(
            "study_plan_update",
            {"topic": topic, "weekly_minutes": minutes, "resource_ids": []},
            {"postcondition": plan_marker, "weekly_minutes": minutes},
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
            concept_groups=[[topic], [str(minutes)], ["review", "复习"], [str(score)]],
            markers=[plan_marker, progress_marker],
            tool_groups=[["learning_profile_get"], ["study_plan_update"], ["learning_progress_record"]],
        ),
        audit_actions=[
            ("learning_profile_get", {}),
            ("study_plan_update", {"topic": topic, "weekly_minutes": minutes, "resource_ids": []}),
            ("learning_progress_record", {"topic": topic, "status": "review", "score": score}),
        ],
        audit_final=final,
    )


def _direct(ordinal: int, seed: int) -> Scenario:
    family = "direct_abstention"
    task_id = _stable_id(family, ordinal, seed)
    sessions = 3 + ordinal % 4
    minutes = 25 + 5 * (ordinal % 5)
    total = sessions * minutes
    source_group = f"spark-direct:{ordinal:04d}"
    request = f"我每周复习 {sessions} 次，每次 {minutes} 分钟。一周总共复习多少分钟？"
    final = f"一周总复习时间是 {sessions} × {minutes} = {total} 分钟。"
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
                "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}],
            }
        )
        observation = await environment.execute(name, arguments)
        messages.append({"role": "tool", "name": name, "tool_call_id": call_id, "content": observation})
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


def build(root: Path, *, total_tasks: int, seed: int, force: bool) -> dict[str, Any]:
    if total_tasks < len(FAMILY_WEIGHTS):
        raise ValueError(f"--total-tasks must be at least {len(FAMILY_WEIGHTS)}")
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
        scenarios.extend(BUILDERS[family](ordinal, seed) for ordinal in range(count))
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

    _write_jsonl(root / "task_specs.jsonl", tasks)
    provenance = {
        "schema_version": "studyhub.spark-hermes-source-provenance.v1",
        "dataset_id": DATASET_ID,
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
        "status": "PASS_READY_FOR_SPARK_PILOT" if total_tasks == 50 else "PASS_READY_FOR_COLLECTION",
        "dataset_id": DATASET_ID,
        "seed": seed,
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
        default=PROJECT_ROOT / "datasets/interim/spark_hermes_teacher_v1",
    )
    parser.add_argument("--total-tasks", type=int, default=50)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(build(args.root, total_tasks=args.total_tasks, seed=args.seed, force=args.force), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
