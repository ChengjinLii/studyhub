"""Export the historical Search-R1 data shape from Model-I/O records.

The adapter keeps original rollout token IDs in ``extra_info``.  It never turns
stored summaries or artifact references back into text and never tokenizes them
again, so tool observations remain non-trainable exactly as recorded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.agentic_platform.domain.data_policy import ExportTarget

from ...data_governance import DatasetExportDenied, DatasetExportGuard


class SearchR1DatasetError(ValueError):
    pass


class SearchR1DatasetAdapter:
    """Map only export-authorized, already-tokenized model records."""

    def __init__(
        self,
        *,
        data_source: str = "studyhub.agentic.transition.v1",
        ability: str = "agentic_search",
        target: ExportTarget = ExportTarget.TRAIN,
        export_guard: DatasetExportGuard | None = None,
    ) -> None:
        if not data_source.strip() or not ability.strip():
            raise ValueError("data source and ability must not be blank")
        self.data_source = data_source
        self.ability = ability
        self.target = ExportTarget(target)
        self.export_guard = export_guard or DatasetExportGuard()

    def export_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        try:
            data_policy = self.export_guard.authorize_record(record, target=self.target)
        except DatasetExportDenied as exc:
            raise SearchR1DatasetError(f"dataset_export_denied:{exc.reason_code}") from exc
        token_ids = _raw_token_ids(record.get("token_ids"))
        token_logprobs = _optional_logprobs(record.get("token_logprobs"), len(token_ids))
        spans = _token_role_spans(record.get("token_role_spans"), len(token_ids))
        mask = _loss_mask(record.get("trainable_token_mask"), token_ids, spans)
        reward_facts = _mapping(record.get("reward_facts"), "reward_facts")
        context_view_ref = _mapping(record.get("context_view_ref"), "context_view_ref")
        parsed_decision = _mapping(record.get("parsed_decision"), "parsed_decision")
        training_eligible = record.get("training_eligible")
        if type(training_eligible) is not bool:
            raise SearchR1DatasetError("training_eligible must be a boolean")
        required_strings = (
            "trajectory_id",
            "thread_id",
            "run_id",
            "transition_id",
            "environment_snapshot_id",
            "state_before_hash",
            "state_after_hash",
            "state_abstract_key",
            "state_group_key_v2",
            "policy_version",
            "model_id",
        )
        identifiers = {name: _nonblank_string(record.get(name), name) for name in required_strings}
        return {
            # These five top-level keys intentionally mirror the historical
            # Search-R1 dataset contract without importing its training stack.
            "data_source": self.data_source,
            "prompt": {
                "context_view_ref": context_view_ref,
                "state_group_key_v2": identifiers["state_group_key_v2"],
            },
            "ability": self.ability,
            "reward_model": {
                "style": "studyhub_reward_facts_v1",
                "ground_truth": reward_facts,
            },
            "extra_info": {
                **identifiers,
                "turn_index": _nonnegative_int(record.get("turn_index"), "turn_index"),
                "raw_token_ids": token_ids,
                "token_logprobs": token_logprobs,
                "token_role_spans": spans,
                "loss_mask": mask,
                "training_eligible": training_eligible,
                "data_policy": data_policy.model_dump(mode="json"),
                "parsed_decision": parsed_decision,
                "observation_ref": _optional_mapping(record.get("observation_ref"), "observation_ref"),
                "raw_model_output_ref": _optional_mapping(record.get("raw_model_output_ref"), "raw_model_output_ref"),
            },
        }

    def export_records(self, records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [self.export_record(record) for record in records]


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SearchR1DatasetError(f"{field_name} must be a JSON object")
    return dict(value)


def _optional_mapping(value: object, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _mapping(value, field_name)


def _nonblank_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SearchR1DatasetError(f"{field_name} must be a nonblank string")
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SearchR1DatasetError(f"{field_name} must be a non-negative integer")
    return value


def _raw_token_ids(value: object) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SearchR1DatasetError("token_ids must be a list of raw token IDs")
    return [_nonnegative_int(item, "token_ids") for item in value]


def _optional_logprobs(value: object, token_count: int) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SearchR1DatasetError("token_logprobs must be a list")
    if len(value) != token_count:
        raise SearchR1DatasetError("token_logprobs must align with raw token IDs")
    if any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in value):
        raise SearchR1DatasetError("token_logprobs must be numeric")
    return [float(item) for item in value]


def _token_role_spans(value: object, token_count: int) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SearchR1DatasetError("token_role_spans must be a list")
    parsed: list[dict[str, Any]] = []
    valid_roles = {
        "system",
        "user",
        "tool_observation",
        "user_simulator_observation",
        "assistant_action",
        "assistant_final",
    }
    for raw in (_mapping(item, "token_role_span") for item in value):
        role = _nonblank_string(raw.get("role"), "token role")
        if role not in valid_roles:
            raise SearchR1DatasetError("token role is not part of the recorded role contract")
        parsed.append(
            {
                "role": role,
                "start": _nonnegative_int(raw.get("start"), "token role start"),
                "end": _nonnegative_int(raw.get("end"), "token role end"),
                "trainable": raw.get("trainable"),
            }
        )
    spans: list[dict[str, Any]] = []
    previous_end = 0
    for raw in sorted(parsed, key=lambda item: (item["start"], item["end"])):
        role = raw["role"]
        start = raw["start"]
        end = raw["end"]
        trainable = raw.get("trainable")
        if end <= start or end > token_count or start < previous_end:
            raise SearchR1DatasetError("token role spans must be ordered, non-overlapping, and in bounds")
        expected_trainable = role in {"assistant_action", "assistant_final"}
        if trainable is not expected_trainable:
            raise SearchR1DatasetError("token role trainability does not match the role contract")
        spans.append({"role": role, "start": start, "end": end, "trainable": trainable})
        previous_end = end
    return spans


def _loss_mask(value: object, token_ids: list[int], spans: list[dict[str, Any]]) -> list[bool]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SearchR1DatasetError("trainable_token_mask must be a list")
    if len(value) != len(token_ids) or any(type(item) is not bool for item in value):
        raise SearchR1DatasetError("trainable_token_mask must align with raw token IDs")
    expected = [False] * len(token_ids)
    for span in spans:
        for index in range(span["start"], span["end"]):
            expected[index] = span["trainable"]
    if list(value) != expected:
        raise SearchR1DatasetError("loss mask must match the recorded token role spans")
    return list(value)
