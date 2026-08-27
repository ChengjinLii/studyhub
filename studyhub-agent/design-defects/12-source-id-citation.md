# Source-ID citation without claim support

- **Defect:** v2 citation checks mainly verify that a cited source ID was read, not that the passage supports the associated claim.
- **Discovery:** v2 Reward review.
- **Evidence:** citation logic in `training/rl/reward_v2.py` and the 4B report's citation failure analysis.
- **Scope:** grounded QA, RAG, Web and deep-research outputs.
- **Why systemic:** a model can cite a relevant-looking document beside an unsupported claim and receive credit.
- **Competing explanations:** source-ID validity is still a necessary syntax and provenance check.
- **Minimal falsification:** pair correct IDs with unsupported claims and measure the current citation false-positive rate.
- **Root cause:** the frozen environment did not expose stable passage-level claim annotations.
- **Fix:** evaluate Claim -> Citation -> Passage -> support/entailment and report precision, recall and unsupported claims.
- **Regression:** adversarial citation swaps must fail even when every source was read.
- **Before/after:** provenance existence -> claim-level support.
- **Residual risk:** entailment judges can miss nuanced or multi-source support.
- **Interview 60s:** explain the difference between citation validity and citation correctness.
- **Deep dive:** handle compound claims and evidence spread across passages.
