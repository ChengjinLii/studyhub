from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.agentic_platform.domain.hashing import canonical_hash
from app.services.read_support import ROLE_ADMIN, has_role

from .base import BaseSkill, IdempotencyMode
from .context import SkillExecutionContext, SkillExecutionMode
from .registry import SkillRegistry


OutputT = TypeVar("OutputT", bound=BaseModel)


class SkillPermissionDeniedError(PermissionError):
    pass


class SkillInvalidArgumentsError(ValueError):
    pass


class SkillIdempotencyKeyRequiredError(ValueError):
    pass


class SkillExecutionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "skill_execution_error", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class SkillTimeoutError(SkillExecutionError):
    def __init__(self, skill_name: str) -> None:
        super().__init__(f"skill timed out: {skill_name}", code="timeout", retryable=True)


@dataclass(frozen=True, slots=True)
class SkillExecutionResult(Generic[OutputT]):
    output: OutputT
    attempts: int
    elapsed_ms: float
    cache_hit: bool
    estimated_cost: float


class SkillExecutor:
    """Shared execution policy for Live and Fixture capability adapters."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry
        self._idempotency_cache: dict[str, BaseModel] = {}

    async def execute(
        self,
        *,
        skill_name: str,
        arguments: dict[str, Any],
        context: SkillExecutionContext,
    ) -> SkillExecutionResult[BaseModel]:
        skill = self.registry.get(skill_name)
        self._assert_permission(skill, context)
        try:
            payload = skill.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise SkillInvalidArgumentsError(f"invalid arguments for {skill_name}: {exc}") from exc

        cache_key = self._cache_key(skill, payload, context)
        if cache_key is not None and cache_key in self._idempotency_cache:
            output = self._idempotency_cache[cache_key].model_copy(deep=True)
            return SkillExecutionResult(
                output=output,
                attempts=0,
                elapsed_ms=0.0,
                cache_hit=True,
                estimated_cost=skill.spec.cost_model.fixed_cost,
            )

        started_at = perf_counter()
        attempts = 0
        while True:
            attempts += 1
            try:
                raw_output = await asyncio.wait_for(
                    self._invoke(skill, context, payload),
                    timeout=skill.spec.timeout_seconds,
                )
                output = skill.output_model.model_validate(raw_output)
                break
            except asyncio.TimeoutError as exc:
                error = SkillTimeoutError(skill.spec.name)
                cause: Exception | None = exc
            except SkillExecutionError as exc:
                error = exc
                cause = exc
            except ValidationError as exc:
                raise SkillExecutionError(
                    f"skill output violated {skill.output_model.__name__}: {exc}",
                    code="invalid_output",
                    retryable=False,
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise SkillExecutionError(str(exc), code="unhandled_skill_error", retryable=False) from exc

            if not self._should_retry(skill, error, attempts):
                raise error from cause
            if skill.spec.retry_policy.backoff_seconds:
                await asyncio.sleep(skill.spec.retry_policy.backoff_seconds)

        if cache_key is not None:
            self._idempotency_cache[cache_key] = output.model_copy(deep=True)
        return SkillExecutionResult(
            output=output,
            attempts=attempts,
            elapsed_ms=(perf_counter() - started_at) * 1_000,
            cache_hit=False,
            estimated_cost=skill.spec.cost_model.fixed_cost,
        )

    async def _invoke(self, skill: BaseSkill, context: SkillExecutionContext, payload: BaseModel) -> BaseModel:
        raise NotImplementedError

    @staticmethod
    def _assert_permission(skill: BaseSkill, context: SkillExecutionContext) -> None:
        if not has_role(context.role_mask, ROLE_ADMIN):
            raise SkillPermissionDeniedError("agentic skills require ROLE_ADMIN")
        missing_scopes = set(skill.spec.permission_scopes) - set(context.permission_scopes)
        if missing_scopes:
            raise SkillPermissionDeniedError(f"missing skill permission scopes: {sorted(missing_scopes)}")
        if skill.spec.requires_approval and not context.approval_granted:
            raise SkillPermissionDeniedError(f"skill requires approval: {skill.spec.name}")

    @staticmethod
    def _should_retry(skill: BaseSkill, error: SkillExecutionError, attempts: int) -> bool:
        if attempts >= skill.spec.retry_policy.max_attempts or not error.retryable:
            return False
        retryable_codes = skill.spec.retry_policy.retryable_error_codes
        return not retryable_codes or error.code in retryable_codes

    @staticmethod
    def _cache_key(skill: BaseSkill, payload: BaseModel, context: SkillExecutionContext) -> str | None:
        if skill.spec.idempotency == IdempotencyMode.NON_IDEMPOTENT:
            return None
        if skill.spec.idempotency == IdempotencyMode.KEYED:
            key = (context.idempotency_key or "").strip()
            if not key:
                raise SkillIdempotencyKeyRequiredError(f"skill requires an idempotency key: {skill.spec.name}")
            return f"keyed:{skill.spec.name}:{skill.spec.version}:{key}"
        return f"pure:{skill.spec.name}:{skill.spec.version}:{canonical_hash(payload)}"


class LiveSkillExecutor(SkillExecutor):
    async def _invoke(self, skill: BaseSkill, context: SkillExecutionContext, payload: BaseModel) -> BaseModel:
        if context.mode != SkillExecutionMode.LIVE:
            raise SkillExecutionError("live executor received non-live context", code="execution_mode_mismatch")
        return await skill.execute(context, payload)


class FixtureSkillExecutor(SkillExecutor):
    async def _invoke(self, skill: BaseSkill, context: SkillExecutionContext, payload: BaseModel) -> BaseModel:
        del payload
        if context.mode != SkillExecutionMode.FIXTURE:
            raise SkillExecutionError("fixture executor received non-fixture context", code="execution_mode_mismatch")
        try:
            fixture_output = context.fixture_outputs[skill.spec.name]
        except KeyError as exc:
            raise SkillExecutionError(f"fixture output is missing for {skill.spec.name}", code="fixture_missing") from exc
        return skill.output_model.model_validate(fixture_output)
