# Evidence recall without precision

- **Defect:** v2 evidence scoring emphasizes whether gold sources were found, with weak cost for irrelevant reads.
- **Discovery:** 2026-08-27 Reward audit.
- **Evidence:** `training/rl/reward_v2.py` uses gold-source coverage while process cost is secondary.
- **Scope:** search efficiency, context pollution, citation quality and long-horizon cost.
- **Why systemic:** the easiest strategy can become reading many sources until the gold set is included.
- **Competing explanations:** early exploration may require broad recall before the policy learns precision.
- **Minimal falsification:** compare trajectories with equal answer quality but different irrelevant-read ratios.
- **Root cause:** a closed gold set was easier to verify than marginal evidence utility.
- **Fix:** track claim support, evidence precision, marginal evidence gain and cost; keep shaping small until calibrated.
- **Regression:** benchmark slices report useful-read precision and cost per supported claim.
- **Before/after:** gold-source recall -> utility-aware evidence selection.
- **Residual risk:** penalizing breadth can hurt genuine deep research.
- **Interview 60s:** discuss why retrieval recall and Agent efficiency are different objectives.
- **Deep dive:** use family-specific cost frontiers instead of one global tool penalty.
