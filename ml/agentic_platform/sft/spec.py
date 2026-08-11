"""Validation contract for StudyHub Agent SFT specification datasets.

The contract deliberately stays independent from the production database and
model runtime. It validates JSONL artifacts against a frozen public corpus and
the current read-only tool boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "studyhub.agent.sft.spec.v0"
ALLOWED_PROFILES = {"router_tool_2b", "grounded_tutor_9b"}
ALLOWED_SPLITS = {"train", "validation", "test"}
ALLOWED_DATA_CLASSES = {"public", "synthetic", "public_synthetic"}
ALLOWED_LABEL_STATUSES = {
    "silver_spec_validation",
    "silver_teacher_sft",
}
ALLOWED_TOOLS = {
    "search_materials",
    "inspect_materials",
    "read_pdf_evidence",
    "read_memory",
    "synthesize_course_context",
}
REQUIRED_POLICY_TAGS = {"readonly", "free_materials_only", "no_private_user_data"}

_EXAMPLE_ID = re.compile(r"^(2b|9b)_[0-9]{4}$")
_FORBIDDEN_CONTENT = (
    re.compile(r"https?://(?:pan\.baidu\.com|yun\.baidu\.com)", re.IGNORECASE),
    re.compile(r"(?:pwd|提取码)\s*[:=]\s*[A-Za-z0-9]{4,}", re.IGNORECASE),
    re.compile(r"<think>|</think>|隐藏思维链|内部思考过程", re.IGNORECASE),
    re.compile(r"\b1[3-9][0-9]{9}\b"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)


class DatasetSpecError(ValueError):
    pass


@dataclass(slots=True)
class DatasetAudit:
    total_records: int = 0
    profile_counts: Counter[str] = field(default_factory=Counter)
    split_counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    family_counts: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    data_class_counts: Counter[str] = field(default_factory=Counter)
    evidence_kind_counts: Counter[str] = field(default_factory=Counter)
    material_ids: set[int] = field(default_factory=set)
    chunk_ids: set[str] = field(default_factory=set)
    duplicate_pairs: list[tuple[str, str]] = field(default_factory=list)
    material_split_leaks: dict[int, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    dataset_sha256: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.errors and not self.duplicate_pairs and not self.material_split_leaks

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total_records": self.total_records,
            "profile_counts": dict(sorted(self.profile_counts.items())),
            "split_counts": {
                profile: dict(sorted(counts.items()))
                for profile, counts in sorted(self.split_counts.items())
            },
            "family_counts": {
                profile: dict(sorted(counts.items()))
                for profile, counts in sorted(self.family_counts.items())
            },
            "data_class_counts": dict(sorted(self.data_class_counts.items())),
            "evidence_kind_counts": dict(sorted(self.evidence_kind_counts.items())),
            "unique_material_ids": len(self.material_ids),
            "unique_chunk_ids": len(self.chunk_ids),
            "duplicate_pairs": [list(item) for item in self.duplicate_pairs],
            "material_split_leaks": {
                str(material_id): splits
                for material_id, splits in sorted(self.material_split_leaks.items())
            },
            "errors": list(self.errors),
            "dataset_sha256": dict(sorted(self.dataset_sha256.items())),
        }


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise DatasetSpecError(f"{path}:{line_number}: blank JSONL line")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetSpecError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise DatasetSpecError(f"{path}:{line_number}: record must be an object")
        result.append(value)
    return result


def load_public_corpus(
    *,
    materials_path: str | Path,
    chunks_path: str | Path,
) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    materials = {
        int(row["id"]): row
        for row in load_jsonl(materials_path)
        if row.get("free") is True and float(row.get("price") or 0) == 0
    }
    chunks = {
        str(row["chunk_id"]): row
        for row in load_jsonl(chunks_path)
        if int(row.get("material_id") or 0) in materials
    }
    return materials, chunks


def validate_record(
    record: Mapping[str, Any],
    *,
    materials: Mapping[int, Mapping[str, Any]],
    chunks: Mapping[str, Mapping[str, Any]],
) -> None:
    example_id = _string(record.get("example_id"), "example_id")
    if not _EXAMPLE_ID.fullmatch(example_id):
        raise DatasetSpecError("example_id does not match the versioned ID contract")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise DatasetSpecError("schema_version is not supported")

    profile = _string(record.get("target_profile"), "target_profile")
    if profile not in ALLOWED_PROFILES:
        raise DatasetSpecError("target_profile is not supported")
    expected_prefix = "2b_" if profile == "router_tool_2b" else "9b_"
    if not example_id.startswith(expected_prefix):
        raise DatasetSpecError("example_id prefix does not match target_profile")

    split = _string(record.get("split"), "split")
    if split not in ALLOWED_SPLITS:
        raise DatasetSpecError("split is not supported")
    _string(record.get("task_family"), "task_family")

    data_class = _string(record.get("data_class"), "data_class")
    if data_class not in ALLOWED_DATA_CLASSES:
        raise DatasetSpecError("data_class is not train-export eligible")
    if record.get("training_eligible") is not True:
        raise DatasetSpecError("spec-validation records must be explicitly training eligible")

    policy_tags = set(_string_list(record.get("policy_tags"), "policy_tags", minimum=3))
    if not REQUIRED_POLICY_TAGS.issubset(policy_tags):
        raise DatasetSpecError("required policy boundary tags are missing")

    messages = _sequence(record.get("messages"), "messages")
    if len(messages) < 3:
        raise DatasetSpecError("messages must contain system, user, and assistant turns")
    parsed_messages = [_mapping(item, "message") for item in messages]
    roles = [_string(item.get("role"), "message role") for item in parsed_messages]
    if roles[0] != "system" or roles[1] != "user" or roles[-1] != "assistant":
        raise DatasetSpecError("message role order is invalid")
    if any(role not in {"system", "user", "assistant", "tool"} for role in roles):
        raise DatasetSpecError("message role is unsupported")
    if sum(role == "assistant" for role in roles) != 1:
        raise DatasetSpecError("spec-validation records must have one trainable assistant target")
    for item in parsed_messages:
        _string(item.get("content"), "message content")
        expected_trainable = item.get("role") == "assistant"
        if item.get("trainable") is not expected_trainable:
            raise DatasetSpecError("message trainability does not match role contract")

    try:
        user_payload = json.loads(parsed_messages[1]["content"])
        assistant_message = json.loads(parsed_messages[-1]["content"])
    except json.JSONDecodeError as exc:
        raise DatasetSpecError("user and assistant message contents must be strict JSON") from exc
    if not isinstance(user_payload, dict) or not isinstance(assistant_message, dict):
        raise DatasetSpecError("user and assistant message contents must decode to objects")
    assistant_target = _mapping(record.get("assistant_target"), "assistant_target")
    if canonical_json(assistant_message) != canonical_json(assistant_target):
        raise DatasetSpecError("assistant message and assistant_target differ")

    _validate_user_payload(user_payload)
    validate_assistant_target(assistant_target, profile=profile)

    refs = _sequence(record.get("evidence_refs"), "evidence_refs")
    referenced_material_ids: set[int] = set()
    for item in refs:
        ref = _mapping(item, "evidence_ref")
        material_id = _positive_int(ref.get("material_id"), "evidence material_id")
        material = materials.get(material_id)
        if material is None:
            raise DatasetSpecError(f"evidence material {material_id} is not in the free snapshot")
        if material.get("free") is not True or float(material.get("price") or 0) != 0:
            raise DatasetSpecError("evidence references a paid material")
        chunk_id = _string(ref.get("chunk_id"), "evidence chunk_id")
        chunk = chunks.get(chunk_id)
        if chunk is None or int(chunk.get("material_id") or 0) != material_id:
            raise DatasetSpecError("evidence chunk does not belong to the referenced material")
        if str(ref.get("title") or "") != str(chunk.get("title") or ""):
            raise DatasetSpecError("evidence title does not match the frozen chunk")
        if ref.get("page") != chunk.get("page"):
            raise DatasetSpecError("evidence page does not match the frozen chunk")
        if ref.get("source_kind") != chunk.get("source_kind"):
            raise DatasetSpecError("evidence source_kind does not match the frozen chunk")
        referenced_material_ids.add(material_id)

    if data_class == "synthetic" and refs:
        raise DatasetSpecError("synthetic-only records must not carry corpus evidence")
    if data_class == "public" and not refs:
        raise DatasetSpecError("public records must carry frozen corpus evidence")

    _validate_target_references(assistant_target, referenced_material_ids)
    _validate_snapshot(record.get("source_snapshot"))
    _validate_quality(record.get("quality"))
    _validate_provenance(record.get("provenance"))
    _scan_forbidden_content(record)


def audit_datasets(
    paths: Iterable[str | Path],
    *,
    materials_path: str | Path,
    chunks_path: str | Path,
    expected_profile_counts: Mapping[str, int] | None = None,
    expected_split_counts: Mapping[str, Mapping[str, int]] | None = None,
) -> DatasetAudit:
    materials, chunks = load_public_corpus(materials_path=materials_path, chunks_path=chunks_path)
    audit = DatasetAudit()
    seen_ids: set[str] = set()
    seen_pairs: dict[str, str] = {}
    material_splits: dict[int, set[str]] = defaultdict(set)

    for raw_path in paths:
        path = Path(raw_path)
        audit.dataset_sha256[path.name] = sha256_file(path)
        for line_number, record in enumerate(load_jsonl(path), start=1):
            example_id = str(record.get("example_id") or f"{path.name}:{line_number}")
            try:
                validate_record(record, materials=materials, chunks=chunks)
            except DatasetSpecError as exc:
                audit.errors.append(f"{example_id}: {exc}")
                continue
            if example_id in seen_ids:
                audit.errors.append(f"{example_id}: duplicate example_id")
                continue
            seen_ids.add(example_id)

            profile = str(record["target_profile"])
            split = str(record["split"])
            family = str(record["task_family"])
            data_class = str(record["data_class"])
            audit.total_records += 1
            audit.profile_counts[profile] += 1
            audit.split_counts[profile][split] += 1
            audit.family_counts[profile][family] += 1
            audit.data_class_counts[data_class] += 1

            messages = record["messages"]
            pair_key = hashlib.sha256(
                (
                    _normalize_text(str(messages[1]["content"]))
                    + "\n"
                    + canonical_json(record["assistant_target"])
                ).encode("utf-8")
            ).hexdigest()
            previous = seen_pairs.get(pair_key)
            if previous is not None:
                audit.duplicate_pairs.append((previous, example_id))
            else:
                seen_pairs[pair_key] = example_id

            for ref in record["evidence_refs"]:
                material_id = int(ref["material_id"])
                chunk_id = str(ref["chunk_id"])
                audit.material_ids.add(material_id)
                audit.chunk_ids.add(chunk_id)
                audit.evidence_kind_counts[str(ref["source_kind"])] += 1
                material_splits[material_id].add(split)

    for material_id, splits in material_splits.items():
        if len(splits) > 1:
            audit.material_split_leaks[material_id] = sorted(splits)

    if expected_profile_counts:
        for profile, expected in expected_profile_counts.items():
            actual = audit.profile_counts.get(profile, 0)
            if actual != expected:
                audit.errors.append(f"{profile}: expected {expected} records, found {actual}")
    if expected_split_counts:
        for profile, expected_splits in expected_split_counts.items():
            for split, expected in expected_splits.items():
                actual = audit.split_counts.get(profile, Counter()).get(split, 0)
                if actual != expected:
                    audit.errors.append(
                        f"{profile}/{split}: expected {expected} records, found {actual}"
                    )
    return audit


def _validate_user_payload(value: Mapping[str, Any]) -> None:
    _string(value.get("current_user_query"), "current_user_query")
    _string(value.get("instruction"), "instruction")
    budget = _mapping(value.get("budget"), "budget")
    for field_name in (
        "remaining_rounds",
        "remaining_tool_calls",
        "remaining_search_calls",
        "remaining_candidate_slots",
    ):
        _nonnegative_int(budget.get(field_name), field_name)
    if type(value.get("force_final")) is not bool:
        raise DatasetSpecError("force_final must be a boolean")
    _sequence(value.get("tool_observations"), "tool_observations")
    _sequence(value.get("search_history"), "search_history")
    _mapping(value.get("task_context"), "task_context")


def validate_assistant_target(value: Mapping[str, Any], *, profile: str) -> None:
    mode = _string(value.get("mode"), "assistant mode")
    if mode not in {"tools", "final"}:
        raise DatasetSpecError("assistant mode must be tools or final")
    _mapping(value.get("task_context"), "assistant task_context")
    if profile == "grounded_tutor_9b" and mode != "final":
        raise DatasetSpecError("grounded_tutor_9b records must teach final grounded responses")

    if mode == "tools":
        _string(value.get("progress"), "tool progress")
        actions = _sequence(value.get("actions"), "actions")
        if not 1 <= len(actions) <= 4:
            raise DatasetSpecError("tool mode must contain one to four actions")
        for item in actions:
            action = _mapping(item, "action")
            name = _string(action.get("name"), "tool name")
            if name not in ALLOWED_TOOLS:
                raise DatasetSpecError(f"tool {name} is outside the read-only boundary")
            validate_tool_action(name, _mapping(action.get("arguments"), "tool arguments"))
        return

    answer = _string(value.get("answer"), "answer")
    if not 20 <= len(answer) <= 5000:
        raise DatasetSpecError("final answer length is outside the validation contract")
    recommendations = _sequence(value.get("recommendations"), "recommendations")
    for item in recommendations:
        recommendation = _mapping(item, "recommendation")
        _positive_int(recommendation.get("material_id"), "recommendation material_id")
        _string(recommendation.get("reason"), "recommendation reason")
    evidence_sources = _sequence(value.get("evidence_sources"), "evidence_sources")
    for item in evidence_sources:
        source = _mapping(item, "evidence_source")
        _positive_int(source.get("material_id"), "source material_id")
        _string(source.get("chunk_id"), "source chunk_id")
        _string(source.get("title"), "source title")
        page = source.get("page")
        if page is not None:
            _positive_int(page, "source page")
    followups = _string_list(value.get("followup_questions"), "followup_questions")
    if len(followups) > 3:
        raise DatasetSpecError("final response has too many follow-up questions")


def validate_tool_action(name: str, arguments: Mapping[str, Any]) -> None:
    if name not in ALLOWED_TOOLS:
        raise DatasetSpecError(f"tool {name} is outside the read-only boundary")
    _validate_tool_arguments(name, arguments)


def _validate_tool_arguments(name: str, arguments: Mapping[str, Any]) -> None:
    if name == "search_materials":
        _bounded_string(arguments.get("query"), "search query", maximum=500)
        _bounded_int(arguments.get("limit"), "search limit", minimum=1, maximum=12)
        filters = arguments.get("filters", {})
        parsed_filters = _mapping(filters, "search filters")
        if set(parsed_filters) - {"school", "college", "major", "tag"}:
            raise DatasetSpecError("search filters contain an unsupported field")
        for value in parsed_filters.values():
            _bounded_string(value, "search filter", maximum=100)
    elif name == "inspect_materials":
        _material_ids(arguments.get("material_ids"), maximum=8)
    elif name == "read_pdf_evidence":
        _material_ids(arguments.get("material_ids"), maximum=6)
        _bounded_string(arguments.get("query"), "evidence query", maximum=500)
        _bounded_int(arguments.get("max_pages"), "max_pages", minimum=1, maximum=8)
        if "page_numbers" in arguments:
            pages = _sequence(arguments.get("page_numbers"), "page_numbers")
            if len(pages) > 8:
                raise DatasetSpecError("too many requested page numbers")
            for page in pages:
                _bounded_int(page, "page number", minimum=1, maximum=80)
    elif name == "read_memory":
        _bounded_string(arguments.get("focus"), "memory focus", maximum=500)
    elif name == "synthesize_course_context":
        _bounded_string(arguments.get("task_label"), "task label", maximum=160)
        for field_name, maximum in (
            ("course_terms", 4),
            ("evidence_goals", 6),
            ("response_preferences", 6),
            ("constraints", 6),
        ):
            values = _string_list(arguments.get(field_name), field_name)
            if len(values) > maximum:
                raise DatasetSpecError(f"{field_name} exceeds its item budget")


def _validate_target_references(
    target: Mapping[str, Any],
    referenced_material_ids: set[int],
) -> None:
    target_ids: set[int] = set()
    for recommendation in target.get("recommendations", []):
        if isinstance(recommendation, Mapping):
            target_ids.add(int(recommendation["material_id"]))
    for source in target.get("evidence_sources", []):
        if isinstance(source, Mapping):
            target_ids.add(int(source["material_id"]))
    for action in target.get("actions", []):
        if not isinstance(action, Mapping):
            continue
        arguments = action.get("arguments")
        if not isinstance(arguments, Mapping):
            continue
        for material_id in arguments.get("material_ids", []):
            target_ids.add(int(material_id))
    if not target_ids.issubset(referenced_material_ids):
        raise DatasetSpecError("assistant target references materials outside evidence_refs")


def _validate_snapshot(value: object) -> None:
    snapshot = _mapping(value, "source_snapshot")
    if snapshot.get("access_scope") != "free_public_only":
        raise DatasetSpecError("source snapshot is not restricted to free public materials")
    for field_name in ("materials_sha256", "chunks_sha256", "snapshot_id"):
        text = _string(snapshot.get(field_name), field_name)
        if field_name.endswith("sha256") and not re.fullmatch(r"[0-9a-f]{64}", text):
            raise DatasetSpecError(f"{field_name} is not a SHA-256 digest")


def _validate_quality(value: object) -> None:
    quality = _mapping(value, "quality")
    if quality.get("label_status") not in ALLOWED_LABEL_STATUSES:
        raise DatasetSpecError("quality label_status is not an approved silver label")
    if quality.get("teacher_policy_reviewed") is not True:
        raise DatasetSpecError("teacher policy review flag is required")
    if quality.get("deterministic_checks_passed") is not True:
        raise DatasetSpecError("deterministic check flag is required")


def _validate_provenance(value: object) -> None:
    provenance = _mapping(value, "provenance")
    for field_name in (
        "teacher_runtime",
        "teacher_model_requested",
        "generation_method",
        "template_id",
        "generated_at",
    ):
        _string(provenance.get(field_name), field_name)
    if provenance.get("runtime_model_verified") is not False:
        raise DatasetSpecError("unverified runtime model must be represented explicitly")


def _scan_forbidden_content(record: Mapping[str, Any]) -> None:
    serialized = canonical_json(record)
    for pattern in _FORBIDDEN_CONTENT:
        if pattern.search(serialized):
            raise DatasetSpecError(f"record contains forbidden content matching {pattern.pattern}")


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DatasetSpecError(f"{field_name} must be an object")
    return dict(value)


def _sequence(value: object, field_name: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DatasetSpecError(f"{field_name} must be an array")
    return list(value)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetSpecError(f"{field_name} must be a nonblank string")
    return value.strip()


def _bounded_string(value: object, field_name: str, *, maximum: int) -> str:
    text = _string(value, field_name)
    if len(text) > maximum:
        raise DatasetSpecError(f"{field_name} exceeds {maximum} characters")
    return text


def _string_list(
    value: object,
    field_name: str,
    *,
    minimum: int = 0,
) -> list[str]:
    values = _sequence(value, field_name)
    if len(values) < minimum:
        raise DatasetSpecError(f"{field_name} has too few items")
    return [_string(item, field_name) for item in values]


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DatasetSpecError(f"{field_name} must be a positive integer")
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DatasetSpecError(f"{field_name} must be a non-negative integer")
    return value


def _bounded_int(value: object, field_name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise DatasetSpecError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _material_ids(value: object, *, maximum: int) -> list[int]:
    values = _sequence(value, "material_ids")
    if not 1 <= len(values) <= maximum:
        raise DatasetSpecError("material_ids has an invalid item count")
    parsed = [_positive_int(item, "material_id") for item in values]
    if len(parsed) != len(set(parsed)):
        raise DatasetSpecError("material_ids contains duplicates")
    return parsed


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()
