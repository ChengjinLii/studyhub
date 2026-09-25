# Tiny pilot treated as a formal experiment

- **Defect:** a 25-update, 200-task, single-seed GRPO pilot can be mistaken for evidence of stable capability gain.
- **Discovery:** 4B completion analysis.
- **Evidence:** the 4B report records 25 updates, 200 groups and non-significant broad comparisons.
- **Scope:** model claims, algorithm choice and whether 9B work starts.
- **Why systemic:** mechanism evidence and effect evidence answer different questions.
- **Competing explanations:** the pilot is sufficient to prove the training chain and expose failure modes.
- **Minimal falsification:** pre-register a 300-600 update 9B run with independent Dev, variance panel and stop/expand rules.
- **Root cause:** repeated caution allowed the cheap pilot to become the default experimental unit.
- **Fix:** freeze 4B as infrastructure history and run the first 9B main GRPO with 500 planned updates and 4k unique tasks after gates.
- **Regression:** reports label evidence A/B/C/D and prohibit capability claims from Gate, smoke or mechanism pilots.
- **Before/after:** pilot-as-result -> pilot-as-mechanism followed by budgeted main experiment.
- **Residual risk:** a larger run is still invalid if Benchmark or Reward is wrong.
- **Interview 60s:** separate reproducibility, statistical power and practical significance.
- **Deep dive:** define pre-registered expansion and stopping criteria.
