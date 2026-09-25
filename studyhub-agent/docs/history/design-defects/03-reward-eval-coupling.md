# Training Reward and evaluation coupling

- **Defect:** Eval32 reuses Reward v2 components and hidden verifier semantics.
- **Discovery:** 2026-08-27 v3 baseline audit.
- **Evidence:** `configs/eval/studyhub-dev-eval-v2.json`, `training/rl/reward_v2.py`, and `scripts/train/evaluate_dev_rollouts.py` share success concepts.
- **Scope:** checkpoint selection, apparent RL gains and capability claims.
- **Why systemic:** optimizing the training grader can look like generalization even when behavior does not improve.
- **Competing explanations:** strict-success aggregation is not numerically identical to scalar Reward.
- **Minimal falsification:** rescore the same trajectories with an independently implemented rubric and inspect rank disagreement by family.
- **Root cause:** the small pilot prioritized a consistent smoke protocol over evaluator independence.
- **Fix:** place Reward v3, Dev v1 and Sealed v1 graders in separate code paths with independent tests and versions.
- **Regression:** validator requires three distinct implementation paths and benchmark cards record grader hashes.
- **Before/after:** verifier-aligned Eval32 -> independent Dev plus hidden Sealed and official external protocols.
- **Residual risk:** shared task authorship or judge models can still create correlated errors.
- **Interview 60s:** explain why reward/eval agreement is suspicious when they share code.
- **Deep dive:** use disagreement matrices, human QA and paired task analysis.
