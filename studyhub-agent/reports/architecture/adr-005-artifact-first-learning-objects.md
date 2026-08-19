# ADR-005: Artifact-first learning objects and parent-owned persistence

## Status

Accepted — 2026-07-26.

## Decision

Specialist sub-agents produce only typed, evidence-provenanced candidates:
`LearningPlan`, `PracticeSet`, `MaterialAnalysis`, and `DailyBrief`. They do
not receive a database session or repository and cannot make a candidate
durable by themselves.

The parent runtime reviews a candidate through `LearningArtifactService` before
calling the existing versioned `AgentArtifactRepository`. Invalid candidates
are rejected before the repository is touched. A durable artifact gets its
version from the existing `(thread_id, artifact_type, artifact_key)` version
sequence; changing an accepted plan creates a new version instead of mutating
the prior one. Reusing an idempotency key for changed content is rejected.

Learning plans and practice sets must point to real internal material and
page-level PDF evidence. `DailyBrief` is structurally marked
`admin_preview_only=true`, so PR8 cannot turn it into a learner-visible message.

## Consequences

- Parent policy can accept, reject, revise, or defer any sub-agent candidate.
- Artifact history is auditable and suitable for later evaluation/training.
- A malformed plan or invented practice page cannot enter persistence.
- Proactive delivery remains shadow-only until a later explicit product stage.
