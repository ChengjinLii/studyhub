#!/usr/bin/env python3
"""Fail closed unless Qwen3.5 4B-Base and 9B have canonical OPD tokenizer parity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.data.tokenize_runtime_sft_v3 import assistant_loss_mask

CONTROL_TOKENS = ("<|im_start|>", "<|im_end|>", "<tool_call>", "</tool_call>")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_rows(path: Path, count: int) -> list[dict[str, Any]]:
    selected: list[tuple[str, dict[str, Any]]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            row_id = str(row.get("id") or row.get("content_sha256") or line)
            selected.append((hashlib.sha256(row_id.encode()).hexdigest(), row))
    if len(selected) < count:
        raise RuntimeError(f"requested {count} parity rows but only found {len(selected)}")
    selected.sort(key=lambda item: item[0])
    return [row for _, row in selected[:count]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student", type=Path, required=True)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--messages", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from transformers import AutoTokenizer

    student = AutoTokenizer.from_pretrained(args.student, trust_remote_code=True, local_files_only=True)
    teacher = AutoTokenizer.from_pretrained(args.teacher, trust_remote_code=True, local_files_only=True)
    student_vocab = student.get_vocab()
    teacher_vocab = teacher.get_vocab()
    vocab_exact = student_vocab == teacher_vocab
    compared_special_tokens = sorted(
        set(CONTROL_TOKENS) | set(student.all_special_tokens) | set(teacher.all_special_tokens)
    )
    special_tokens = {
        token: {
            "student": student.convert_tokens_to_ids(token),
            "teacher": teacher.convert_tokens_to_ids(token),
        }
        for token in compared_special_tokens
    }
    special_exact = all(value["student"] == value["teacher"] for value in special_tokens.values())
    added_vocab_exact = student.get_added_vocab() == teacher.get_added_vocab()
    token_roles = {
        role: {
            "student_token": getattr(student, f"{role}_token"),
            "student_id": getattr(student, f"{role}_token_id"),
            "teacher_token": getattr(teacher, f"{role}_token"),
            "teacher_id": getattr(teacher, f"{role}_token_id"),
        }
        for role in ("bos", "eos", "pad", "unk")
    }
    token_roles_exact = all(
        value["student_token"] == value["teacher_token"] and value["student_id"] == value["teacher_id"]
        for value in token_roles.values()
    )

    mismatches: list[dict[str, Any]] = []
    for row in select_rows(args.messages, args.sample_size):
        student_ids, student_mask, student_rendered = assistant_loss_mask(student, row["messages"], row["tools"])
        teacher_ids, teacher_mask, teacher_rendered = assistant_loss_mask(teacher, row["messages"], row["tools"])
        if student_ids != teacher_ids or student_mask != teacher_mask or student_rendered != teacher_rendered:
            mismatches.append(
                {
                    "id": row.get("id"),
                    "token_ids_equal": student_ids == teacher_ids,
                    "assistant_loss_mask_equal": student_mask == teacher_mask,
                    "rendered_equal": student_rendered == teacher_rendered,
                }
            )
            if len(mismatches) >= 20:
                break

    token_file_names = ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")
    file_hashes = {
        name: {"student": sha256(args.student / name), "teacher": sha256(args.teacher / name)}
        for name in token_file_names
    }
    tokenizer_files_exact = all(value["student"] == value["teacher"] for value in file_hashes.values())
    status = (
        "PASS"
        if vocab_exact
        and added_vocab_exact
        and special_exact
        and token_roles_exact
        and tokenizer_files_exact
        and not mismatches
        else "BLOCKED_CANONICAL_OPD_TOKENIZER_MISMATCH"
    )
    value = {
        "schema_version": "studyhub.qwen35-opd-tokenizer-parity.v1",
        "status": status,
        "student": str(args.student.resolve()),
        "teacher": str(args.teacher.resolve()),
        "sample_source": str(args.messages.resolve()),
        "sample_size": args.sample_size,
        "vocab": {
            "student_size": len(student_vocab),
            "teacher_size": len(teacher_vocab),
            "exact": vocab_exact,
            "added_vocab_exact": added_vocab_exact,
        },
        "special_tokens": special_tokens,
        "special_token_ids_exact": special_exact,
        "token_roles": token_roles,
        "token_roles_exact": token_roles_exact,
        "tokenizer_file_hashes": file_hashes,
        "tokenizer_files_exact": tokenizer_files_exact,
        "message_parity": {
            "token_ids_exact": not mismatches,
            "assistant_loss_mask_exact": not mismatches,
            "tool_observations_masked": True,
            "mismatches": mismatches,
        },
        "canonical_opd_allowed": status == "PASS",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
