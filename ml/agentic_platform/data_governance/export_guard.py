"""Fail-closed guard used by every offline Agent dataset exporter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agentic_platform.domain.data_policy import (
    ExportTarget,
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

    def authorize_record(self, record: Mapping[str, Any], *, target: ExportTarget) -> TrainingDataPolicy:
        policy = self.policy_for(record)
        try:
            require_export_allowed(policy, target)
        except TrainingDataExportError as exc:
            raise DatasetExportDenied(exc.reason_code) from exc
        if target == ExportTarget.TRAIN and record.get("training_eligible") is not True:
            raise DatasetExportDenied("training_record_not_eligible")
        self._validate_role_spans(record)
        return policy

    def authorize_manifest(self, manifest: Mapping[str, Any], *, target: ExportTarget) -> TrainingDataPolicy:
        policy = self.policy_for(manifest)
        try:
            require_export_allowed(policy, target)
        except TrainingDataExportError as exc:
            raise DatasetExportDenied(exc.reason_code) from exc
        return policy

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
