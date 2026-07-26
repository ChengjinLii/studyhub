"""Canonical Transition and Model-I/O JSONL export.

The sink is deliberately injected into :class:`AgentKernel` rather than made a
new runtime scheduler.  It observes already-validated transitions, preserves
the rollout's original token IDs, and never re-tokenizes text.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.state import StateDelta
from app.agentic_platform.domain.transition import AgentTransitionEvent, TokenRoleSpan


class TrajectoryExportError(RuntimeError):
    pass


class TrajectoryCorruptionError(TrajectoryExportError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class TokenTraceValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TrajectoryPaths:
    trajectory_id: str
    transitions_path: Path
    model_io_path: Path
    manifest_path: Path
    quarantine_root: Path


class ModelIORecord(DomainModel):
    """Token-preserving training view of one canonical transition.

    Context, observations, and raw model output remain durable references.  The
    record does not copy a prompt or chain-of-thought into the JSONL dataset.
    """

    schema_version: str = "1.0"
    trajectory_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    transition_id: str = Field(min_length=1, max_length=128)
    turn_index: int = Field(ge=0)
    environment_snapshot_id: str = Field(min_length=1, max_length=128)
    state_before_hash: str = Field(min_length=1, max_length=128)
    state_after_hash: str = Field(min_length=1, max_length=128)
    state_abstract_key: str = Field(min_length=1, max_length=256)
    policy_version: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str | None = Field(default=None, max_length=256)
    context_view_ref: ArtifactRef
    raw_model_output_ref: ArtifactRef | None = None
    observation_ref: ArtifactRef | None = None
    parsed_decision: AgentDecision
    state_delta: StateDelta
    reward_facts: RewardFacts
    token_ids: list[int]
    token_logprobs: list[float] | None = None
    token_role_spans: list[TokenRoleSpan] = Field(default_factory=list)
    trainable_token_mask: list[bool]
    training_eligible: bool

    @field_validator("token_ids")
    @classmethod
    def validate_token_ids(cls, token_ids: list[int]) -> list[int]:
        if any(token_id < 0 for token_id in token_ids):
            raise ValueError("token IDs must be non-negative")
        return token_ids

    @model_validator(mode="after")
    def validate_token_contract(self) -> "ModelIORecord":
        if self.token_logprobs is not None and len(self.token_logprobs) != len(self.token_ids):
            raise ValueError("token logprobs must align with raw token IDs")
        if any(span.end > len(self.token_ids) for span in self.token_role_spans):
            raise ValueError("token role span exceeds raw token IDs")
        expected_mask = trainable_token_mask(self.token_ids, self.token_role_spans)
        if self.trainable_token_mask != expected_mask:
            raise ValueError("trainable token mask must exactly match token role spans")
        return self

    @classmethod
    def from_transition(cls, event: AgentTransitionEvent) -> "ModelIORecord | None":
        """Build an I/O record without deriving token IDs from any text."""

        if event.token_ids is None:
            return None
        token_ids = list(event.token_ids)
        spans = [span.model_copy(deep=True) for span in event.token_role_spans]
        return cls(
            trajectory_id=trajectory_id_for_event(event),
            thread_id=event.thread_id,
            run_id=event.run_id,
            transition_id=event.transition_id,
            turn_index=event.turn_index,
            environment_snapshot_id=event.environment_snapshot_id,
            state_before_hash=event.state_before_hash,
            state_after_hash=event.state_after_hash,
            state_abstract_key=event.state_abstract_key,
            policy_version=event.policy_version,
            model_id=event.model_id,
            model_revision=event.model_revision,
            context_view_ref=event.context_view_ref.model_copy(deep=True),
            raw_model_output_ref=event.raw_model_output_ref.model_copy(deep=True) if event.raw_model_output_ref else None,
            observation_ref=event.observation_ref.model_copy(deep=True) if event.observation_ref else None,
            parsed_decision=event.parsed_decision.model_copy(deep=True),
            state_delta=event.state_delta.model_copy(deep=True),
            reward_facts=event.reward_facts.model_copy(deep=True),
            token_ids=token_ids,
            token_logprobs=list(event.token_logprobs) if event.token_logprobs is not None else None,
            token_role_spans=spans,
            trainable_token_mask=trainable_token_mask(token_ids, spans),
            training_eligible=event.reward_facts.trainable and event.reward_facts.quarantine_reason is None,
        )


class TrajectoryManifest(DomainModel):
    """Small integrity manifest for one isolated thread/run trajectory."""

    schema_version: str = "1.0"
    trajectory_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    environment_snapshot_ids: list[str] = Field(min_length=1)
    transition_count: int = Field(ge=1)
    model_io_count: int = Field(ge=0)
    transition_ids: list[str] = Field(min_length=1)
    first_state_hash: str = Field(min_length=1, max_length=128)
    final_state_hash: str = Field(min_length=1, max_length=128)
    transitions_sha256: str = Field(min_length=1, max_length=128)
    model_io_sha256: str | None = Field(default=None, min_length=1, max_length=128)
    content_hash: str = Field(min_length=1, max_length=128)

    @field_validator("environment_snapshot_ids", "transition_ids")
    @classmethod
    def validate_unique_nonblank_values(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("manifest values must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("manifest values must be unique")
        return values

    @model_validator(mode="after")
    def validate_manifest(self) -> "TrajectoryManifest":
        if self.transition_count != len(self.transition_ids):
            raise ValueError("manifest transition count must match transition IDs")
        if self.content_hash != self._content_hash():
            raise ValueError("manifest content hash does not match manifest fields")
        return self

    @classmethod
    def build(
        cls,
        events: list[AgentTransitionEvent],
        model_records: list[ModelIORecord],
        *,
        transitions_sha256: str,
        model_io_sha256: str | None,
    ) -> "TrajectoryManifest":
        if not events:
            raise ValueError("cannot build a trajectory manifest without transitions")
        first = events[0]
        data = {
            "trajectory_id": trajectory_id_for_event(first),
            "thread_id": first.thread_id,
            "run_id": first.run_id,
            "environment_snapshot_ids": _ordered_unique(event.environment_snapshot_id for event in events),
            "transition_count": len(events),
            "model_io_count": len(model_records),
            "transition_ids": [event.transition_id for event in events],
            "first_state_hash": first.state_before_hash,
            "final_state_hash": events[-1].state_after_hash,
            "transitions_sha256": transitions_sha256,
            "model_io_sha256": model_io_sha256,
        }
        content_hash = canonical_hash({"schema_version": "1.0", **data})
        return cls(**data, content_hash=content_hash)

    def _content_hash(self) -> str:
        return canonical_hash(
            {
                "schema_version": self.schema_version,
                "trajectory_id": self.trajectory_id,
                "thread_id": self.thread_id,
                "run_id": self.run_id,
                "environment_snapshot_ids": self.environment_snapshot_ids,
                "transition_count": self.transition_count,
                "model_io_count": self.model_io_count,
                "transition_ids": self.transition_ids,
                "first_state_hash": self.first_state_hash,
                "final_state_hash": self.final_state_hash,
                "transitions_sha256": self.transitions_sha256,
                "model_io_sha256": self.model_io_sha256,
            }
        )


class TrajectoryQuarantineRecord(DomainModel):
    schema_version: str = "1.0"
    trajectory_id: str = Field(min_length=1, max_length=128)
    reason_code: str = Field(min_length=1, max_length=128)


def trajectory_id_for_event(event: AgentTransitionEvent) -> str:
    """Derive a path-safe ID that isolates trajectories by thread and run."""

    return f"trajectory_{canonical_hash({'thread_id': event.thread_id, 'run_id': event.run_id})[:40]}"


def trainable_token_mask(token_ids: list[int], spans: list[TokenRoleSpan]) -> list[bool]:
    """Build a loss mask from recorded roles, never from reconstructed text."""

    mask = [False] * len(token_ids)
    previous_end = 0
    for span in sorted(spans, key=lambda item: (item.start, item.end)):
        if span.start < previous_end:
            raise TokenTraceValidationError("token_role_spans_overlap")
        if span.end > len(token_ids):
            raise TokenTraceValidationError("token_role_span_out_of_bounds")
        for index in range(span.start, span.end):
            mask[index] = span.trainable
        previous_end = span.end
    return mask


class TransitionJsonlSink:
    """Filesystem sink compatible with the runtime's async ``TransitionSink``.

    Writes are isolated by ``thread_id`` + ``run_id``.  A malformed line,
    checksum-invalid manifest, or incompatible model-I/O entry moves the entire
    trajectory to a dedicated quarantine directory before a fresh trace starts.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def emit(self, event: AgentTransitionEvent) -> None:
        immutable_event = event.model_copy(deep=True)
        paths = self.paths_for_event(immutable_event)
        lock = await self._lock_for(paths.trajectory_id)
        async with lock:
            self._emit_sync(immutable_event, paths)

    def paths_for_event(self, event: AgentTransitionEvent) -> TrajectoryPaths:
        trajectory_id = trajectory_id_for_event(event)
        return TrajectoryPaths(
            trajectory_id=trajectory_id,
            transitions_path=self.root / "transitions" / f"{trajectory_id}.jsonl",
            model_io_path=self.root / "model_io" / f"{trajectory_id}.jsonl",
            manifest_path=self.root / "manifests" / f"{trajectory_id}.json",
            quarantine_root=self.root / "quarantine",
        )

    def manifest_for_event(self, event: AgentTransitionEvent) -> TrajectoryManifest | None:
        path = self.paths_for_event(event).manifest_path
        if not path.exists():
            return None
        try:
            return TrajectoryManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise TrajectoryCorruptionError("invalid_manifest") from exc

    async def _lock_for(self, trajectory_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(trajectory_id, asyncio.Lock())

    def _emit_sync(self, event: AgentTransitionEvent, paths: TrajectoryPaths) -> None:
        if event.reward_facts.quarantine_reason is not None:
            self._quarantine(paths, "runtime_quarantine", rejected_event=event)
            return
        try:
            model_record = ModelIORecord.from_transition(event)
        except (TokenTraceValidationError, ValidationError, ValueError) as exc:
            self._quarantine(paths, "invalid_token_trace", rejected_event=event)
            return
        try:
            events, model_records = self._load_existing(paths)
        except TrajectoryCorruptionError as exc:
            self._quarantine(paths, exc.reason_code)
            events, model_records = [], []

        existing_by_id = {existing.transition_id: existing for existing in events}
        existing = existing_by_id.get(event.transition_id)
        if existing is not None and existing.canonical_hash() != event.canonical_hash():
            self._quarantine(paths, "transition_id_collision", rejected_event=event)
            events, model_records, existing = [], [], None

        self._ensure_parent_directories(paths)
        if existing is None:
            self._append_json_line(paths.transitions_path, event)
            events.append(event.model_copy(deep=True))
        if model_record is not None:
            known_model_records = {record.transition_id: record for record in model_records}
            known = known_model_records.get(model_record.transition_id)
            if known is None:
                self._append_json_line(paths.model_io_path, model_record)
                model_records.append(model_record.model_copy(deep=True))
            elif known.model_dump(mode="json") != model_record.model_dump(mode="json"):
                self._quarantine(paths, "model_io_transition_mismatch", rejected_event=event)
                self._emit_sync(event, paths)
                return
        self._write_manifest(paths, events, model_records)

    def _load_existing(self, paths: TrajectoryPaths) -> tuple[list[AgentTransitionEvent], list[ModelIORecord]]:
        events = self._read_transition_events(paths.transitions_path)
        model_records = self._read_model_io_records(paths.model_io_path)
        if paths.manifest_path.exists():
            try:
                manifest = TrajectoryManifest.model_validate_json(paths.manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError) as exc:
                raise TrajectoryCorruptionError("invalid_manifest") from exc
            if manifest.trajectory_id != paths.trajectory_id:
                raise TrajectoryCorruptionError("manifest_trajectory_mismatch")
        self._validate_loaded_records(paths, events, model_records)
        return events, model_records

    def _read_transition_events(self, path: Path) -> list[AgentTransitionEvent]:
        if not path.exists():
            return []
        records: list[AgentTransitionEvent] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    raise TrajectoryCorruptionError("blank_transition_jsonl_line")
                records.append(AgentTransitionEvent.model_validate_json(line))
        except TrajectoryCorruptionError:
            raise
        except (OSError, ValidationError, ValueError) as exc:
            raise TrajectoryCorruptionError("invalid_transition_jsonl") from exc
        return records

    def _read_model_io_records(self, path: Path) -> list[ModelIORecord]:
        if not path.exists():
            return []
        records: list[ModelIORecord] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    raise TrajectoryCorruptionError("blank_model_io_jsonl_line")
                records.append(ModelIORecord.model_validate_json(line))
        except TrajectoryCorruptionError:
            raise
        except (OSError, ValidationError, ValueError) as exc:
            raise TrajectoryCorruptionError("invalid_model_io_jsonl") from exc
        return records

    @staticmethod
    def _validate_loaded_records(
        paths: TrajectoryPaths,
        events: list[AgentTransitionEvent],
        model_records: list[ModelIORecord],
    ) -> None:
        event_by_id: dict[str, AgentTransitionEvent] = {}
        for event in events:
            if trajectory_id_for_event(event) != paths.trajectory_id:
                raise TrajectoryCorruptionError("transition_trajectory_mismatch")
            if event.transition_id in event_by_id:
                raise TrajectoryCorruptionError("duplicate_transition_id")
            event_by_id[event.transition_id] = event
        model_by_id: dict[str, ModelIORecord] = {}
        for record in model_records:
            if record.trajectory_id != paths.trajectory_id:
                raise TrajectoryCorruptionError("model_io_trajectory_mismatch")
            if record.transition_id in model_by_id:
                raise TrajectoryCorruptionError("duplicate_model_io_transition_id")
            event = event_by_id.get(record.transition_id)
            if event is None:
                raise TrajectoryCorruptionError("orphaned_model_io_record")
            try:
                expected = ModelIORecord.from_transition(event)
            except (TokenTraceValidationError, ValidationError, ValueError) as exc:
                raise TrajectoryCorruptionError("invalid_token_trace") from exc
            if expected is None or expected.model_dump(mode="json") != record.model_dump(mode="json"):
                raise TrajectoryCorruptionError("model_io_transition_mismatch")
            model_by_id[record.transition_id] = record

    def _write_manifest(
        self,
        paths: TrajectoryPaths,
        events: list[AgentTransitionEvent],
        model_records: list[ModelIORecord],
    ) -> None:
        manifest = TrajectoryManifest.build(
            events,
            model_records,
            transitions_sha256=_file_sha256(paths.transitions_path),
            model_io_sha256=_file_sha256(paths.model_io_path) if paths.model_io_path.exists() else None,
        )
        rendered = canonical_json(manifest, exclude_fields=()) + "\n"
        temporary = paths.manifest_path.with_name(f".{paths.manifest_path.name}.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(paths.manifest_path)

    @staticmethod
    def _append_json_line(path: Path, model: DomainModel) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(model, exclude_fields=()))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _ensure_parent_directories(paths: TrajectoryPaths) -> None:
        paths.transitions_path.parent.mkdir(parents=True, exist_ok=True)
        paths.model_io_path.parent.mkdir(parents=True, exist_ok=True)
        paths.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def _quarantine(
        self,
        paths: TrajectoryPaths,
        reason_code: str,
        *,
        rejected_event: AgentTransitionEvent | None = None,
    ) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        quarantine_dir = paths.quarantine_root / f"{paths.trajectory_id}-{stamp}-{canonical_hash(reason_code)[:12]}"
        quarantine_dir.mkdir(parents=True, exist_ok=False)
        for source in (paths.transitions_path, paths.model_io_path, paths.manifest_path):
            if source.exists():
                source.replace(quarantine_dir / source.name)
        record = TrajectoryQuarantineRecord(trajectory_id=paths.trajectory_id, reason_code=reason_code)
        (quarantine_dir / "quarantine.json").write_text(
            canonical_json(record, exclude_fields=()) + "\n",
            encoding="utf-8",
        )
        if rejected_event is not None:
            (quarantine_dir / "rejected-transition.jsonl").write_text(
                canonical_json(rejected_event, exclude_fields=()) + "\n",
                encoding="utf-8",
            )


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    known: set[str] = set()
    for value in values:
        rendered = str(value)
        if rendered not in known:
            result.append(rendered)
            known.add(rendered)
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65_536), b""):
            digest.update(block)
    return digest.hexdigest()
