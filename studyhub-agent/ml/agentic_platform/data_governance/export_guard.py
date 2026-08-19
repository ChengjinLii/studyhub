"""Fail-closed guard used by every offline Agent dataset exporter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agentic_platform.domain.data_policy import (
    ExportTarget,
    TrainingCollectionAuthorization,
    TrainingDataExportError,
    TrainingDataPolicy,
    require_export_allowed,
)


class DatasetExportDenied(PermissionError):
    """A record cannot be copied to the requested offline dataset target."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class DatasetExportGuard:
    """Authorize one already-tokenized record before materializing it.

    This deliberately treats missing provenance as an error rather than
    guessing a permissive license.  It also checks the existing model-token
    eligibility marker for train exports; policy authorization alone cannot
    make a Tool Observation or un-tokenized provider response trainable.
    """

    def __init__(
        self,
        *,
        collection_authorization: TrainingCollectionAuthorization | None = None,
        enforce_collection_gate: bool = True,
    ) -> None:
        self.collection_authorization = collection_authorization
        self.enforce_collection_gate = enforce_collection_gate

    def authorize_record(self, record: Mapping[str, Any], *, target: ExportTarget) -> TrainingDataPolicy:
        policy = self.policy_for(record)
        try:
            require_export_allowed(policy, target)
        except TrainingDataExportError as exc:
            raise DatasetExportDenied(exc.reason_code) from exc
        if target == ExportTarget.TRAIN and record.get("training_eligible") is not True:
            raise DatasetExportDenied("training_record_not_eligible")
        if target == ExportTarget.TRAIN:
            self._require_training_collection_authorization()
            self._validate_train_provenance(record)
        self._validate_role_spans(record)
        return policy

    def authorize_manifest(self, manifest: Mapping[str, Any], *, target: ExportTarget) -> TrainingDataPolicy:
        policy = self.policy_for(manifest)
        try:
            require_export_allowed(policy, target)
        except TrainingDataExportError as exc:
            raise DatasetExportDenied(exc.reason_code) from exc
        if target == ExportTarget.TRAIN:
            self._require_training_collection_authorization()
        return policy

    def _require_training_collection_authorization(self) -> None:
        if not self.enforce_collection_gate:
            return
        if self.collection_authorization is None:
            raise DatasetExportDenied("collection_gate_not_authorized")

    @staticmethod
    def _validate_train_provenance(record: Mapping[str, Any]) -> None:
        required_fields = (
            "model_id",
            "policy_version",
            "prompt_template_hash",
            "skill_catalog_hash",
            "retriever_version",
            "environment_snapshot_id",
            "environment_snapshot_hash",
        )
        values: list[str] = []
        for field_name in required_fields:
            value = record.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise DatasetExportDenied("missing_runtime_provenance")
            values.append(value)
        if any(value.startswith("legacy-unavailable-") or value == "unconfigured-retriever" for value in values):
            raise DatasetExportDenied("unresolved_runtime_provenance")

    @staticmethod
    def policy_for(value: Mapping[str, Any]) -> TrainingDataPolicy:
        raw = value.get("data_policy")
        if not isinstance(raw, Mapping):
            raise DatasetExportDenied("missing_data_policy")
        try:
            return TrainingDataPolicy.model_validate(dict(raw))
        except Exception as exc:  # noqa: BLE001 - normalize schema errors for callers.
            raise DatasetExportDenied("invalid_data_policy") from exc

    @staticmethod
    def _validate_role_spans(record: Mapping[str, Any]) -> None:
        spans = record.get("token_role_spans")
        if spans is None:
            return
        if not isinstance(spans, list):
            raise DatasetExportDenied("invalid_token_role_spans")
        for span in spans:
            if not isinstance(span, Mapping):
                raise DatasetExportDenied("invalid_token_role_spans")
            if span.get("role") in {"tool_observation", "user_simulator_observation"} and span.get("trainable") is True:
                raise DatasetExportDenied("observation_tokens_must_not_be_trainable")
