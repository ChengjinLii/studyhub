# Teacher-to-Hermes Smoke, 2026-08-28

## Scope

This smoke validated the provider-to-controller boundary only. It did not use Benchmark v2 tasks, Sealed-A/B, hidden graders, or oracle trajectories. Every model turn received a public task, public tool schemas, visible messages, and a one-action JSON contract. Hermes executed accepted tool actions against the frozen task environment.

## Provider Results

| Provider | Result | Evidence |
| --- | --- | --- |
| GPT-5.3-Codex-Spark CLI | Available after 06:34 CST | The bounded recovery smoke completed 20 rollouts over 10 public training tasks. Two direct-answer rollouts passed the objective verifier; one was later excluded by Codex self-review. |
| OpenAI Responses API | `NOT_AVAILABLE` | `OPENAI_API_KEY` was not configured. |
| Authorized Xiaomi OpenAI-compatible endpoint | `FAILED_AUTH` | Six bounded smoke requests returned HTTP 401 `Invalid API Key`; no retry loop was started. |
| Local Qwen3.5-9B best-of-N | `NOT_RUN` | The two H100s were reserved for the bounded v3.0 SFT baseline. |

## Findings

The first Spark probe exposed an invalid generic Structured Outputs schema. Provider arguments are now emitted as a JSON string and decoded to a dict before Hermes schema validation. This preserves standard OpenAI tool-call objects in the saved trajectory.

The next probe exposed two task-environment defects rather than a model-quality result:

- Web search rows had been copied into the local knowledge corpus, short-circuiting the intended RAG-to-Web fallback.
- Replay search tools required the teacher to reproduce the fixture query exactly, so legitimate query rewrites failed.

The corrected environment keeps local and Web evidence separate, allows deterministic lexical matching over frozen search fixtures, and keeps fetch/state calls on exact routes. A public completion contract now states required tool families, minimum grounded citations, and exact citation syntax. Hidden reference answers remain unavailable to the teacher.

## Outcome

Raw runs: `26` (`20` Spark plus `6` failed authorized-endpoint probes).

Objective verifier results:

- accepted: `2`;
- rejected: `24`;
- overall objective acceptance rate: `7.69%`;
- Spark objective acceptance rate: `10%`.

Codex self-review covered all available rows, not the requested 50/50 minimum because only 2 accepted and 24 rejected rows existed. One objective-accepted direct answer was excluded for a factual mismatch that lexical overlap had missed. One direct answer remained approved. All 24 objective rejections were upheld.

The smoke was not expanded because tool-using trajectories had low verifier pass rates. Main failures were missing grounded citations, incomplete Search/Read/Fetch sequences, provider execution failures, and invalid state-tool calls. Existing raw runs and rejection taxonomies remain in the ignored interim directory. No failed or self-review-excluded trajectory enters the v3.1 candidate. `runtime-SFT-v3.1-teacher-candidate` remains candidate-only and must not be described as a formal v3.1 release.
