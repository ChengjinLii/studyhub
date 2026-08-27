# Task-specific tool suffix

- **Defect:** v2 tasks narrow allowed tools by family and append task-specific tool guidance.
- **Discovery:** 2026-08-27 data-builder audit.
- **Evidence:** `scripts/data/build_open_rl_tasks.py` builds family-specific allowed tool sets and prompt suffixes.
- **Scope:** tool routing, cross-tool fallback and transfer to the real Hermes registry.
- **Why systemic:** the prompt leaks the intended route and makes routing metrics artificially easy.
- **Competing explanations:** restricted tool sets reduce early invalid-call noise during cold start.
- **Minimal falsification:** compare 9B Base trajectories on 200 tasks with narrow and full stable tool registries.
- **Root cause:** pilot tasks were designed for isolated family verification rather than autonomous routing.
- **Fix:** keep stable tool identities; use curriculum tiers without revealing the gold family in the user prompt.
- **Regression:** scan public tasks for family/tool hints and report routing regret with distractor tools.
- **Before/after:** task-labelled tool menu -> stable registry and capability-aware environment.
- **Residual risk:** too many tools can cause schema overload and require staged curriculum.
- **Interview 60s:** distinguish curriculum restrictions from answer leakage.
- **Deep dive:** measure tool entropy, invalid calls and success under distractor growth.
