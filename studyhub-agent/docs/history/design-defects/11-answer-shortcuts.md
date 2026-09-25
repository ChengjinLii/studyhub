# Token-F1 and substring answer shortcuts

- **Defect:** v2 answer scoring can reward lexical overlap or substring matches without semantic correctness, especially in Chinese.
- **Discovery:** 2026-08-27 Reward code audit.
- **Evidence:** `training/rl/reward_v2.py` implements expected-answer substring and token-overlap scoring.
- **Scope:** QA, explanation, evidence synthesis and no-answer behavior.
- **Why systemic:** a policy can copy keywords or hedge around the target while making unsupported claims.
- **Competing explanations:** exact match remains reliable for normalized short factual answers.
- **Minimal falsification:** build paraphrase, negation, keyword-copy and contradictory-answer adversarial pairs and measure FP/FN.
- **Root cause:** cheap open-data verifiers were generalized beyond their valid task family.
- **Fix:** use task-specific objective checks where possible and calibrated semantic/rubric graders for open answers.
- **Regression:** Reward calibration includes Chinese adversarial cases and tracks per-family false positives/negatives.
- **Before/after:** generic lexical proxy -> typed end-state and semantic evaluation.
- **Residual risk:** semantic judges introduce cost and model bias.
- **Interview 60s:** contrast exact factual grading with open explanation grading.
- **Deep dive:** report pairwise accuracy and judge disagreement, not only correlation.
