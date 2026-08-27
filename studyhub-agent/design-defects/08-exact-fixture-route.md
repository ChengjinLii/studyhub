# Exact fixture route penalizes valid paths

- **Defect:** deterministic fixtures treat one argument set or call route as the successful behavior.
- **Discovery:** 2026-08-27 Reward/environment audit.
- **Evidence:** v2 function fixtures and `expected_calls` are coupled in `scripts/data/build_open_rl_tasks.py` and `training/rl/reward_v2.py`.
- **Scope:** multi-call tasks, equivalent arguments, retries and recovery.
- **Why systemic:** equivalent normalized parameters or an extra harmless verification call can receive a lower score.
- **Competing explanations:** exact argument equality is correct for some atomic APIs.
- **Minimal falsification:** author alternative legal calls and compare final environment state against exact-route scoring.
- **Root cause:** fixture match was used as a proxy for postcondition success.
- **Fix:** define simulator state transitions and acceptable postconditions; reserve exact matching for schema regression only.
- **Regression:** alternative-route tests must reach identical state and receive equivalent outcome credit.
- **Before/after:** route equality -> end-state equality plus cost diagnostics.
- **Residual risk:** simulators can still omit real-world side effects.
- **Interview 60s:** give an example where two call orders are both valid.
- **Deep dive:** model idempotency, side effects and transaction invariants.
