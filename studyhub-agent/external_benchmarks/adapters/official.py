"""Command builders for unmodified upstream benchmark entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _csv(values: tuple[str, ...]) -> str:
    if not values or any(not value or "," in value for value in values):
        raise ValueError("command values must be non-empty and comma-free")
    return ",".join(values)


@dataclass(frozen=True, slots=True)
class OfficialInvocation:
    """Arguments only; callers execute them without a shell."""

    benchmark: str
    working_directory: Path
    command: tuple[str, ...]
    requires_api_key: bool = False
    requires_gpu: bool = False

    @classmethod
    def bfcl_generate(
        cls,
        source_root: Path,
        *,
        model: str,
        categories: tuple[str, ...],
        result_dir: str,
    ) -> OfficialInvocation:
        return cls(
            benchmark="bfcl",
            working_directory=source_root / "berkeley-function-call-leaderboard",
            command=(
                "bfcl",
                "generate",
                "--model",
                model,
                "--test-category",
                _csv(categories),
                "--result-dir",
                result_dir,
                "--skip-server-setup",
            ),
        )

    @classmethod
    def bfcl_evaluate(
        cls,
        source_root: Path,
        *,
        model: str,
        categories: tuple[str, ...],
        result_dir: str,
    ) -> OfficialInvocation:
        return cls(
            benchmark="bfcl",
            working_directory=source_root / "berkeley-function-call-leaderboard",
            command=(
                "bfcl",
                "evaluate",
                "--model",
                model,
                "--test-category",
                _csv(categories),
                "--result-dir",
                result_dir,
                "--partial-eval",
            ),
        )

    @classmethod
    def tau2_run(
        cls,
        source_root: Path,
        *,
        domain: str,
        agent_model: str,
        user_model: str,
        task_ids: tuple[str, ...] = (),
    ) -> OfficialInvocation:
        allowed_domains = {"airline", "retail", "telecom", "banking_knowledge"}
        if domain not in allowed_domains:
            raise ValueError(f"unsupported core tau2 domain: {domain}")
        command = [
            "uv",
            "run",
            "tau2",
            "run",
            "--domain",
            domain,
            "--agent-llm",
            agent_model,
            "--user-llm",
            user_model,
            "--task-split-name",
            "base",
        ]
        if task_ids:
            command.extend(("--task-ids", *task_ids))
        return cls("tau2", source_root, tuple(command), requires_api_key=True)

    @classmethod
    def deepresearch_evaluate(cls, source_root: Path) -> OfficialInvocation:
        return cls(
            "deepresearch_bench_ii",
            source_root,
            ("uv", "run", "python", "run_evaluation.py"),
            requires_api_key=True,
        )

    @classmethod
    def browsecomp_evaluate(cls, source_root: Path, *, input_dir: Path) -> OfficialInvocation:
        return cls(
            "browsecomp_plus",
            source_root,
            ("uv", "run", "python", "scripts_evaluation/evaluate_run.py", "--input_dir", str(input_dir)),
            requires_gpu=True,
        )
