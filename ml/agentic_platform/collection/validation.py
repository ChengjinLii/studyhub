"""Validate immutable pilot trajectories against the pre-collection Go Gate."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.data_policy import ExportTarget, TrainingCollectionAuthorization
from app.agentic_platform.domain.transition import TokenRole
from app.agentic_platform.persistence.durable_transition_sink import DurableTrajectoryError, DurableTransitionSink
from app.agentic_platform.domain.hashing import canonical_hash

from ..data_governance import DatasetExportDenied, DatasetExportGuard
from .pilot import PilotRunReport, PilotScenarioManifest, PilotScenarioOutcome, PilotOutcomeStatus


class PilotGateReport(DomainModel):
    """Machine-readable evidence for every Pilot Gate metric in the plan."""

    schema_version: str = "1.0"
    pilot_report_hash: str = Field(min_length=64, max_length=64)
    export_target: ExportTarget
    required_count: int = Field(gt=0)
    run_completion: dict[str, int]
    queued_duration: dict[str, float | int]
    turn_count: int = Field(ge=0)
    tool_count: int = Field(ge=0)
    token_coverage: dict[str, int]
    role_span_coverage: dict[str, int]
    tool_observation_trainability: dict[str, int]
    child_transition_coverage: dict[str, int]
    version_coverage: dict[str, int]
    citation_validity: dict[str, int]
    replay_result: dict[str, int]
    data_classification: dict[str, int]
    quarantine_reasons: dict[str, int]
    api_cost: float = Field(ge=0.0)
    gpu_metadata: dict[str, float]
    manifest_verification: dict[str, int]
    acl_violations: int = Field(ge=0)
    invalid_citations: int = Field(ge=0)
    restricted_export_denials: int = Field(ge=0)
    ci_passed: bool = False
    mysql_migration_verified: bool = False
    gate_passed: bool
    failed_gates: list[str] = Field(default_factory=list)
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("pilot_report_hash", "content_hash")
    @classmethod
    def reject_blank_hash(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pilot gate hashes must not be blank")
        return value

    @model_validator(mode="after")
    def validate_hash(self) -> "PilotGateReport":
        if self.content_hash != self._content_hash():
            raise ValueError("pilot gate report content hash does not match its fields")
        return self

    @classmethod
    def build(cls, **data: object) -> "PilotGateReport":
        content_hash = canonical_hash({"schema_version": "1.0", **data}, exclude_fields=())
        return cls(**data, content_hash=content_hash)

    def _content_hash(self) -> str:
        return canonical_hash(
            {
                "schema_version": self.schema_version,
                "pilot_report_hash": self.pilot_report_hash,
                "export_target": self.export_target,
                "required_count": self.required_count,
                "run_completion": self.run_completion,
                "queued_duration": self.queued_duration,
                "turn_count": self.turn_count,
                "tool_count": self.tool_count,
                "token_coverage": self.token_coverage,
                "role_span_coverage": self.role_span_coverage,
                "tool_observation_trainability": self.tool_observation_trainability,
                "child_transition_coverage": self.child_transition_coverage,
                "version_coverage": self.version_coverage,
                "citation_validity": self.citation_validity,
                "replay_result": self.replay_result,
                "data_classification": self.data_classification,
                "quarantine_reasons": self.quarantine_reasons,
                "api_cost": self.api_cost,
                "gpu_metadata": self.gpu_metadata,
                "manifest_verification": self.manifest_verification,
                "acl_violations": self.acl_violations,
                "invalid_citations": self.invalid_citations,
                "restricted_export_denials": self.restricted_export_denials,
                "ci_passed": self.ci_passed,
                "mysql_migration_verified": self.mysql_migration_verified,
                "gate_passed": self.gate_passed,
                "failed_gates": self.failed_gates,
            },
            exclude_fields=(),
        )


class PilotGateAuthorizationError(ValueError):
    """The documented Go Gate is not sufficient to open Train collection."""


def authorize_training_collection(gate: PilotGateReport) -> TrainingCollectionAuthorization:
    """Issue a content-addressed Train export authorization after the Go Gate.

    The report remains the detailed audit evidence; the compact authorization
    is what offline exporters require.  Deliberately no authorization is
    issued for a small smoke pilot, a failed gate, or an Eval-only report.
    """

    if gate.export_target != ExportTarget.TRAIN:
        raise PilotGateAuthorizationError("collection_authorization_requires_train_gate")
    if gate.required_count < 100:
        raise PilotGateAuthorizationError("collection_authorization_requires_100_pilot_runs")
    if not gate.gate_passed or gate.failed_gates:
        raise PilotGateAuthorizationError("collection_authorization_requires_passing_gate")
    return TrainingCollectionAuthorization.issue(
        pilot_report_hash=gate.pilot_report_hash,
        pilot_gate_content_hash=gate.content_hash,
        required_count=gate.required_count,
    )


def validate_pilot_dataset(
    report: PilotRunReport,
    *,
    target: ExportTarget = ExportTarget.TRAIN,
    scenario_manifest: PilotScenarioManifest | None = None,
    required_count: int = 100,
    long_queue_threshold_ms: float = 60_000.0,
    ci_passed: bool = False,
    mysql_migration_verified: bool = False,
) -> PilotGateReport:
    """Re-read every immutable segment and calculate the documented Go Gate.

    A malformed/missing trajectory, disallowed export class, un-tokenized turn,
    or failed replay is reflected in ``failed_gates``.  The function never
    exports data itself.
    """

    if required_count <= 0:
        raise ValueError("required_count must be positive")
    if long_queue_threshold_ms < 0:
        raise ValueError("long_queue_threshold_ms must not be negative")

    # This function only audits prospective records; it does not materialize
    # an offline Train dataset.  Requiring the authorization here would make
    # the Gate circular, so exporters retain the strict default instead.
    guard = DatasetExportGuard(enforce_collection_gate=False)
    sink = DurableTransitionSink(Path(report.trajectory_root))
    outcomes = list(report.outcomes)
    completed = [item for item in outcomes if item.status == PilotOutcomeStatus.COMPLETED]
    failures: list[str] = []
    manifest_verified = 0
    manifest_failures = 0
    turn_count = 0
    tool_count = 0
    model_turn_count = 0
    tokenized_turns = 0
    role_spanned_turns = 0
    observation_token_count = 0
    trainable_observation_token_count = 0
    versioned_turns = 0
    child_turns = 0
    required_child_runs = 0
    child_covered_runs = 0
    policy_counts: Counter[str] = Counter()
    quarantine_reasons: Counter[str] = Counter()
    acl_violations = 0
    export_denials = 0
    restricted_export_denials = 0
    citation_checked = 0
    citation_valid = 0
    scenario_by_id = {
        scenario.scenario_id: scenario
        for scenario in (scenario_manifest.scenarios if scenario_manifest is not None else [])
    }

    for outcome in outcomes:
        policy_counts[outcome.data_policy.license_class.value] += 1
        if outcome.citation_valid is not None:
            citation_checked += 1
            citation_valid += int(outcome.citation_valid)
        if outcome.error_code:
            quarantine_reasons[outcome.error_code] += 1
            acl_violations += int(_is_acl_violation(outcome.error_code))
        scenario = scenario_by_id.get(outcome.scenario_id)
        if scenario is not None and scenario.requires_child_transitions:
            required_child_runs += 1

    for outcome in completed:
        assert outcome.trajectory_id is not None
        try:
            records = sink.load_records(outcome.trajectory_id)
        except (DurableTrajectoryError, OSError, ValueError) as exc:
            manifest_failures += 1
            quarantine_reasons[_safe_error_code(exc)] += 1
            continue
        manifest_verified += 1
        policy_counts[records.manifest.data_policy.license_class.value] += 1
        try:
            guard.authorize_manifest(records.manifest.model_dump(mode="json"), target=target)
        except DatasetExportDenied as exc:
            export_denials += 1
            restricted_export_denials += int(exc.reason_code in {"restricted_no_export", "personal_no_training"})
            quarantine_reasons[f"export:{exc.reason_code}"] += 1
        turn_count += len(records.transitions)
        tool_count += sum(event.parsed_decision.skill_name is not None for event in records.transitions)
        child_turns += len(records.child_transitions)
        if scenario_by_id.get(outcome.scenario_id, None) and scenario_by_id[outcome.scenario_id].requires_child_transitions:
            child_covered_runs += int(bool(records.child_transitions))
        for event in records.transitions:
            if event.error is not None:
                quarantine_reasons[event.error.code] += 1
                acl_violations += int(_is_acl_violation(event.error.code))
        for child in records.child_transitions:
            if child.error_code:
                quarantine_reasons[child.error_code] += 1
                acl_violations += int(_is_acl_violation(child.error_code))
            if child.model_turn is not None:
                model = child.model_turn
                model_turn_count += 1
                tokenized_turns += int(model.token_ids is not None and len(model.token_ids) > 0)
                role_spanned_turns += int(bool(model.token_role_spans))
                versioned_turns += int(_has_complete_runtime_provenance(model.model_dump(mode="json")))
                for span in model.token_role_spans:
                    if span.role in {TokenRole.TOOL_OBSERVATION, TokenRole.USER_SIMULATOR_OBSERVATION}:
                        observation_token_count += span.end - span.start
                        trainable_observation_token_count += (span.end - span.start) * int(span.trainable)
                if model.quarantine_reason:
                    quarantine_reasons[model.quarantine_reason] += 1
                try:
                    guard.authorize_record(model.model_dump(mode="json"), target=target)
                except DatasetExportDenied as exc:
                    export_denials += 1
                    restricted_export_denials += int(exc.reason_code in {"restricted_no_export", "personal_no_training"})
                    quarantine_reasons[f"export:{exc.reason_code}"] += 1
        for model in records.model_records:
            model_turn_count += 1
            tokenized_turns += int(model.token_ids is not None and len(model.token_ids) > 0)
            role_spanned_turns += int(bool(model.token_role_spans))
            versioned_turns += int(_has_complete_runtime_provenance(model.model_dump(mode="json")))
            for span in model.token_role_spans:
                if span.role in {TokenRole.TOOL_OBSERVATION, TokenRole.USER_SIMULATOR_OBSERVATION}:
                    observation_token_count += span.end - span.start
                    trainable_observation_token_count += (span.end - span.start) * int(span.trainable)
            if model.quarantine_reason:
                quarantine_reasons[model.quarantine_reason] += 1
            try:
                guard.authorize_record(model.model_dump(mode="json"), target=target)
            except DatasetExportDenied as exc:
                export_denials += 1
                restricted_export_denials += int(exc.reason_code in {"restricted_no_export", "personal_no_training"})
                quarantine_reasons[f"export:{exc.reason_code}"] += 1

    queued_values = [outcome.queued_duration_ms for outcome in outcomes]
    replay_checked = sum(outcome.replay_consistent is not None for outcome in outcomes)
    replay_consistent = sum(outcome.replay_consistent is True for outcome in outcomes)
    invalid_citations = citation_checked - citation_valid
    long_queued = sum(value > long_queue_threshold_ms for value in queued_values)
    uncompleted = report.requested_count - len(completed)

    if report.requested_count != required_count:
        failures.append("pilot_count")
    if len(outcomes) != report.requested_count or uncompleted != 0:
        failures.append("run_completion")
    if long_queued:
        failures.append("long_queued")
    if manifest_failures or manifest_verified != len(completed):
        failures.append("manifest_verification")
    if model_turn_count == 0 or tokenized_turns != model_turn_count:
        failures.append("model_token_coverage")
    if model_turn_count == 0 or role_spanned_turns != model_turn_count:
        failures.append("role_span_coverage")
    if trainable_observation_token_count:
        failures.append("tool_observation_trainability")
    if model_turn_count == 0 or versioned_turns != model_turn_count:
        failures.append("model_prompt_policy_version_coverage")
    if required_child_runs and child_covered_runs != required_child_runs:
        failures.append("child_transition_coverage")
    if replay_checked != report.requested_count or replay_consistent / max(replay_checked, 1) < 0.99:
        failures.append("replay_consistency")
    if acl_violations:
        failures.append("acl_violation")
    if invalid_citations:
        failures.append("invalid_citation")
    if export_denials:
        failures.append("export_guard")
    if not ci_passed:
        failures.append("ci")
    if not mysql_migration_verified:
        failures.append("mysql_migration")

    return PilotGateReport.build(
        pilot_report_hash=report.content_hash,
        export_target=target,
        required_count=required_count,
        run_completion={
            "requested": report.requested_count,
            "reported": len(outcomes),
            "completed": len(completed),
            "not_terminal": max(uncompleted, 0),
        },
        queued_duration={
            "total_ms": sum(queued_values),
            "max_ms": max(queued_values, default=0.0),
            "long_queued": long_queued,
        },
        turn_count=turn_count,
        tool_count=tool_count,
        token_coverage={"covered": tokenized_turns, "total": model_turn_count},
        role_span_coverage={"covered": role_spanned_turns, "total": model_turn_count},
        tool_observation_trainability={
            "observation_tokens": observation_token_count,
            "trainable_observation_tokens": trainable_observation_token_count,
        },
        child_transition_coverage={
            "required_runs": required_child_runs,
            "covered_runs": child_covered_runs,
            "child_transition_count": child_turns,
        },
        version_coverage={"covered": versioned_turns, "total": model_turn_count},
        citation_validity={"checked": citation_checked, "valid": citation_valid, "invalid": invalid_citations},
        replay_result={"checked": replay_checked, "consistent": replay_consistent},
        data_classification=dict(sorted(policy_counts.items())),
        quarantine_reasons=dict(sorted(quarantine_reasons.items())),
        api_cost=sum(outcome.api_cost for outcome in outcomes),
        gpu_metadata={
            "cost": sum(outcome.gpu_cost for outcome in outcomes),
            "seconds": sum(outcome.gpu_seconds for outcome in outcomes),
        },
        manifest_verification={"verified": manifest_verified, "failed": manifest_failures},
        acl_violations=acl_violations,
        invalid_citations=invalid_citations,
        restricted_export_denials=restricted_export_denials,
        ci_passed=ci_passed,
        mysql_migration_verified=mysql_migration_verified,
        gate_passed=not failures,
        failed_gates=failures,
    )


def _is_acl_violation(code: str) -> bool:
    normalized = code.strip().lower()
    return normalized in {"acl_violation", "permission_escalation", "unauthorized_access"}


def _safe_error_code(error: Exception) -> str:
    code = getattr(error, "reason_code", None)
    return str(code) if isinstance(code, str) and code.strip() else "trajectory_validation_failed"


def _has_complete_runtime_provenance(value: dict[str, object]) -> bool:
    required_fields = (
        "model_id",
        "policy_version",
        "prompt_template_hash",
        "skill_catalog_hash",
        "retriever_version",
        "environment_snapshot_id",
        "environment_snapshot_hash",
    )
    fields = [value.get(field_name) for field_name in required_fields]
    return all(
        isinstance(field, str)
        and field.strip()
        and not field.startswith("legacy-unavailable-")
        and field != "unconfigured-retriever"
        for field in fields
    )
