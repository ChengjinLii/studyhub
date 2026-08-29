#!/usr/bin/env python3
"""Audit Open-Agentic prompts for cross-group semantic near duplicates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPACE = re.compile(r"\s+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip().casefold()


def first_user(row: dict[str, Any]) -> str:
    return next(
        (str(message.get("content", "")) for message in row.get("messages", []) if message.get("role") == "user"),
        "",
    )


def tool_schema_summary(row: dict[str, Any]) -> str:
    summaries = []
    for tool in row.get("tools", []):
        function = tool.get("function", tool) if isinstance(tool, dict) else {}
        if not isinstance(function, dict):
            continue
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
        required = parameters.get("required", []) if isinstance(parameters, dict) else []
        summaries.append(
            ":".join(
                (
                    str(function.get("name", "unknown")),
                    ",".join(sorted(map(str, properties))) if isinstance(properties, dict) else "",
                    ",".join(sorted(map(str, required))) if isinstance(required, list) else "",
                )
            )
        )
    return ";".join(sorted(set(summaries)))


def semantic_task_text(row: dict[str, Any]) -> str:
    user = first_user(row)
    schema = tool_schema_summary(row)
    path = str(row.get("tool_path_signature", ""))
    if not schema and not path:
        return user
    return f"{user}\nexecuted path: {path}\navailable tool schemas: {schema}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.jsonl",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_ROOT.parent / "models/P0/bge-m3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs/training/evidence/open-agentic-sft-v2-semantic-dedup.json",
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--neighbors", type=int, default=192)
    parser.add_argument("--review-threshold", type=float, default=0.985)
    parser.add_argument("--hard-threshold", type=float, default=0.995)
    parser.add_argument("--blocklist-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.0 < args.review_threshold < args.hard_threshold <= 1.0:
        raise ValueError("semantic thresholds must satisfy 0 < review < hard <= 1")

    import torch
    from transformers import AutoModel, AutoTokenizer

    rows = []
    texts = []
    with args.input.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            text = normalized_text(semantic_task_text(row))
            if not text:
                raise RuntimeError(f"selected row has no user task: {row.get('id')}")
            rows.append(
                {
                    "id": str(row["id"]),
                    "group_id": str(row["group_id"]),
                    "source": str(row["source_dataset"]),
                    "source_family": str(row["source_family"]),
                    "split": str(row["split"]),
                    "quality_tier": str(row.get("policy_quality_tier", "C")),
                    "text": text,
                }
            )
            texts.append(text)

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA semantic audit requested but CUDA is unavailable")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        trust_remote_code=True,
        local_files_only=True,
    )
    model = AutoModel.from_pretrained(
        args.model,
        trust_remote_code=True,
        local_files_only=True,
        dtype=torch.bfloat16 if device.type == "cuda" else torch.float32,
    ).to(device)
    model.eval()

    vectors = []
    with torch.inference_mode():
        for start in range(0, len(texts), args.batch_size):
            encoded = tokenizer(
                texts[start : start + args.batch_size],
                padding=True,
                truncation=True,
                max_length=args.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            hidden = model(**encoded).last_hidden_state[:, 0].float()
            vectors.append(torch.nn.functional.normalize(hidden, p=2, dim=1).cpu())
    embeddings = torch.cat(vectors, dim=0).to(device)

    seen_pairs: set[tuple[int, int]] = set()
    review_pairs = []
    hard_pairs = []
    hard_edges: list[tuple[int, int, float]] = []
    same_group_pairs = 0
    neighbor_count = min(args.neighbors + 1, len(rows))
    with torch.inference_mode():
        for start in range(0, len(rows), 512):
            similarities = embeddings[start : start + 512] @ embeddings.T
            scores, indices = torch.topk(similarities, k=neighbor_count, dim=1)
            for local_index, (row_scores, row_indices) in enumerate(zip(scores, indices, strict=True)):
                left = start + local_index
                for score_tensor, right_tensor in zip(row_scores, row_indices, strict=True):
                    right = int(right_tensor)
                    if left == right:
                        continue
                    pair = (min(left, right), max(left, right))
                    if pair in seen_pairs:
                        continue
                    score = float(score_tensor)
                    if score < args.review_threshold:
                        continue
                    seen_pairs.add(pair)
                    same_group = rows[left]["group_id"] == rows[right]["group_id"]
                    if same_group:
                        same_group_pairs += 1
                    payload = {
                        "similarity": round(score, 8),
                        "same_group": same_group,
                        "left": {key: rows[left][key] for key in ("id", "group_id", "source", "split")},
                        "right": {key: rows[right][key] for key in ("id", "group_id", "source", "split")},
                        "left_excerpt": rows[left]["text"][:240],
                        "right_excerpt": rows[right]["text"][:240],
                    }
                    if score >= args.hard_threshold and not same_group:
                        hard_edges.append((pair[0], pair[1], score))
                        if len(hard_pairs) < 250:
                            hard_pairs.append(payload)
                    elif len(review_pairs) < 250:
                        review_pairs.append(payload)

    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for left, right, _score in hard_edges:
        union(left, right)
    components: dict[int, set[int]] = {}
    for left, right, _score in hard_edges:
        root = find(left)
        components.setdefault(root, set()).update((left, right))

    quality_rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    blocked = []
    for members in components.values():
        representative = min(
            members,
            key=lambda index: (
                quality_rank.get(rows[index]["quality_tier"], 9),
                rows[index]["id"],
            ),
        )
        component_id = hashlib.sha256("\n".join(sorted(rows[index]["id"] for index in members)).encode()).hexdigest()[
            :20
        ]
        for index in sorted(members - {representative}, key=lambda value: rows[value]["id"]):
            blocked.append(
                {
                    "blocked_id": rows[index]["id"],
                    "kept_id": rows[representative]["id"],
                    "component_id": component_id,
                    "blocked_source": rows[index]["source"],
                    "kept_source": rows[representative]["source"],
                    "blocked_quality_tier": rows[index]["quality_tier"],
                    "kept_quality_tier": rows[representative]["quality_tier"],
                }
            )

    blocklist = None
    if args.blocklist_output is not None:
        args.blocklist_output.parent.mkdir(parents=True, exist_ok=True)
        temporary_blocklist = args.blocklist_output.with_suffix(args.blocklist_output.suffix + ".partial")
        with temporary_blocklist.open("w", encoding="utf-8") as stream:
            for row in blocked:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary_blocklist, args.blocklist_output)
        blocklist = {
            "path": str(args.blocklist_output.resolve()),
            "sha256": sha256(args.blocklist_output),
            "rows": len(blocked),
        }

    if hard_edges and blocklist is None:
        status = "FAIL"
    elif hard_edges:
        status = "PASS_WITH_SEMANTIC_BLOCKLIST"
    else:
        status = "PASS"
    evidence = {
        "schema_version": "studyhub.open-agentic-semantic-dedup.v1",
        "status": status,
        "contract": {
            "embedding": "BAAI/bge-m3 CLS normalized cosine",
            "max_length": args.max_length,
            "neighbors": args.neighbors,
            "review_threshold": args.review_threshold,
            "hard_cross_group_threshold": args.hard_threshold,
            "same_group_pairs_are_reported_not_failed": True,
        },
        "rows": len(rows),
        "pairs_at_or_above_review_threshold": len(seen_pairs),
        "same_group_pairs": same_group_pairs,
        "hard_cross_group_pairs": len(hard_edges),
        "semantic_components": len(components),
        "blocked_rows": len(blocked),
        "blocklist": blocklist,
        "hard_pairs": hard_pairs,
        "review_pairs": review_pairs,
        "lineage": {
            "input_path": str(args.input.resolve()),
            "input_sha256": sha256(args.input),
            "model_config_sha256": sha256(args.model / "config.json"),
            "model_weights_sha256": sha256(args.model / "pytorch_model.bin"),
        },
        "scope": {
            "sealed_content_read": False,
            "benchmark_tasks_embedded": False,
            "model_quality": "NOT_EVALUATED",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({key: evidence[key] for key in ("status", "rows", "hard_cross_group_pairs")}, indent=2))
    return 0 if status in {"PASS", "PASS_WITH_SEMANTIC_BLOCKLIST"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
