"""Fail-closed recovery state and batch provenance for the pinned AReaL SFT runtime."""

from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.distributed as dist

AUDIT_ROOT_ENV = "STUDYHUB_RECOVERY_AUDIT_ROOT"
START_STEP_ENV = "STUDYHUB_RECOVERY_AUDIT_START_STEP"
SNAPSHOT_STEP_ENV = "STUDYHUB_RECOVERY_SNAPSHOT_STEP"
SNAPSHOT_TARGET_ENV = "STUDYHUB_RECOVERY_SNAPSHOT_TARGET"
SNAPSHOT_REPORT_ENV = "STUDYHUB_RECOVERY_SNAPSHOT_REPORT"


def _rank_world() -> tuple[int, int]:
    if dist.is_available() and dist.is_initialized():
        return dist.get_rank(), dist.get_world_size()
    return int(os.environ.get("RANK", "0")), int(os.environ.get("WORLD_SIZE", "1"))


def _required_int(name: str) -> int:
    raw = os.environ.get(name)
    if raw is None:
        raise RuntimeError(f"missing recovery audit variable: {name}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be non-negative, got {value}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tensor_bytes(tensor: torch.Tensor) -> bytes:
    value = tensor.detach().cpu().contiguous()
    return value.view(torch.uint8).numpy().tobytes()


def _update_digest(digest: Any, value: Any) -> None:
    if torch.is_tensor(value):
        digest.update(b"tensor\0")
        digest.update(str(value.dtype).encode())
        digest.update(b"\0")
        digest.update(json.dumps(list(value.shape)).encode())
        digest.update(b"\0")
        digest.update(_tensor_bytes(value))
    elif isinstance(value, dict):
        digest.update(b"dict\0")
        for key in sorted(value):
            digest.update(str(key).encode())
            digest.update(b"\0")
            _update_digest(digest, value[key])
    elif isinstance(value, (list, tuple)):
        digest.update(f"sequence:{len(value)}\0".encode())
        for item in value:
            _update_digest(digest, item)
    elif value is None:
        digest.update(b"none\0")
    else:
        digest.update(type(value).__name__.encode())
        digest.update(b"\0")
        digest.update(repr(value).encode())
        digest.update(b"\0")


def fingerprint(value: Any) -> str:
    digest = hashlib.sha256()
    _update_digest(digest, value)
    return digest.hexdigest()


def fingerprint_batch(batch: Any) -> dict[str, Any]:
    samples = batch if isinstance(batch, list) else [batch]
    return {
        "batch_sha256": fingerprint(batch),
        "sample_count": len(samples),
        "sample_sha256": [fingerprint(sample) for sample in samples],
        "input_ids_sha256": [
            fingerprint(sample.get("input_ids")) if isinstance(sample, dict) else None
            for sample in samples
        ],
        "loss_mask_sha256": [
            fingerprint(sample.get("loss_mask")) if isinstance(sample, dict) else None
            for sample in samples
        ],
    }


def _rng_payload() -> dict[str, Any]:
    return {
        "schema_version": "studyhub.rng-state.v1",
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
    }


def rng_fingerprint() -> str:
    payload = _rng_payload()
    digest = hashlib.sha256()
    _update_digest(digest, payload["python"])
    numpy_state = payload["numpy"]
    _update_digest(digest, numpy_state[0])
    _update_digest(digest, torch.from_numpy(numpy_state[1].copy()))
    _update_digest(digest, numpy_state[2:])
    _update_digest(digest, payload["torch_cpu"])
    _update_digest(digest, payload["torch_cuda"])
    return digest.hexdigest()


def _atomic_torch_save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("wb") as stream:
        torch.save(payload, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_event(root: Path, rank: int, payload: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rank-{rank}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _trial_root(handler: Any) -> Path:
    recover_info = Path(
        handler.recover_info_path(
            handler.config.experiment_name,
            handler.config.trial_name,
            handler.config.fileroot,
        )
    )
    return recover_info.parent


def _normalized_engines(engine: Any) -> dict[str, Any]:
    return engine if isinstance(engine, dict) else {"default": engine}


def _engine_versions(engine: Any) -> dict[str, int]:
    versions = {}
    for name, value in _normalized_engines(engine).items():
        getter = getattr(value, "get_version", None)
        if not callable(getter):
            raise RuntimeError(f"recovery engine has no get_version(): {name}")
        versions[str(name)] = int(getter())
    return versions


def _set_engine_versions(engine: Any, version: int) -> dict[str, int]:
    for name, value in _normalized_engines(engine).items():
        setter = getattr(value, "set_version", None)
        if not callable(setter):
            raise RuntimeError(f"recovery engine has no set_version(): {name}")
        setter(version)
    return _engine_versions(engine)


def _save_rng_state(recover_info: Path, rank: int, world_size: int) -> dict[str, Any]:
    payload = _rng_payload()
    payload.update({"rank": rank, "world_size": world_size})
    path = recover_info / f"rng_state_rank_{rank}.pt"
    _atomic_torch_save(path, payload)
    return {"path": path.name, "sha256": _sha256(path)}


def _restore_rng_state(recover_info: Path, rank: int, world_size: int) -> dict[str, Any]:
    path = recover_info / f"rng_state_rank_{rank}.pt"
    if not path.is_file():
        raise RuntimeError(f"missing per-rank RNG state: {path}")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("schema_version") != "studyhub.rng-state.v1":
        raise RuntimeError(f"unexpected RNG state schema: {path}")
    if int(payload.get("rank", -1)) != rank or int(payload.get("world_size", -1)) != world_size:
        raise RuntimeError("RNG state rank/world-size mismatch")
    random.setstate(payload["python"])
    np.random.set_state(payload["numpy"])
    torch.set_rng_state(payload["torch_cpu"])
    if torch.cuda.is_available():
        states = payload["torch_cuda"]
        if len(states) != torch.cuda.device_count():
            raise RuntimeError(
                "CUDA RNG state device count mismatch: "
                f"saved={len(states)}, current={torch.cuda.device_count()}"
            )
        torch.cuda.set_rng_state_all(states)
    return {"path": path.name, "sha256": _sha256(path)}


def _broadcast_error(error: str | None) -> None:
    if not (dist.is_available() and dist.is_initialized()):
        if error:
            raise RuntimeError(error)
        return
    payload = [error]
    dist.broadcast_object_list(payload, src=0)
    if payload[0]:
        raise RuntimeError(str(payload[0]))


def _raise_rank_errors(error: str | None) -> None:
    if not (dist.is_available() and dist.is_initialized()):
        if error:
            raise RuntimeError(error)
        return
    errors: list[str | None] = [None for _ in range(dist.get_world_size())]
    dist.all_gather_object(errors, error)
    failures = [value for value in errors if value]
    if failures:
        raise RuntimeError("; ".join(failures))


def install_areal_recovery_state_bridge() -> None:
    """Patch only the pinned SFT runtime; upstream source remains untouched."""

    audit_root = Path(os.environ[AUDIT_ROOT_ENV])
    start_step = _required_int(START_STEP_ENV)

    from areal.trainer.sft_trainer import SFTTrainer
    from areal.utils.recover import RecoverHandler

    current_dump = RecoverHandler.dump
    if not getattr(current_dump, "_studyhub_recovery_state_v1", False):
        original_dump = current_dump

        def dump_with_state(
            self: Any,
            engine: Any,
            step_info: Any,
            saver: Any,
            evaluator: Any,
            stats_logger: Any,
            dataloader: Any,
            tokenizer: Any = None,
            processor: Any = None,
            base_model_path: str | None = None,
        ) -> Any:
            result = original_dump(
                self,
                engine,
                step_info,
                saver,
                evaluator,
                stats_logger,
                dataloader,
                tokenizer=tokenizer,
                processor=processor,
                base_model_path=base_model_path,
            )
            if int(self.last_step_info.global_step) != int(step_info.global_step):
                return result
            rank, world_size = _rank_world()
            trial_root = _trial_root(self)
            recover_info = trial_root / "recover_info"
            rng_file: dict[str, Any] = {}
            save_error: str | None = None
            try:
                rng_file = _save_rng_state(recover_info, rank, world_size)
            except Exception as exc:
                save_error = f"rank {rank} RNG save failed: {type(exc).__name__}: {exc}"
            _raise_rank_errors(save_error)

            error: str | None = None
            if rank == 0:
                rng_files = {
                    f"rank_{value}": {
                        "path": f"rng_state_rank_{value}.pt",
                        "sha256": _sha256(recover_info / f"rng_state_rank_{value}.pt"),
                    }
                    for value in range(world_size)
                }
                _atomic_json(
                    recover_info / "rng_state_manifest.json",
                    {
                        "schema_version": "studyhub.rng-state-manifest.v1",
                        "global_step": int(step_info.global_step),
                        "world_size": world_size,
                        "files": rng_files,
                    },
                )
                snapshot_step = os.environ.get(SNAPSHOT_STEP_ENV)
                if snapshot_step is not None and int(snapshot_step) == int(step_info.global_step):
                    try:
                        from scripts.train.snapshot_sft_recovery_prefix import snapshot_prefix

                        snapshot_prefix(
                            trial_root,
                            Path(os.environ[SNAPSHOT_TARGET_ENV]),
                            Path(os.environ[SNAPSHOT_REPORT_ENV]),
                            expected_global_step=int(snapshot_step),
                        )
                    except Exception as exc:
                        error = f"synchronous recovery snapshot failed: {type(exc).__name__}: {exc}"
            _broadcast_error(error)
            audit_restore_error: str | None = None
            try:
                _restore_rng_state(recover_info, rank, world_size)
            except Exception as exc:
                audit_restore_error = (
                    f"rank {rank} post-audit RNG restore failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            _raise_rank_errors(audit_restore_error)
            _append_event(
                audit_root / "state",
                rank,
                {
                    "event": "state_saved",
                    "global_step": int(step_info.global_step),
                    "rank": rank,
                    "world_size": world_size,
                    "rng_file": rng_file,
                    "post_audit_rng_restored": True,
                    "dataloader_state_sha256": _sha256(recover_info / "dataloader_info.pkl"),
                    "checkpoint_boundary": "post_optimizer_step_no_partial_accumulation",
                    "engine_versions": _engine_versions(engine),
                },
            )
            return result

        dump_with_state._studyhub_recovery_state_v1 = True  # type: ignore[attr-defined]
        dump_with_state._studyhub_original_dump = original_dump  # type: ignore[attr-defined]
        RecoverHandler.dump = dump_with_state

    current_load = RecoverHandler.load
    if not getattr(current_load, "_studyhub_recovery_state_v1", False):
        original_load = current_load

        def load_with_state(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = original_load(self, *args, **kwargs)
            if result is None:
                if start_step > 0:
                    raise RuntimeError("recovery audit expected a checkpoint but AReaL loaded none")
                return result
            rank, world_size = _rank_world()
            recover_info = _trial_root(self) / "recover_info"
            engine = args[0] if args else kwargs.get("engine")
            if engine is None:
                raise RuntimeError("recovery state bridge could not locate the train engine")
            next_global_step = int(result.last_step_info.global_step) + 1
            recovered_engine_versions = _set_engine_versions(engine, next_global_step)
            rng_file: dict[str, Any] = {}
            restore_error: str | None = None
            try:
                rng_file = _restore_rng_state(recover_info, rank, world_size)
            except Exception as exc:
                restore_error = (
                    f"rank {rank} RNG restore failed: {type(exc).__name__}: {exc}"
                )
            _raise_rank_errors(restore_error)
            _append_event(
                audit_root / "state",
                rank,
                {
                    "event": "state_restored",
                    "saved_global_step": int(result.last_step_info.global_step),
                    "next_global_step": next_global_step,
                    "rank": rank,
                    "world_size": world_size,
                    "rng_file": rng_file,
                    "dataloader_state_sha256": _sha256(recover_info / "dataloader_info.pkl"),
                    "dcp_model_optimizer_load": "PASS",
                    "dataloader_load_state_dict": "PASS",
                    "engine_versions": recovered_engine_versions,
                },
            )
            return result

        load_with_state._studyhub_recovery_state_v1 = True  # type: ignore[attr-defined]
        load_with_state._studyhub_original_load = original_load  # type: ignore[attr-defined]
        RecoverHandler.load = load_with_state

    current_loader = SFTTrainer._load_bcast_from
    if not getattr(current_loader, "_studyhub_batch_fingerprint_v1", False):
        original_loader = current_loader

        def load_with_fingerprint(self: Any, data_generator: Any) -> Any:
            before_rng = rng_fingerprint()
            batch = original_loader(self, data_generator)
            after_rng = rng_fingerprint()
            rank, world_size = _rank_world()
            local_index = int(getattr(self, "_studyhub_batch_audit_index", 0))
            global_step = start_step + local_index
            self._studyhub_batch_audit_index = local_index + 1
            _append_event(
                audit_root / "batches",
                rank,
                {
                    "event": "train_batch",
                    "global_step": global_step,
                    "rank": rank,
                    "world_size": world_size,
                    "rng_before_load_sha256": before_rng,
                    "rng_after_load_sha256": after_rng,
                    **fingerprint_batch(batch),
                },
            )
            return batch

        load_with_fingerprint._studyhub_batch_fingerprint_v1 = True  # type: ignore[attr-defined]
        load_with_fingerprint._studyhub_original_loader = original_loader  # type: ignore[attr-defined]
        SFTTrainer._load_bcast_from = load_with_fingerprint
