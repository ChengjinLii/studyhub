"""Open, manifest-driven orchestration for bounded Agent pilot runs.

The collection layer does not encode a workflow or action script.  A trusted
local runner plugin receives each scenario and may use any registered policy,
Skill, and Snapshot environment.  This module only provides bounded
concurrency, resumability, durable outcome metadata, and the data-policy
contract needed by the downstream gate.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from pydantic import Field, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.data_policy import TrainingDataPolicy
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json


class PilotConfigurationError(ValueError):
    pass


class PilotOutcomeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PilotScenario(DomainModel):
    schema_version: str = "1.0"
    scenario_id: str = Field(min_length=1, max_length=128)
    payload: dict[str, object] = Field(default_factory=dict)
    data_policy: TrainingDataPolicy = Field(default_factory=TrainingDataPolicy.internal_eval_only)
    requires_child_transitions: bool = False

    @field_validator("scenario_id")
    @classmethod
    def reject_blank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scenario_id must not be blank")
        return value


class PilotScenarioManifest(DomainModel):
    """One bounded batch and a trusted plugin that can execute it locally."""

    schema_version: str = "1.0"
    trajectory_root: str = Field(min_length=1, max_length=2_048)
    runner: str = Field(min_length=3, max_length=512)
    scenarios: list[PilotScenario] = Field(min_length=1)

    @field_validator("trajectory_root", "runner")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("manifest value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_unique_scenarios(self) -> "PilotScenarioManifest":
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("pilot scenario IDs must be unique")
        if ":" not in self.runner:
            raise ValueError("pilot runner must use module:callable syntax")
        return self

    def manifest_hash(self) -> str:
        return canonical_hash(self, exclude_fields=())


class PilotScenarioOutcome(DomainModel):
    schema_version: str = "1.0"
    scenario_id: str = Field(min_length=1, max_length=128)
    status: PilotOutcomeStatus
    trajectory_id: str | None = Field(default=None, max_length=128)
    queued_duration_ms: float = Field(default=0.0, ge=0.0)
    turn_count: int = Field(default=0, ge=0)
    tool_count: int = Field(default=0, ge=0)
    replay_consistent: bool | None = None
    citation_valid: bool | None = None
    api_cost: float = Field(default=0.0, ge=0.0)
    gpu_cost: float = Field(default=0.0, ge=0.0)
    gpu_seconds: float = Field(default=0.0, ge=0.0)
    error_code: str | None = Field(default=None, max_length=128)
    data_policy: TrainingDataPolicy

    @field_validator("scenario_id", "trajectory_id", "error_code")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("outcome text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> "PilotScenarioOutcome":
        if self.status == PilotOutcomeStatus.COMPLETED and self.trajectory_id is None:
            raise ValueError("completed pilot outcomes require a trajectory_id")
        if self.status != PilotOutcomeStatus.COMPLETED and self.trajectory_id is not None:
            raise ValueError("non-completed pilot outcomes must not claim a trajectory_id")
        return self


class PilotRunReport(DomainModel):
    schema_version: str = "1.0"
    manifest_hash: str = Field(min_length=64, max_length=64)
    provider: str = Field(min_length=1, max_length=256)
    requested_count: int = Field(gt=0)
    concurrency: int = Field(gt=0, le=128)
    trajectory_root: str = Field(min_length=1, max_length=2_048)
    started_at: datetime
    completed_at: datetime
    outcomes: list[PilotScenarioOutcome] = Field(default_factory=list)
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("provider", "trajectory_root", "manifest_hash", "content_hash")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pilot report text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_hash_and_unique_outcomes(self) -> "PilotRunReport":
        ids = [outcome.scenario_id for outcome in self.outcomes]
        if len(ids) != len(set(ids)):
            raise ValueError("pilot outcomes must be unique per scenario")
        if self.content_hash != self._content_hash():
            raise ValueError("pilot report content hash does not match its fields")
        return self

    @classmethod
    def build(
        cls,
        *,
        manifest: PilotScenarioManifest,
        provider: str,
        requested_count: int,
        concurrency: int,
        started_at: datetime,
        outcomes: list[PilotScenarioOutcome],
    ) -> "PilotRunReport":
        completed_at = datetime.now(UTC)
        data = {
            "manifest_hash": manifest.manifest_hash(),
            "provider": provider,
            "requested_count": requested_count,
            "concurrency": concurrency,
            "trajectory_root": manifest.trajectory_root,
            "started_at": started_at,
            "completed_at": completed_at,
            "outcomes": outcomes,
        }
        return cls(**data, content_hash=canonical_hash({"schema_version": "1.0", **data}, exclude_fields=()))

    def _content_hash(self) -> str:
        return canonical_hash(
            {
                "schema_version": self.schema_version,
                "manifest_hash": self.manifest_hash,
                "provider": self.provider,
                "requested_count": self.requested_count,
                "concurrency": self.concurrency,
                "trajectory_root": self.trajectory_root,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "outcomes": self.outcomes,
            },
            exclude_fields=(),
        )


PilotRunner = Callable[..., object]


async def run_pilot(
    manifest: PilotScenarioManifest,
    *,
    count: int,
    concurrency: int,
    provider: str,
    output_dir: str | Path,
    resume: bool = False,
) -> PilotRunReport:
    """Run at most ``count`` scenarios through a trusted local runner plugin.

    The plugin is intentionally the extension point: it can construct an open
    Agent policy, choose a model provider, and drive dynamic snapshots without
    this collection module deciding which actions are legal.  The output must
    point to a durable trajectory generated by the runtime.
    """

    if count <= 0:
        raise PilotConfigurationError("pilot_count_must_be_positive")
    if concurrency <= 0 or concurrency > 128:
        raise PilotConfigurationError("pilot_concurrency_out_of_range")
    if not provider.strip():
        raise PilotConfigurationError("pilot_provider_must_not_be_blank")
    if count > len(manifest.scenarios):
        raise PilotConfigurationError("pilot_count_exceeds_manifest_scenarios")

    output = Path(output_dir)
    report_path = output / "pilot-run.json"
    selected = manifest.scenarios[:count]
    previous = _load_resume_report(report_path, manifest=manifest, provider=provider) if resume else None
    completed = {
        outcome.scenario_id: outcome.model_copy(deep=True)
        for outcome in (previous.outcomes if previous is not None else [])
        if outcome.status == PilotOutcomeStatus.COMPLETED
    }
    runner = _load_runner(manifest.runner)
    started_at = datetime.now(UTC)
    semaphore = asyncio.Semaphore(concurrency)

    async def execute(scenario: PilotScenario) -> PilotScenarioOutcome:
        if scenario.scenario_id in completed:
            return completed[scenario.scenario_id]
        async with semaphore:
            try:
                raw = runner(
                    scenario=scenario.model_dump(mode="json"),
                    provider=provider,
                    trajectory_root=manifest.trajectory_root,
                    output_dir=str(output),
                )
                if inspect.isawaitable(raw):
                    raw = await raw
                if not isinstance(raw, dict):
                    raise PilotConfigurationError("pilot_runner_must_return_object")
                values = dict(raw)
                values["scenario_id"] = scenario.scenario_id
                values.setdefault("data_policy", scenario.data_policy.model_dump(mode="json"))
                outcome = PilotScenarioOutcome.model_validate(values)
                if outcome.data_policy != scenario.data_policy:
                    raise PilotConfigurationError("pilot_runner_data_policy_mismatch")
                return outcome
            except PilotConfigurationError:
                raise
            except Exception:  # noqa: BLE001 - report a stable public failure code only.
                return PilotScenarioOutcome(
                    scenario_id=scenario.scenario_id,
                    status=PilotOutcomeStatus.FAILED,
                    error_code="pilot_runner_error",
                    data_policy=scenario.data_policy.model_copy(deep=True),
                )

    outcomes = list(await asyncio.gather(*(execute(scenario) for scenario in selected)))
    report = PilotRunReport.build(
        manifest=manifest,
        provider=provider,
        requested_count=count,
        concurrency=concurrency,
        started_at=started_at,
        outcomes=outcomes,
    )
    _atomic_write_json(report_path, report)
    return report


def load_pilot_manifest(path: str | Path) -> PilotScenarioManifest:
    try:
        return PilotScenarioManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PilotConfigurationError("invalid_pilot_scenario_manifest") from exc


def load_pilot_report(path: str | Path) -> PilotRunReport:
    try:
        return PilotRunReport.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PilotConfigurationError("invalid_pilot_run_report") from exc


def _load_runner(reference: str) -> PilotRunner:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise PilotConfigurationError("invalid_pilot_runner_reference")
    try:
        runner = getattr(importlib.import_module(module_name), attribute)
    except (AttributeError, ImportError) as exc:
        raise PilotConfigurationError("pilot_runner_unavailable") from exc
    if not callable(runner):
        raise PilotConfigurationError("pilot_runner_not_callable")
    return runner


def _load_resume_report(path: Path, *, manifest: PilotScenarioManifest, provider: str) -> PilotRunReport | None:
    if not path.exists():
        return None
    report = load_pilot_report(path)
    if report.manifest_hash != manifest.manifest_hash() or report.provider != provider:
        raise PilotConfigurationError("pilot_resume_report_mismatch")
    return report


def _atomic_write_json(path: Path, value: DomainModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(canonical_json(value, exclude_fields=()) + "\n", encoding="utf-8")
    temporary.replace(path)
