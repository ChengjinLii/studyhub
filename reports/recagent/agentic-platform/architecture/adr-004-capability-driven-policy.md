# ADR-004: Capability-driven policy, not a hard-coded agent script

## Status

Accepted — 2026-07-26.

## Decision

StudyHub's Agent runtime will enforce only the boundaries that need deterministic
control: administrator authorization, Skill permissions, approval gates,
idempotency, budgets, typed state transitions, and persistence/audit rules.

It will not hard-code an intent classifier, a mandatory task sequence, a fixed
tool order, or a fixed number of replans. The policy selects one validated atomic
action from the currently registered capability catalog, and can create or revise
plans as new observations arrive.

`ContextBuilder` applies a token budget to a single model view, not to the Agent
Task State. When a view is compacted it marks `truncated=true`, retains the
capability catalog identity/count, and leaves the full state, artifacts, and
registered Skills intact for subsequent context-management or replanning actions.

`ReplayPolicy` exists solely for deterministic testing, simulation, and replay;
it is not the production runtime's control flow.

PR 6's LangGraph node topology is likewise an execution substrate, not a
workflow template.  Its router maps a typed atomic action only to the generic
executor that can carry it out (Skill, sub-agent, interrupt, verifier, or
finalizer); it never maps an intent to a business-specific plan, Skill order,
or mandatory replan count.  LangGraph's recursion allowance is derived from
the declared safety budget so it does not silently impose a smaller loop cap.

The DeepResearch subgraph follows the same rule.  It has structural planner,
policy, executor, and finalizer nodes, while the Policy chooses whether to
search, rewrite a query, read, cross-validate, manage context, revise a plan,
write, validate, or finish.  An empty search result and a recoverable source
failure are recorded as observations; neither automatically retries nor forces
a fixed search-to-report script.

## Consequences

- New Skills can be registered without changing a central action sequence.
- Capability probes and model policies remain replaceable.
- Future agent evaluations measure planning, search, verification, and recovery
  abilities rather than compliance with a handcrafted workflow.
- Safety-critical restrictions remain explicit and testable.
