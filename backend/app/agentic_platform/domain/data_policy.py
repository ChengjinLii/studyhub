"""Data classification and fail-closed export rules for Agent trajectories.

The policy belongs to the durable domain contract rather than a particular
training framework.  Runtime code can therefore label artifacts and
transitions without importing a trainer, while every later exporter applies the
same restrictive decision.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Iterable

from pydantic import Field, field_validator, model_validator

from ._base import DomainModel


class DataSensitivity(StrEnum):
    PUBLIC = "public"
    SYNTHETIC = "synthetic"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    PERSONAL = "personal"


class LicenseClass(StrEnum):
    PUBLIC_TRAINABLE = "public_trainable"
    SYNTHETIC_TRAINABLE = "synthetic_trainable"
    INTERNAL_EVAL_ONLY = "internal_eval_only"
    RESTRICTED_NO_EXPORT = "restricted_no_export"
    PERSONAL_NO_TRAINING = "personal_no_training"


class SourceScope(StrEnum):
    PUBLIC = "public"
    SYNTHETIC = "synthetic"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    PERSONAL = "personal"


class ExportTarget(StrEnum):
    TRAIN = "train"
    EVAL = "eval"


class TrainingDataPolicy(DomainModel):
    """Immutable classification required before an artifact can be exported.

    ``training_allowed`` is deliberately not inferred from model/token fields.
    It is a source-data authorization decision, so an unclassified record can
    never become trainable merely because it has a valid action-token span.
    """

    schema_version: str = "1.0"
    training_allowed: bool
    sensitivity: DataSensitivity
    license_class: LicenseClass
    source_scope: SourceScope
    contains_personal_data: bool
    anonymization_version: str | None = Field(default=None, max_length=128)
    retention_policy: str = Field(min_length=1, max_length=256)

    @field_validator("anonymization_version", "retention_policy")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_license_contract(self) -> "TrainingDataPolicy":
        expected = {
            LicenseClass.PUBLIC_TRAINABLE: (True, DataSensitivity.PUBLIC, SourceScope.PUBLIC, False),
            LicenseClass.SYNTHETIC_TRAINABLE: (True, DataSensitivity.SYNTHETIC, SourceScope.SYNTHETIC, False),
            LicenseClass.INTERNAL_EVAL_ONLY: (False, DataSensitivity.INTERNAL, SourceScope.INTERNAL, False),
            LicenseClass.RESTRICTED_NO_EXPORT: (False, DataSensitivity.RESTRICTED, SourceScope.RESTRICTED, False),
            LicenseClass.PERSONAL_NO_TRAINING: (False, DataSensitivity.PERSONAL, SourceScope.PERSONAL, True),
        }[self.license_class]
        actual = (
            self.training_allowed,
            self.sensitivity,
            self.source_scope,
            self.contains_personal_data,
        )
        if actual != expected:
            raise ValueError(f"data policy fields do not match {self.license_class.value}")
        return self

    @classmethod
    def public_trainable(cls, *, retention_policy: str = "public_training_standard") -> "TrainingDataPolicy":
        return cls(
            training_allowed=True,
            sensitivity=DataSensitivity.PUBLIC,
            license_class=LicenseClass.PUBLIC_TRAINABLE,
            source_scope=SourceScope.PUBLIC,
            contains_personal_data=False,
            retention_policy=retention_policy,
        )

    @classmethod
    def synthetic_trainable(cls, *, retention_policy: str = "synthetic_training_standard") -> "TrainingDataPolicy":
        return cls(
            training_allowed=True,
            sensitivity=DataSensitivity.SYNTHETIC,
            license_class=LicenseClass.SYNTHETIC_TRAINABLE,
            source_scope=SourceScope.SYNTHETIC,
            contains_personal_data=False,
            retention_policy=retention_policy,
        )

    @classmethod
    def internal_eval_only(cls, *, retention_policy: str = "internal_evaluation_only") -> "TrainingDataPolicy":
        """Return the safe default for legacy or not-yet-reviewed records."""

        return cls(
            training_allowed=False,
            sensitivity=DataSensitivity.INTERNAL,
            license_class=LicenseClass.INTERNAL_EVAL_ONLY,
            source_scope=SourceScope.INTERNAL,
            contains_personal_data=False,
            retention_policy=retention_policy,
        )

    @classmethod
    def restricted_no_export(cls, *, retention_policy: str = "restricted_no_export") -> "TrainingDataPolicy":
        return cls(
            training_allowed=False,
            sensitivity=DataSensitivity.RESTRICTED,
            license_class=LicenseClass.RESTRICTED_NO_EXPORT,
            source_scope=SourceScope.RESTRICTED,
            contains_personal_data=False,
            retention_policy=retention_policy,
        )

    @classmethod
    def personal_no_training(
        cls,
        *,
        anonymization_version: str | None = None,
        retention_policy: str = "personal_data_no_training",
    ) -> "TrainingDataPolicy":
        return cls(
            training_allowed=False,
            sensitivity=DataSensitivity.PERSONAL,
            license_class=LicenseClass.PERSONAL_NO_TRAINING,
            source_scope=SourceScope.PERSONAL,
            contains_personal_data=True,
            anonymization_version=anonymization_version,
            retention_policy=retention_policy,
        )

    def allows(self, target: ExportTarget) -> bool:
        if self.license_class in {LicenseClass.RESTRICTED_NO_EXPORT, LicenseClass.PERSONAL_NO_TRAINING}:
            return False
        if target == ExportTarget.EVAL:
            return True
        return self.training_allowed and self.license_class in {
            LicenseClass.PUBLIC_TRAINABLE,
            LicenseClass.SYNTHETIC_TRAINABLE,
        }


class TrainingDataExportError(PermissionError):
    """A requested export violates the durable source-data classification."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def require_export_allowed(policy: TrainingDataPolicy, target: ExportTarget) -> None:
    """Fail closed before any dataset row is materialized or copied."""

    if policy.license_class == LicenseClass.RESTRICTED_NO_EXPORT:
        raise TrainingDataExportError("restricted_no_export")
    if policy.license_class == LicenseClass.PERSONAL_NO_TRAINING:
        raise TrainingDataExportError("personal_no_training")
    if target == ExportTarget.TRAIN and not policy.allows(target):
        raise TrainingDataExportError("training_not_allowed")
    if target == ExportTarget.EVAL and not policy.allows(target):
        raise TrainingDataExportError("evaluation_not_allowed")


def aggregate_data_policies(policies: Iterable[TrainingDataPolicy]) -> TrainingDataPolicy:
    """Return a conservative trajectory-level policy for a mixed record set.

    A manifest has one compact classification.  If its constituent records are
    heterogeneous, the result intentionally becomes ``internal_eval_only``
    rather than claiming that all bytes have the most permissive license.
    """

    values = [policy.model_copy(deep=True) for policy in policies]
    if not values:
        return TrainingDataPolicy.internal_eval_only()
    if all(policy == values[0] for policy in values[1:]):
        return values[0]
    license_classes = {policy.license_class for policy in values}
    if LicenseClass.PERSONAL_NO_TRAINING in license_classes:
        return TrainingDataPolicy.personal_no_training(retention_policy="mixed_sources_require_review")
    if LicenseClass.RESTRICTED_NO_EXPORT in license_classes:
        return TrainingDataPolicy.restricted_no_export(retention_policy="mixed_sources_require_review")
    if LicenseClass.INTERNAL_EVAL_ONLY in license_classes:
        return TrainingDataPolicy.internal_eval_only(retention_policy="mixed_sources_require_review")
    return TrainingDataPolicy.internal_eval_only(retention_policy="mixed_trainable_sources_require_review")


def manifest_policy_fields(policy: TrainingDataPolicy) -> dict[str, object]:
    """Return audit-friendly top-level manifest fields for ``policy``.

    The full policy remains nested for complete provenance, while these fields
    make common export review queries possible without a JSON-path dependency.
    """

    return {
        "training_allowed": policy.training_allowed,
        "sensitivity": policy.sensitivity,
        "license_class": policy.license_class,
        "anonymization_version": policy.anonymization_version,
        "retention_policy": policy.retention_policy,
    }
