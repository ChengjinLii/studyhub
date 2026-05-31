# StudyCopilot v9 Admin/Test Shadow Readiness

This file documents the machine-readable checks in `rollout_readiness.admin_shadow.json`.

## Scope

- Mode: admin/test shadow only.
- Public frontend entry: disabled.
- Production database writes: disabled.
- Production search behavior: unchanged.

## Feature Flag

- Suggested flag name: `STUDYHUB_AI_STUDYCOPILOT_SHADOW`.
- Default value: off.
- Allowed audience before production: local CLI, CI, admin-only smoke test, or test account traffic replay.

## Rollback Plan

- Disable `STUDYHUB_AI_STUDYCOPILOT_SHADOW`.
- Remove LLM provider environment variables from the shadow process.
- Keep existing keyword/search behavior as the user-facing fallback.
- Ignore any isolated JSONL usage logs and local memory demo files when rolling back.

## Cost Monitoring

- Set `STUDYHUB_USAGE_LOG_PATH` for every shadow run.
- Track provider, model, operation, token estimates, input count, output count, status, and error type.
- Do not log prompt text, user query text, model response body, or API keys.

## Privacy Policy

- Sanitize model-bound prompts with `shared/privacy.py`.
- Do not send production-only private fields unless a later production review explicitly approves them.
- Keep Hermes memory output as candidates until the user-facing review and deletion contract is implemented.
- Use `JsonHermesMemoryStore` only for isolated demos and tests.

## Human Fallback

- If Router, rerank, or GenRec output is low confidence or invalid, fall back to ordinary retrieval.
- If moderation detects copyright, contact leakage, spam, or unsafe content, route to manual review.
- If an AI answer cites no retrieved candidate IDs, discard the answer and return non-AI search results.

## Exit Criteria For Public Rollout

- Offline eval report passes.
- Prompt injection guard coverage remains green.
- Usage log review confirms no prompt, response body, raw query, or secret persistence.
- Product owner approves a frontend entry, data retention policy, and rollback switch.
