# Teacher-to-Hermes Smoke, 2026-08-28

## Scope

This smoke validated the provider-to-controller boundary only. It did not use Benchmark v2 tasks, Sealed-A/B, hidden graders, or oracle trajectories. Every model turn received a public task, public tool schemas, visible messages, and a one-action JSON contract. Hermes executed accepted tool actions against the frozen task environment.

## Provider Results

| Provider | Result | Evidence |
| --- | --- | --- |
| GPT-5.3-Codex-Spark CLI | Available, then rate-limited | Structured action output worked; accepted Codex turns had zero shell/file tool events. The account reported a usage limit until 06:34 CST. |
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

Accepted teacher trajectories: `0`.

The corrected task/environment version was not expanded after Spark hit its usage limit. Existing failed raw runs and rejection taxonomies are retained under ignored interim probe directories. No failed trajectory enters SFT. `runtime-SFT-v3.1-teacher-candidate` therefore remains candidate-only and must not be described as a formal v3.1 release.
