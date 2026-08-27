# Training and product capability mismatch

- **Defect:** open FC/QA data dominates v2 while StudyHub requires educational RAG, Web fallback, personal/collective Memory, ACL and learning workflows.
- **Discovery:** 2026-08-27 data-to-product audit.
- **Evidence:** the 3k SFT and 2.4k RL manifests are open-data based; the product adapters expose broader capabilities.
- **Scope:** real user value and external validity.
- **Why systemic:** success on generic functions can coexist with failure on StudyHub's central learning tasks.
- **Competing explanations:** open data supplies useful protocol and reasoning priors.
- **Minimal falsification:** compare 9B Base and v2-trained checkpoints on matched open and StudyHub-native slices.
- **Root cause:** available datasets drove the task mix instead of a capability budget.
- **Fix:** use roughly 52% StudyHub-native SFT and 60% StudyHub RL tasks, while preserving external diversity.
- **Regression:** every dataset manifest reports capability, product-domain and source shares against the matrix.
- **Before/after:** source-led collection -> capability-led open+custom mix.
- **Residual risk:** synthetic StudyHub tasks may be template-heavy or teacher-biased.
- **Interview 60s:** explain why domain data and open generalization data have different jobs.
- **Deep dive:** analyze cross-domain transfer and source ablations without exceeding the main compute budget.
