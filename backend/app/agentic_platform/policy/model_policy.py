from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.decision import AgentDecision, AgentOutput
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json
from app.agentic_platform.domain.plan import AgentPlan
from app.agentic_platform.domain.state import AgentTaskState

from .context_view import ContextPurpose, ContextView
from .model_provider import AgentModelProvider, AgentModelRequest, AgentModelResponse
from .openai_compatible_provider import ModelResponseQuarantinedError
from .token_trace import TokenTrace
from .turn_result import InMemoryRestrictedRawModelOutputStore, PolicyTurnResult, RawModelOutputStore


OutputT = TypeVar("OutputT", bound=BaseModel)


class RenderedPolicyPrompt(DomainModel):
    purpose: ContextPurpose
    context_hash: str = Field(min_length=1, max_length=128)
    prompt_hash: str = Field(min_length=1, max_length=128)
    rendered_prompt: str = Field(min_length=1, max_length=200_000)


class InvalidModelOutputError(ValueError):
    """Safe structural failure: no raw model response or hidden reasoning leaks."""

    def __init__(
        self,
        *,
        purpose: ContextPurpose,
        schema_name: str,
        model_id: str,
        response_hash: str,
        error_types: list[str],
        field_paths: list[str],
        raw_model_output_ref=None,
    ) -> None:
        self.purpose = purpose
        self.schema_name = schema_name
        self.model_id = model_id
        self.response_hash = response_hash
        self.error_types = error_types
        self.field_paths = field_paths
        self.raw_model_output_ref = raw_model_output_ref
        super().__init__(
            f"invalid structured model output for {purpose.value}/{schema_name}; "
            f"fields={field_paths or ['<root>']}, errors={error_types or ['validation_error']}"
        )


_INSTRUCTIONS = {
    ContextPurpose.PLANNER: (
        "Create or revise a plan as one JSON object matching the supplied schema. "
        "Do not include chain-of-thought, hidden reasoning, markdown, or fields outside the schema. "
        'JSON example: {"plan_id":"example","version":1}.'
    ),
    ContextPurpose.POLICY: (
        "Choose exactly one atomic agent action as one JSON object matching the supplied schema. "
        "Use only rationale_summary; do not include chain-of-thought, markdown, or fields outside the schema. "
        'JSON example: {"action_type":"review","rationale_summary":"brief safe summary"}.'
    ),
    ContextPurpose.FINALIZER: (
        "Produce an administrator-visible final artifact summary as one JSON object matching the supplied schema. "
        "Do not include chain-of-thought, markdown fences, or fields outside the schema. "
        'JSON example: {"summary":"brief final result","user_visible":true}.'
    ),
}


def render_policy_prompt(context: ContextView, output_model: type[BaseModel]) -> RenderedPolicyPrompt:
    context_hash = canonical_hash(context)
    output_schema = output_model.model_json_schema()
    schema_hash = canonical_hash(output_schema)
    instruction = _INSTRUCTIONS[context.purpose]
    prompt_hash = canonical_hash(
        {
            "purpose": context.purpose.value,
            "instruction": instruction,
            "context_hash": context_hash,
            "schema_hash": schema_hash,
        }
    )
    rendered_prompt = "\n".join(
        (
            instruction,
            f"context_hash={context_hash}",
            "CONTEXT_JSON:",
            canonical_json(context),
            "OUTPUT_JSON_SCHEMA:",
            canonical_json(output_schema, exclude_fields=()),
        )
    )
    return RenderedPolicyPrompt(
        purpose=context.purpose,
        context_hash=context_hash,
        prompt_hash=prompt_hash,
        rendered_prompt=rendered_prompt,
    )


class ModelPolicy:
    """Strict structured-output policy backed by any AgentModelProvider adapter."""

    def __init__(self, provider: AgentModelProvider, *, raw_output_store: RawModelOutputStore | None = None) -> None:
        self.provider = provider
        self.raw_output_store = raw_output_store or InMemoryRestrictedRawModelOutputStore()

    async def create_plan(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentPlan]:
        return await self._request_structured(state, context, ContextPurpose.PLANNER, AgentPlan, max_output_tokens=1_200)

    async def decide(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentDecision]:
        return await self._request_structured(state, context, ContextPurpose.POLICY, AgentDecision, max_output_tokens=800)

    async def finalize(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentOutput]:
        return await self._request_structured(state, context, ContextPurpose.FINALIZER, AgentOutput, max_output_tokens=1_200)

    async def _request_structured(
        self,
        state: AgentTaskState,
        context: ContextView,
        purpose: ContextPurpose,
        output_model: type[OutputT],
        *,
        max_output_tokens: int,
    ) -> PolicyTurnResult[OutputT]:
        if context.purpose != purpose:
            raise ValueError(f"{purpose.value} requires a matching {purpose.value} context")
        prompt = render_policy_prompt(context, output_model)
        request = AgentModelRequest(
            purpose=purpose,
            rendered_prompt=prompt.rendered_prompt,
            context_hash=prompt.context_hash,
            prompt_hash=prompt.prompt_hash,
            output_schema_name=output_model.__name__,
            output_schema=output_model.model_json_schema(),
            max_output_tokens=max_output_tokens,
        )
        try:
            response = await self.provider.complete(request)
        except ModelResponseQuarantinedError as exc:
            raw_ref = await self.raw_output_store.store(
                state=state,
                purpose=purpose,
                raw_content=exc.raw_content,
                model_id="unparsed-provider-output",
                prompt_hash=prompt.prompt_hash,
            )
            raise InvalidModelOutputError(
                purpose=purpose,
                schema_name=output_model.__name__,
                model_id="unparsed-provider-output",
                response_hash=exc.content_hash,
                error_types=[exc.code],
                field_paths=[],
                raw_model_output_ref=raw_ref,
            ) from exc
        raw_ref = await self._store_raw_output(state=state, purpose=purpose, prompt_hash=prompt.prompt_hash, response=response)
        try:
            parsed = output_model.model_validate(response.structured_output)
        except ValidationError as exc:
            self._raise_invalid_output(
                purpose=purpose,
                schema_name=output_model.__name__,
                model_id=response.model_id,
                raw_output=response.structured_output,
                validation_error=exc,
                raw_model_output_ref=raw_ref,
            )
        trace = TokenTrace(
            source=response.token_trace_source,
            token_ids=response.token_ids,
            token_logprobs=response.token_logprobs,
            token_role_spans=response.token_role_spans,
        )
        return PolicyTurnResult(
            parsed_output=parsed,
            model_id=response.model_id,
            model_revision=response.model_revision,
            prompt_hash=prompt.prompt_hash,
            context_hash=prompt.context_hash,
            raw_model_output_ref=raw_ref,
            token_ids=trace.token_ids,
            token_logprobs=trace.token_logprobs,
            token_role_spans=trace.token_role_spans,
            usage=response.usage,
            latency_ms=response.latency_ms,
            finish_reason=response.finish_reason,
            provider_request_id=response.provider_request_id,
            token_trace_source=trace.source,
            trainable=trace.trainable,
        )

    async def _store_raw_output(
        self,
        *,
        state: AgentTaskState,
        purpose: ContextPurpose,
        prompt_hash: str,
        response: AgentModelResponse,
    ) -> ArtifactRef | None:
        if response.raw_content is None:
            return None
        return await self.raw_output_store.store(
            state=state,
            purpose=purpose,
            raw_content=response.raw_content,
            model_id=response.model_id,
            prompt_hash=prompt_hash,
        )

    @staticmethod
    def _raise_invalid_output(
        *,
        purpose: ContextPurpose,
        schema_name: str,
        model_id: str,
        raw_output: dict[str, object],
        validation_error: ValidationError,
        raw_model_output_ref=None,
    ) -> None:
        errors = validation_error.errors(include_url=False, include_input=False)
        error_types = sorted({str(item.get("type") or "validation_error") for item in errors})
        field_paths = [".".join(str(part) for part in item.get("loc", ())) or "<root>" for item in errors]
        raise InvalidModelOutputError(
            purpose=purpose,
            schema_name=schema_name,
            model_id=model_id,
            response_hash=canonical_hash(raw_output),
            error_types=error_types,
            field_paths=field_paths,
            raw_model_output_ref=raw_model_output_ref,
        )
