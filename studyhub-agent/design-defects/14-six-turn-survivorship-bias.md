# Six-turn survivorship bias

- **Defect:** the global six-turn cap excludes or truncates tasks that need longer trajectories, then makes the remaining benchmark look representative.
- **Discovery:** v2 runtime-budget audit.
- **Evidence:** `configs/train/open-grpo-qwen35-9b.yaml` and `configs/eval/studyhub-dev-eval-v2.json` both set six model turns.
- **Scope:** multi-hop, recovery, cross-tool, Web and deep-research capability.
- **Why systemic:** data selection adapts to the runtime limit instead of measuring the intended product horizon.
- **Competing explanations:** six turns are appropriate for short function and basic retrieval tasks.
- **Minimal falsification:** audit reference/minimal valid sequential turns and run horizon slices at 6, 10 and 20 turns.
- **Root cause:** memory pressure and smoke-test latency became an implicit capability definition.
- **Fix:** use a global safety ceiling of 20 with per-task 3/6/10/20 budgets and explicit horizon metrics.
- **Regression:** no task enters a slice if its verified feasible horizon exceeds its assigned budget.
- **Before/after:** one global cap -> task-tiered horizon contract.
- **Residual risk:** long contexts can still truncate evidence and increase variance.
- **Interview 60s:** explain how system budgets can silently bias a dataset.
- **Deep dive:** separate model turns, tool calls, tokens and wall-clock budgets.
