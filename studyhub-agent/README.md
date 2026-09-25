# StudyHub Agent v3

A research codebase for a StudyHub study-assistant agent built on Qwen3.5-4B, with 9B/27B as prompted baselines.
Design: [`docs/specs/2026-09-25-foundation-design.md`](docs/specs/2026-09-25-foundation-design.md).

## Layout

| Package | Responsibility |
|---|---|
| `contracts` | ToolSpec + lint, versioned prompts, episode models, the single Qwen3.5 renderer/parser, contract hash |
| `guardrails` | permissions, privacy redaction, SSRF policy |
| `tools` | the 8 tool specs and their backend MCP names |
| `environments` | `Environment` protocol and the gated `ReplayEnvironment` |
| `runtime` | `EpisodeRunner`, token-level (SGLang) and OpenAI-compatible policy clients |
| `graders` | `Grader` protocol (benchmark and reward graders arrive in sub-project 2) |

Layering is enforced by `lint-imports --config .importlinter`.

## Contract

Every episode, SFT sample, rollout and evaluation row carries a `contract_hash` covering the prompts, tool specs,
thinking flag, chat-template digest, tokenizer revision, token limits and the turn rule. Rows with different hashes are
never mixed. Tools marked `capability="snapshot"` run against frozen data and are not claims about the live product.

## Development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,tokenizers]"
.venv/bin/ruff check src tests && .venv/bin/lint-imports --config .importlinter && .venv/bin/pytest --cov
```

Model-dependent acceptance tests: `STUDYHUB_AGENT_MODEL_DIR=/path/to/Qwen3.5-4B pytest -m requires_model`.

Serving Qwen3.5-4B with SGLang for the smoke episodes (`scripts/smoke_episodes.py`), including the
no-nvcc compatibility shim and shared-GPU etiquette for the current host, is documented in
[`scripts/serving/README.md`](scripts/serving/README.md). Sample output:
[`docs/evidence/foundation-smoke-2026-09-25.jsonl`](docs/evidence/foundation-smoke-2026-09-25.jsonl).

## History

The v2 code (Hermes/AReaL workflows, benchmark v1/v2, SFT/GRPO/OPD scripts) is preserved at tag `legacy-agent-v2`
(unmerged OPD work at `archive/opd-*`). Reports and design-defect post-mortems are in `docs/history/`.
