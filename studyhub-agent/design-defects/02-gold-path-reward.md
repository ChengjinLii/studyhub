# Gold-path and expected-call Reward

- **Defect:** v2 verifiers reward exact expected calls and gold source sets, which can reject a different valid trajectory.
- **Discovery:** 2026-08-27 v3 baseline audit.
- **Evidence:** `training/rl/reward_v2.py` and `scripts/data/build_open_rl_tasks.py` contain `expected_calls` and `gold_source_ids` semantics.
- **Scope:** function calling, search, multi-hop retrieval and any open-path Agent task.
- **Why systemic:** the policy learns route imitation rather than goal completion and can be punished for useful exploration.
- **Competing explanations:** exact routes remain appropriate for a small class of deterministic fixture tests.
- **Minimal falsification:** create 100 alternative valid trajectories that reach the same end state and measure Reward v2 false-negative rate.
- **Root cause:** static open datasets supplied one demonstrator route, which was reused as the verifier.
- **Fix:** Reward v3 grades hard constraints, objective end state, semantic rubric and verifiable process signals.
- **Regression:** the v3 task schema rejects gold trajectory/query/source-order fields from policy-visible data.
- **Before/after:** expected sequence equality -> path-agnostic outcome and support evaluation.
- **Residual risk:** rubric judges may accept fluent but weak alternatives without calibration.
- **Interview 60s:** show how a correct end state can be reached through several tool sequences.
- **Deep dive:** separate deterministic transactions from open research tasks in the Reward contract.
