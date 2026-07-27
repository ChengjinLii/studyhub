"""Immutable, recoverable trajectory segments for production Agent execution.

Segments are never appended to a shared JSONL file.  Each canonical transition
and model-I/O record is written through a temporary file, fsynced, and atomically
renamed.  A manifest is only advanced after all linked records are present, so a
worker kill between ``Transition`` and ``ModelIO`` leaves recoverable immutable
bytes rather than a silently truncated trajectory.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from app.agentic_platform.deepresearch.transition import DeepResearchChildTransition
from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json
from app.agentic_platform.domain.transition import AgentTransitionEvent, ModelTurnEvent
from app.agentic_platform.simulation.trajectory import (
    ModelIORecord,
    TokenTraceValidationError,
    trajectory_id_for_event,
    trajectory_id_for_model_turn,
)


class DurableTrajectoryError(RuntimeError):
    """A trajectory cannot safely be persisted or recovered."""


class TransitionIdCollisionError(DurableTrajectoryError):
    pass


class ModelTurnIdCollisionError(DurableTrajectoryError):
    pass


class ResearchChildTransitionIdCollisionError(DurableTrajectoryError):
    pass


class DurableSegmentKind(StrEnum):
    TRANSITION = "transition"
    MODEL_IO = "model_io"
    RESEARCH_CHILD = "research_child"


_SEGMENT_FILENAME = re.compile(r"^(?P<sequence>\d{8})\.(?P<kind>transition|model_io|research_child)\.json$")


class DurableTrajectorySegment(DomainModel):
    """One immutable file recorded by a trajectory manifest."""

    schema_version: str = "1.0"
    sequence: int = Field(ge=1)
    kind: DurableSegmentKind
    filename: str = Field(min_length=1, max_length=256)
    sha256: str = Field(min_length=64, max_length=64)
    transition_id: str | None = Field(default=None, max_length=128)
    model_turn_id: str | None = Field(default=None, max_length=128)
    child_transition_id: str | None = Field(default=None, max_length=128)

    @field_validator("filename", "sha256", "transition_id", "model_turn_id", "child_transition_id")
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_identifier_for_kind(self) -> "DurableTrajectorySegment":
        identifiers = [self.transition_id, self.model_turn_id, self.child_transition_id]
        if sum(value is not None for value in identifiers) != 1:
            raise ValueError("a segment must have exactly one record identifier")
        required_by_kind = {
            DurableSegmentKind.TRANSITION: self.transition_id,
            DurableSegmentKind.MODEL_IO: self.model_turn_id,
            DurableSegmentKind.RESEARCH_CHILD: self.child_transition_id,
        }
        if required_by_kind[self.kind] is None:
            raise ValueError("segment identifier does not match its kind")
        expected = f"{self.sequence:08d}.{self.kind.value}.json"
        if self.filename != expected:
            raise ValueError("segment filename does not match its sequence and kind")
        return self


class DurableTrajectoryManifest(DomainModel):
    """Checksum manifest for all immutable records in one thread/run path."""

    schema_version: str = "1.0"
    trajectory_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    segments: list[DurableTrajectorySegment] = Field(default_factory=list)
    transition_ids: list[str] = Field(default_factory=list)
    model_turn_ids: list[str] = Field(default_factory=list)
    child_transition_ids: list[str] = Field(default_factory=list)
    transition_count: int = Field(default=0, ge=0)
    model_io_count: int = Field(default=0, ge=0)
    child_transition_count: int = Field(default=0, ge=0)
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("trajectory_id", "thread_id", "run_id", "content_hash")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_counts_and_hash(self) -> "DurableTrajectoryManifest":
        if len({(segment.sequence, segment.kind) for segment in self.segments}) != len(self.segments):
            raise ValueError("manifest has duplicate segment slots")
        for values in (self.transition_ids, self.model_turn_ids, self.child_transition_ids):
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError("manifest record IDs must be unique and nonblank")
        if self.transition_count != len(self.transition_ids):
            raise ValueError("manifest transition count does not match IDs")
        if self.model_io_count != len(self.model_turn_ids):
            raise ValueError("manifest model I/O count does not match IDs")
        if self.child_transition_count != len(self.child_transition_ids):
            raise ValueError("manifest child transition count does not match IDs")
        if self.content_hash != self._expected_content_hash():
            raise ValueError("manifest content hash does not match fields")
        return self

    @classmethod
    def build(
        cls,
        *,
        trajectory_id: str,
        thread_id: str,
        run_id: str,
        segments: Iterable[DurableTrajectorySegment],
    ) -> "DurableTrajectoryManifest":
        ordered = sorted(segments, key=lambda item: (item.sequence, item.kind.value))
        transition_ids = [item.transition_id for item in ordered if item.kind == DurableSegmentKind.TRANSITION]
        model_turn_ids = [item.model_turn_id for item in ordered if item.kind == DurableSegmentKind.MODEL_IO]
        child_ids = [item.child_transition_id for item in ordered if item.kind == DurableSegmentKind.RESEARCH_CHILD]
        payload = {
            "trajectory_id": trajectory_id,
            "thread_id": thread_id,
            "run_id": run_id,
            "segments": ordered,
            "transition_ids": [item for item in transition_ids if item is not None],
            "model_turn_ids": [item for item in model_turn_ids if item is not None],
            "child_transition_ids": [item for item in child_ids if item is not None],
            "transition_count": len(transition_ids),
            "model_io_count": len(model_turn_ids),
            "child_transition_count": len(child_ids),
        }
        content_hash = canonical_hash({"schema_version": "1.0", **payload}, exclude_fields=())
        return cls(**payload, content_hash=content_hash)

    def _expected_content_hash(self) -> str:
        return canonical_hash(
            {
                "schema_version": self.schema_version,
                "trajectory_id": self.trajectory_id,
                "thread_id": self.thread_id,
                "run_id": self.run_id,
                "segments": self.segments,
                "transition_ids": self.transition_ids,
                "model_turn_ids": self.model_turn_ids,
                "child_transition_ids": self.child_transition_ids,
                "transition_count": self.transition_count,
                "model_io_count": self.model_io_count,
                "child_transition_count": self.child_transition_count,
            },
            exclude_fields=(),
        )


@dataclass(frozen=True, slots=True)
class DurableTrajectoryPaths:
    trajectory_id: str
    root: Path
    segments_dir: Path
    manifest_path: Path


@dataclass(slots=True)
class _LoadedTrajectory:
    paths: DurableTrajectoryPaths
    thread_id: str
    run_id: str
    segments: list[DurableTrajectorySegment]
    transitions: dict[str, AgentTransitionEvent]
    model_records: dict[str, ModelIORecord]
    child_transitions: dict[str, DeepResearchChildTransition]
    manifest: DurableTrajectoryManifest | None


class DurableTransitionSink:
    """Production sink implementing both Transition and ModelTurn protocols.

    A single worker owns a run through :class:`RunLease` in the execution
    worker.  The per-process locks below protect concurrent async graph tasks;
    immutable IDs and checksums additionally make accidental concurrent writers
    fail closed rather than overwrite one another.
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
            self._emit_transition_sync(immutable_event, paths)

    async def emit_model_turn(self, event: ModelTurnEvent) -> None:
        immutable_event = event.model_copy(deep=True)
        paths = self.paths_for_model_turn(immutable_event)
        lock = await self._lock_for(paths.trajectory_id)
        async with lock:
            self._emit_model_turn_sync(immutable_event, paths)

    def research_child_sink(self, *, thread_id: str, run_id: str) -> "DurableResearchChildTransitionSink":
        trajectory_id = _trajectory_id_for_owner(thread_id=thread_id, run_id=run_id)
        return DurableResearchChildTransitionSink(
            self,
            trajectory_id=trajectory_id,
            thread_id=thread_id,
            run_id=run_id,
        )

    async def emit_research_child(
        self,
        event: DeepResearchChildTransition,
        *,
        trajectory_id: str,
        thread_id: str,
        run_id: str,
    ) -> None:
        immutable_event = event.model_copy(deep=True)
        paths = self.paths_for_trajectory(trajectory_id)
        lock = await self._lock_for(paths.trajectory_id)
        async with lock:
            self._emit_research_child_sync(
                immutable_event,
                paths,
                thread_id=thread_id,
                run_id=run_id,
            )

    def paths_for_event(self, event: AgentTransitionEvent) -> DurableTrajectoryPaths:
        return self.paths_for_trajectory(trajectory_id_for_event(event))

    def paths_for_model_turn(self, event: ModelTurnEvent) -> DurableTrajectoryPaths:
        return self.paths_for_trajectory(trajectory_id_for_model_turn(event))

    def paths_for_trajectory(self, trajectory_id: str) -> DurableTrajectoryPaths:
        if not trajectory_id.startswith("trajectory_"):
            raise ValueError("trajectory_id is invalid")
        root = self.root / trajectory_id
        return DurableTrajectoryPaths(
            trajectory_id=trajectory_id,
            root=root,
            segments_dir=root / "segments",
            manifest_path=root / "manifest.json",
        )

    def load_manifest_for_event(self, event: AgentTransitionEvent) -> DurableTrajectoryManifest:
        return self.load_manifest(self.paths_for_event(event).trajectory_id)

    def load_manifest(self, trajectory_id: str) -> DurableTrajectoryManifest:
        """Load and fully re-verify all manifest files, hashes, and alignment."""

        paths = self.paths_for_trajectory(trajectory_id)
        loaded = self._load(paths, expected_thread_id=None, expected_run_id=None)
        if loaded.manifest is None:
            raise DurableTrajectoryError("trajectory_manifest_missing")
        self._validate_manifest_matches_files(loaded)
        self._validate_alignment(loaded)
        return loaded.manifest.model_copy(deep=True)

    async def _lock_for(self, trajectory_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(trajectory_id, asyncio.Lock())

    def _emit_transition_sync(self, event: AgentTransitionEvent, paths: DurableTrajectoryPaths) -> None:
        loaded = self._load(paths, expected_thread_id=event.thread_id, expected_run_id=event.run_id)
        existing = loaded.transitions.get(event.transition_id)
        if existing is not None:
            if existing.canonical_hash() != event.canonical_hash():
                raise TransitionIdCollisionError(f"transition_id_collision:{event.transition_id}")
            self._write_manifest_if_aligned(loaded)
            return

        sequence = self._next_sequence(loaded)
        segment = self._write_segment(
            paths,
            sequence=sequence,
            kind=DurableSegmentKind.TRANSITION,
            record=event,
        )
        loaded.segments.append(segment)
        loaded.transitions[event.transition_id] = event.model_copy(deep=True)
        self._write_manifest_if_aligned(loaded)

    def _emit_model_turn_sync(self, event: ModelTurnEvent, paths: DurableTrajectoryPaths) -> None:
        try:
            record = ModelIORecord.from_model_turn(event)
        except (TokenTraceValidationError, ValidationError, ValueError) as exc:
            raise DurableTrajectoryError("invalid_model_io_token_trace") from exc
        loaded = self._load(paths, expected_thread_id=event.thread_id, expected_run_id=event.run_id)
        existing = loaded.model_records.get(record.model_turn_id)
        if existing is not None:
            if not _same_model(existing, record):
                raise ModelTurnIdCollisionError(f"model_turn_id_collision:{record.model_turn_id}")
            self._write_manifest_if_aligned(loaded)
            return

        if record.transition_id is not None:
            transition = loaded.transitions.get(record.transition_id)
            if transition is None:
                raise DurableTrajectoryError("model_io_missing_transition")
            expected = _model_record_from_transition(transition)
            if not _same_model(expected, record):
                raise DurableTrajectoryError("model_io_transition_mismatch")
            sequence = self._sequence_for_transition(loaded, record.transition_id)
        else:
            sequence = self._next_sequence(loaded)
        segment = self._write_segment(
            paths,
            sequence=sequence,
            kind=DurableSegmentKind.MODEL_IO,
            record=record,
        )
        loaded.segments.append(segment)
        loaded.model_records[record.model_turn_id] = record.model_copy(deep=True)
        self._write_manifest_if_aligned(loaded)

    def _emit_research_child_sync(
        self,
        event: DeepResearchChildTransition,
        paths: DurableTrajectoryPaths,
        *,
        thread_id: str,
        run_id: str,
    ) -> None:
        loaded = self._load(paths, expected_thread_id=thread_id, expected_run_id=run_id)
        existing = loaded.child_transitions.get(event.child_transition_id)
        if existing is not None:
            if existing.canonical_hash() != event.canonical_hash():
                raise ResearchChildTransitionIdCollisionError(
                    f"research_child_transition_id_collision:{event.child_transition_id}"
                )
            self._write_manifest_if_aligned(loaded)
            return
        segment = self._write_segment(
            paths,
            sequence=self._next_sequence(loaded),
            kind=DurableSegmentKind.RESEARCH_CHILD,
            record=event,
        )
        loaded.segments.append(segment)
        loaded.child_transitions[event.child_transition_id] = event.model_copy(deep=True)
        self._write_manifest_if_aligned(loaded)

    def _load(
        self,
        paths: DurableTrajectoryPaths,
        *,
        expected_thread_id: str | None,
        expected_run_id: str | None,
    ) -> _LoadedTrajectory:
        segments: list[DurableTrajectorySegment] = []
        transitions: dict[str, AgentTransitionEvent] = {}
        model_records: dict[str, ModelIORecord] = {}
        child_transitions: dict[str, DeepResearchChildTransition] = {}
        thread_id = expected_thread_id or ""
        run_id = expected_run_id or ""

        if paths.segments_dir.exists():
            for path in sorted(paths.segments_dir.iterdir(), key=lambda item: item.name):
                if path.name.startswith(".") and path.suffix == ".tmp":
                    continue
                matched = _SEGMENT_FILENAME.fullmatch(path.name)
                if matched is None or not path.is_file():
                    raise DurableTrajectoryError("invalid_trajectory_segment_filename")
                sequence = int(matched.group("sequence"))
                kind = DurableSegmentKind(matched.group("kind"))
                raw = _read_segment_bytes(path)
                if kind == DurableSegmentKind.TRANSITION:
                    record = _parse_transition(raw)
                    if trajectory_id_for_event(record) != paths.trajectory_id:
                        raise DurableTrajectoryError("transition_trajectory_mismatch")
                    thread_id, run_id = _resolve_owner(
                        thread_id,
                        run_id,
                        record.thread_id,
                        record.run_id,
                    )
                    if record.transition_id in transitions:
                        raise DurableTrajectoryError("duplicate_transition_id")
                    transitions[record.transition_id] = record
                    segment = DurableTrajectorySegment(
                        sequence=sequence,
                        kind=kind,
                        filename=path.name,
                        sha256=_sha256(raw),
                        transition_id=record.transition_id,
                    )
                elif kind == DurableSegmentKind.MODEL_IO:
                    record = _parse_model_io(raw)
                    if record.trajectory_id != paths.trajectory_id or trajectory_id_for_model_turn(record) != paths.trajectory_id:
                        raise DurableTrajectoryError("model_io_trajectory_mismatch")
                    thread_id, run_id = _resolve_owner(thread_id, run_id, record.thread_id, record.run_id)
                    if record.model_turn_id in model_records:
                        raise DurableTrajectoryError("duplicate_model_turn_id")
                    model_records[record.model_turn_id] = record
                    segment = DurableTrajectorySegment(
                        sequence=sequence,
                        kind=kind,
                        filename=path.name,
                        sha256=_sha256(raw),
                        model_turn_id=record.model_turn_id,
                    )
                else:
                    record = _parse_research_child(raw)
                    if record.child_transition_id in child_transitions:
                        raise DurableTrajectoryError("duplicate_research_child_transition_id")
                    child_transitions[record.child_transition_id] = record
                    segment = DurableTrajectorySegment(
                        sequence=sequence,
                        kind=kind,
                        filename=path.name,
                        sha256=_sha256(raw),
                        child_transition_id=record.child_transition_id,
                    )
                segments.append(segment)

        if not thread_id or not run_id:
            if paths.manifest_path.exists():
                manifest = _read_manifest(paths.manifest_path)
                thread_id, run_id = manifest.thread_id, manifest.run_id
            elif expected_thread_id and expected_run_id:
                thread_id, run_id = expected_thread_id, expected_run_id
            else:
                raise DurableTrajectoryError("trajectory_owner_unknown")
        if expected_thread_id is not None and thread_id != expected_thread_id:
            raise DurableTrajectoryError("trajectory_thread_owner_mismatch")
        if expected_run_id is not None and run_id != expected_run_id:
            raise DurableTrajectoryError("trajectory_run_owner_mismatch")
        if _trajectory_id_for_owner(thread_id=thread_id, run_id=run_id) != paths.trajectory_id:
            raise DurableTrajectoryError("trajectory_owner_hash_mismatch")

        manifest = _read_manifest(paths.manifest_path) if paths.manifest_path.exists() else None
        return _LoadedTrajectory(
            paths=paths,
            thread_id=thread_id,
            run_id=run_id,
            segments=segments,
            transitions=transitions,
            model_records=model_records,
            child_transitions=child_transitions,
            manifest=manifest,
        )

    def _write_manifest_if_aligned(self, loaded: _LoadedTrajectory) -> None:
        if not self._is_aligned(loaded):
            return
        manifest = DurableTrajectoryManifest.build(
            trajectory_id=loaded.paths.trajectory_id,
            thread_id=loaded.thread_id,
            run_id=loaded.run_id,
            segments=loaded.segments,
        )
        _atomic_write(loaded.paths.manifest_path, _render_json(manifest))
        loaded.manifest = manifest

    def _validate_manifest_matches_files(self, loaded: _LoadedTrajectory) -> None:
        assert loaded.manifest is not None
        manifest = loaded.manifest
        if (
            manifest.trajectory_id != loaded.paths.trajectory_id
            or manifest.thread_id != loaded.thread_id
            or manifest.run_id != loaded.run_id
        ):
            raise DurableTrajectoryError("manifest_trajectory_owner_mismatch")
        actual = sorted(loaded.segments, key=lambda item: (item.sequence, item.kind.value))
        expected = sorted(manifest.segments, key=lambda item: (item.sequence, item.kind.value))
        if [item.model_dump(mode="json") for item in actual] != [item.model_dump(mode="json") for item in expected]:
            raise DurableTrajectoryError("manifest_segment_inventory_mismatch")
        if manifest.transition_ids != [item.transition_id for item in actual if item.transition_id is not None]:
            raise DurableTrajectoryError("manifest_transition_ids_mismatch")
        if manifest.model_turn_ids != [item.model_turn_id for item in actual if item.model_turn_id is not None]:
            raise DurableTrajectoryError("manifest_model_turn_ids_mismatch")
        if manifest.child_transition_ids != [item.child_transition_id for item in actual if item.child_transition_id is not None]:
            raise DurableTrajectoryError("manifest_child_transition_ids_mismatch")

    @staticmethod
    def _validate_alignment(loaded: _LoadedTrajectory) -> None:
        if not DurableTransitionSink._is_aligned(loaded):
            raise DurableTrajectoryError("model_io_transition_alignment_invalid")

    @staticmethod
    def _is_aligned(loaded: _LoadedTrajectory) -> bool:
        linked_models = [record for record in loaded.model_records.values() if record.transition_id is not None]
        if len(linked_models) != len(loaded.transitions):
            return False
        by_transition = {record.transition_id: record for record in linked_models}
        if len(by_transition) != len(linked_models):
            return False
        for transition_id, transition in loaded.transitions.items():
            record = by_transition.get(transition_id)
            if record is None:
                return False
            try:
                expected = _model_record_from_transition(transition)
            except DurableTrajectoryError:
                return False
            if not _same_model(expected, record):
                return False
        return True

    @staticmethod
    def _next_sequence(loaded: _LoadedTrajectory) -> int:
        return max((segment.sequence for segment in loaded.segments), default=0) + 1

    @staticmethod
    def _sequence_for_transition(loaded: _LoadedTrajectory, transition_id: str) -> int:
        for segment in loaded.segments:
            if segment.transition_id == transition_id:
                return segment.sequence
        raise DurableTrajectoryError("transition_segment_missing")

    @staticmethod
    def _write_segment(
        paths: DurableTrajectoryPaths,
        *,
        sequence: int,
        kind: DurableSegmentKind,
        record: DomainModel,
    ) -> DurableTrajectorySegment:
        filename = f"{sequence:08d}.{kind.value}.json"
        target = paths.segments_dir / filename
        rendered = _render_json(record)
        if target.exists():
            raw = _read_segment_bytes(target)
            if raw != rendered:
                raise DurableTrajectoryError("immutable_segment_slot_collision")
        else:
            _atomic_write(target, rendered)
        identifier_kwargs: dict[str, str] = {}
        if kind == DurableSegmentKind.TRANSITION:
            identifier_kwargs["transition_id"] = getattr(record, "transition_id")
        elif kind == DurableSegmentKind.MODEL_IO:
            identifier_kwargs["model_turn_id"] = getattr(record, "model_turn_id")
        else:
            identifier_kwargs["child_transition_id"] = getattr(record, "child_transition_id")
        return DurableTrajectorySegment(
            sequence=sequence,
            kind=kind,
            filename=filename,
            sha256=_sha256(rendered),
            **identifier_kwargs,
        )


class DurableResearchChildTransitionSink:
    """Research graph adapter bound to its owning parent thread/run trajectory."""

    def __init__(
        self,
        parent: DurableTransitionSink,
        *,
        trajectory_id: str,
        thread_id: str,
        run_id: str,
    ) -> None:
        self.parent = parent
        self.trajectory_id = trajectory_id
        self.thread_id = thread_id
        self.run_id = run_id

    async def emit(self, event: DeepResearchChildTransition) -> None:
        await self.parent.emit_research_child(
            event,
            trajectory_id=self.trajectory_id,
            thread_id=self.thread_id,
            run_id=self.run_id,
        )


def _trajectory_id_for_owner(*, thread_id: str, run_id: str) -> str:
    return f"trajectory_{canonical_hash({'thread_id': thread_id, 'run_id': run_id})[:40]}"


def _resolve_owner(current_thread: str, current_run: str, next_thread: str, next_run: str) -> tuple[str, str]:
    if current_thread and current_thread != next_thread:
        raise DurableTrajectoryError("trajectory_thread_owner_mismatch")
    if current_run and current_run != next_run:
        raise DurableTrajectoryError("trajectory_run_owner_mismatch")
    return next_thread, next_run


def _model_record_from_transition(event: AgentTransitionEvent) -> ModelIORecord:
    try:
        return ModelIORecord.from_transition(event)
    except (TokenTraceValidationError, ValidationError, ValueError) as exc:
        raise DurableTrajectoryError("invalid_transition_token_trace") from exc


def _same_model(left: ModelIORecord, right: ModelIORecord) -> bool:
    return canonical_json(left, exclude_fields=()) == canonical_json(right, exclude_fields=())


def _parse_transition(raw: bytes) -> AgentTransitionEvent:
    try:
        return AgentTransitionEvent.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise DurableTrajectoryError("invalid_transition_segment") from exc


def _parse_model_io(raw: bytes) -> ModelIORecord:
    try:
        return ModelIORecord.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise DurableTrajectoryError("invalid_model_io_segment") from exc


def _parse_research_child(raw: bytes) -> DeepResearchChildTransition:
    try:
        return DeepResearchChildTransition.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise DurableTrajectoryError("invalid_research_child_segment") from exc


def _read_manifest(path: Path) -> DurableTrajectoryManifest:
    try:
        return DurableTrajectoryManifest.model_validate_json(_read_segment_bytes(path))
    except (ValidationError, ValueError) as exc:
        raise DurableTrajectoryError("invalid_trajectory_manifest") from exc


def _read_segment_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DurableTrajectoryError("trajectory_segment_unreadable") from exc


def _render_json(value: object) -> bytes:
    return (canonical_json(value, exclude_fields=()) + "\n").encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
