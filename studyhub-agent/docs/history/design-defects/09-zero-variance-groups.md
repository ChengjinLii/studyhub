# Zero-variance GRPO groups

- **Defect:** 31% to 36.5% of observed v2 groups had no within-group reward variance, with Search among the weakest slices.
- **Discovery:** 4B GRPO pilot analysis.
- **Evidence:** `docs/StudyHub_4B_AReaL_Agentic_RL_Experiment_Report.html` and reward-group artifacts record the rates.
- **Scope:** effective sample efficiency, advantage signal and dual-H100 time-to-quality.
- **Why systemic:** complete all-correct or all-failed groups consume rollout compute but provide little group-relative learning signal.
- **Competing explanations:** some zero-variance groups still contribute KL or implementation-specific terms.
- **Minimal falsification:** compute gradient/advantage contribution by group type and calibrate 9B success probability with four rollouts per task.
- **Root cause:** tasks were not selected by current-policy learnability and some verifiers were too easy or impossible.
- **Fix:** route mixed outcomes to GRPO, all-correct to retention and all-failed to teacher repair/curriculum; consider DAPO dynamic sampling only if needed.
- **Regression:** log effective-group rate, reward std, entropy, task family and compute spent per bucket.
- **Before/after:** static task pool -> policy-calibrated learnability pool.
- **Residual risk:** aggressive filtering can narrow task diversity and forget difficult capabilities.
- **Interview 60s:** explain why more rollouts do not guarantee more policy-gradient signal.
- **Deep dive:** compare GRPO normalization with RLOO/REINFORCE and dynamic sampling.
