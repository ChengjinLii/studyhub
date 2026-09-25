# Small and same-source benchmark

- **Defect:** 32 tasks from the RL source manifest cannot support broad Agent capability conclusions.
- **Discovery:** v2 result review, formalized 2026-08-27.
- **Evidence:** `configs/eval/studyhub-dev-eval-v2.json` fixes 32 tasks and four rollouts; the 4B report records wide bootstrap intervals.
- **Scope:** statistical power, family slices, horizon coverage and model promotion.
- **Why systemic:** one task changes a slice by several percentage points and shared source groups invite overfitting.
- **Competing explanations:** Eval32 remains useful as a deterministic regression panel.
- **Minimal falsification:** bootstrap the current 32 tasks and compare interval width with a stratified 1,005-task Dev design.
- **Root cause:** the initial goal was runtime verification, but the same artifact was later asked to answer capability questions.
- **Fix:** retain a 160-task Regression suite, build 1,005-task Dev and 500-task Sealed sets, and add official external benchmarks.
- **Regression:** benchmark validator enforces size ranges, version hashes, contamination checks and variance/MDE evidence.
- **Before/after:** one verifier-aligned subset -> Regression, Dev, Sealed and External layers.
- **Residual risk:** a large benchmark can still be low quality or template-heavy.
- **Interview 60s:** distinguish task count, rollout count and independent task diversity.
- **Deep dive:** discuss clustered bootstrap and source-group leakage.
