#!/usr/bin/env python3
"""Normalize licensed open datasets into auditable chat candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any


TRANSFORM_VERSION = "open-sft-bootstrap-v2"
POOL_LIMITS = {
    "toolace": 1200,
    "hermes_function_calling": 1200,
    "2wiki": 2500,
    "qasper": 1500,
    "coig_exam": 2500,
}


def stable_key(value: str) -> str:
    return hashlib.sha256(("studyhub-open-sft-v1:" + value).encode()).hexdigest()


def clean(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def provenance(source: dict[str, Any], source_id: str) -> dict[str, Any]:
    return {
        "source_dataset": source["id"],
        "source_id": source_id,
        "license": source["license"],
        "revision": source["revision"],
        "source_url": source["source_url"],
        "raw_sha256": next((value for value in source["files"].values() if value), None),
        "attribution": source["attribution"],
        "transform_version": TRANSFORM_VERSION,
    }


def candidate(
    source: dict[str, Any],
    source_id: str,
    task_family: str,
    messages: list[dict[str, str]],
    *,
    group_id: str | None = None,
) -> dict[str, Any] | None:
    normalized = []
    for message in messages:
        role = message["role"]
        content = clean(message["content"])
        if not content or role not in {"system", "user", "assistant", "tool"}:
            return None
        normalized.append({"role": role, "content": content})
    if not normalized or not any(item["role"] == "assistant" for item in normalized):
        return None
    if sum(len(item["content"]) for item in normalized) > 18_000:
        return None
    meta = provenance(source, source_id)
    return {
        "id": f"{source['id']}:{source_id}",
        "group_id": group_id or source_id,
        "task_family": task_family,
        "messages": normalized,
        **meta,
    }


def complete_prefix(messages: list[dict[str, str]], max_chars: int = 14_000) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    total = 0
    last_assistant = -1
    for message in messages:
        size = len(message["content"])
        if selected and total + size > max_chars:
            break
        selected.append(message)
        total += size
        if message["role"] == "assistant":
            last_assistant = len(selected)
    return selected[:last_assistant]


def iter_toolace(root: Path, source: dict[str, Any]) -> Iterable[dict[str, Any]]:
    rows = json.loads((root / "toolace/data.json").read_text(encoding="utf-8"))
    role_map = {"user": "user", "assistant": "assistant", "tool": "tool"}
    for index, row in enumerate(rows):
        messages = [{"role": "system", "content": row["system"]}]
        for item in row.get("conversations", []):
            role = role_map.get(item.get("from"))
            if role:
                messages.append({"role": role, "content": item.get("value", "")})
        record = candidate(
            source,
            str(index),
            "tool_protocol",
            complete_prefix(messages),
        )
        if record:
            yield record


def iter_hermes(root: Path, source: dict[str, Any]) -> Iterable[dict[str, Any]]:
    role_map = {"system": "system", "human": "user", "gpt": "assistant", "tool": "tool"}
    files = [
        ("func-calling.json", "tool_protocol"),
        ("json-mode-agentic.json", "structured_output"),
    ]
    for filename, family in files:
        rows = json.loads((root / "hermes_function_calling" / filename).read_text(encoding="utf-8"))
        for index, row in enumerate(rows):
            messages = []
            for item in row.get("conversations", []):
                role = role_map.get(item.get("from"))
                if role:
                    messages.append({"role": role, "content": item.get("value", "")})
            source_id = f"{filename}:{row.get('id', index)}"
            record = candidate(source, source_id, family, complete_prefix(messages))
            if record:
                yield record


def iter_2wiki(root: Path, source: dict[str, Any]) -> Iterable[dict[str, Any]]:
    import pyarrow.parquet as pq

    columns = ["_id", "question", "context", "supporting_facts", "evidences", "answer"]
    table = pq.read_table(root / "2wiki/train.parquet", columns=columns)
    system = (
        "Answer using only the numbered evidence. Give a concise answer and cite the "
        "supporting evidence numbers. If the evidence is insufficient, say so."
    )
    for row in table.to_pylist():
        contexts = {title: sentences for title, sentences in json.loads(row["context"])}
        supporting = json.loads(row["supporting_facts"])
        evidence_lines = []
        seen = set()
        for title, sentence_index in supporting:
            key = (title, sentence_index)
            sentences = contexts.get(title, [])
            if key in seen or not (0 <= sentence_index < len(sentences)):
                continue
            seen.add(key)
            evidence_lines.append(f"[{len(evidence_lines) + 1}] {title}: {sentences[sentence_index]}")
        if not evidence_lines:
            continue
        triples = json.loads(row["evidences"] or "[]")
        support_summary = "; ".join(" — ".join(map(str, triple)) for triple in triples[:4])
        response = f"Answer: {clean(row['answer'])}\nEvidence: {support_summary or 'see the cited facts above'}"
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Evidence:\n" + "\n".join(evidence_lines[:8]) + "\n\nQuestion: " + row["question"],
            },
            {"role": "assistant", "content": response},
        ]
        record = candidate(source, row["_id"], "grounded_multihop_qa", messages)
        if record:
            yield record


def qasper_answer(answer: dict[str, Any]) -> str:
    if answer.get("unanswerable"):
        return "The provided evidence is insufficient to answer the question."
    if answer.get("free_form_answer"):
        return clean(answer["free_form_answer"])
    if answer.get("extractive_spans"):
        return "; ".join(map(clean, answer["extractive_spans"]))
    if answer.get("yes_no") is not None:
        return "Yes." if answer["yes_no"] else "No."
    return ""


def iter_qasper(root: Path, source: dict[str, Any]) -> Iterable[dict[str, Any]]:
    system = (
        "Answer the research question using only the supplied paper evidence. "
        "Cite evidence numbers and explicitly report insufficient evidence."
    )
    for split in ("train", "dev"):
        papers = json.loads((root / f"qasper/qasper-{split}-v0.3.json").read_text(encoding="utf-8"))
        for paper_id, paper in papers.items():
            for qa in paper.get("qas", []):
                answers = [entry.get("answer", {}) for entry in qa.get("answers", [])]
                answer = next((item for item in answers if qasper_answer(item)), None)
                if answer is None:
                    continue
                evidence = [clean(item) for item in answer.get("evidence", []) if clean(item)]
                if not evidence:
                    evidence = [clean(paper.get("abstract", ""))]
                evidence = [item[:1800] for item in evidence if item][:3]
                if not evidence:
                    continue
                numbered = "\n".join(f"[{i + 1}] {item}" for i, item in enumerate(evidence))
                response = qasper_answer(answer)
                if not answer.get("unanswerable"):
                    response += "\nEvidence: " + ", ".join(f"[{i + 1}]" for i in range(len(evidence)))
                messages = [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": f"Paper: {paper['title']}\nEvidence:\n{numbered}\n\nQuestion: {qa['question']}",
                    },
                    {"role": "assistant", "content": response},
                ]
                source_id = f"{split}:{paper_id}:{qa['question_id']}"
                record = candidate(
                    source,
                    source_id,
                    "grounded_paper_qa",
                    messages,
                    group_id=f"{split}:{paper_id}",
                )
                if record:
                    yield record


def iter_coig(root: Path, source: dict[str, Any]) -> Iterable[dict[str, Any]]:
    path = root / "coig_exam/exam_instructions.jsonl"
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            context = clean(row.get("textbox_q_context"))
            if len(context) > 6000:
                continue
            prompt_parts = [clean(row.get("textbox_q_instruction")), context, clean(row.get("textbox_question"))]
            prompt = "\n\n".join(item for item in prompt_parts if item)
            answer = clean(row.get("textbox_answer"))
            analysis = clean(row.get("textbox_answer_analysis"))
            response = (f"解析：{analysis}\n" if analysis else "") + f"答案：{answer}"
            messages = [
                {
                    "role": "system",
                    "content": "你是学习辅导助手。请依据题目和材料给出清晰、准确的讲解，不编造缺失条件。",
                },
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ]
            record = candidate(source, str(index), "chinese_tutoring", messages)
            if record:
                yield record


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=project / "data_registry/open_sft_sources.json")
    parser.add_argument("--raw-root", type=Path, default=project / "datasets/raw/open_source")
    parser.add_argument(
        "--output", type=Path, default=project / "datasets/interim/open_sft_bootstrap_v2/candidates.jsonl"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    sources = {item["id"]: item for item in registry["sources"]}
    loaders = {
        "toolace": iter_toolace,
        "hermes_function_calling": iter_hermes,
        "2wiki": iter_2wiki,
        "qasper": iter_qasper,
        "coig_exam": iter_coig,
    }
    selected: list[dict[str, Any]] = []
    seen = set()
    counts = {}
    for source_id, loader in loaders.items():
        pool = sorted(loader(args.raw_root, sources[source_id]), key=lambda row: stable_key(row["id"]))
        source_rows = []
        for row in pool:
            first_user = next(item["content"] for item in row["messages"] if item["role"] == "user")
            final_answer = next(item["content"] for item in reversed(row["messages"]) if item["role"] == "assistant")
            fingerprint = hashlib.sha256((clean(first_user).lower() + "\n" + clean(final_answer).lower()).encode()).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            row["content_sha256"] = fingerprint
            source_rows.append(row)
            if len(source_rows) == POOL_LIMITS[source_id]:
                break
        if len(source_rows) < POOL_LIMITS[source_id]:
            raise RuntimeError(f"Insufficient {source_id} candidates: {len(source_rows)}")
        counts[source_id] = len(source_rows)
        selected.extend(source_rows)

    selected.sort(key=lambda row: stable_key(row["id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "schema_version": "studyhub.open-sft-candidate-manifest.v2",
        "transform_version": TRANSFORM_VERSION,
        "total": len(selected),
        "source_counts": counts,
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
