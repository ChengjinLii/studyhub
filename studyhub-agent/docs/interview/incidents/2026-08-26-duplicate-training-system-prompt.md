# Duplicate Training System Prompt

## Classification

- Evidence: `A_REAL_REPRODUCED` for the runtime defect; no capability claim.
- Discovery: natural observation in a completed 10-step Direct GRPO Smoke.
- Affected trial: `direct-smoke-seed-6209-20260825_230016`.
- Regression trial: `direct-gate-seed-6210-20260826_033013`.

## Problem

Hermes builds its normal system message through `_build_system_prompt()` and then appends `ephemeral_system_prompt`. The StudyHub workflow replaced the builder with the frozen training prompt but also passed the same text as the ephemeral prompt. Every model request therefore saw the training policy twice.

## Evidence

The raw AReaL rollout export was indexed without copying prompt text into the report. The index counts a fixed StudyHub prompt marker in every rendered interaction.

| Trial | Exported interactions | Missing marker | Duplicated marker | Exactly once |
| --- | ---: | ---: | ---: | ---: |
| 10-step Smoke before fix | 1,160 | 0 | 1,160 | 0% |
| 1-step Gate after fix | 118 | 0 | 0 | 100% |

Evidence files:

- `artifacts/experiments/direct-smoke-seed-6209-20260825_230016/metrics/rollout-interactions.json`
- `artifacts/experiments/direct-gate-seed-6210-20260826_033013/metrics/rollout-interactions.json`
- `artifacts/experiments/*/trajectories/trajectory-records.jsonl`

## Competing Explanations

1. The prompt may have appeared twice only in the exported representation. This was rejected by inspecting the raw request prompt before indexing.
2. Hermes conversation replay may have copied prior turns. This was rejected because the duplicated text was present in the first exported interaction for each task.
3. AReaL may have prepended its own policy prompt. This was rejected by tracing the two identical copies to the Hermes builder and ephemeral append paths.

## Fix

`training/rl/hermes_workflow.py::_install_training_system_prompt()` now:

1. Replaces `_build_system_prompt()` with the frozen StudyHub prompt.
2. Clears both Hermes prompt caches.
3. Sets `agent.ephemeral_system_prompt = None`.

The workflow constructor no longer supplies an ephemeral copy. A unit test asserts the resulting builder output and the cleared field.

## Regression Result

The post-fix Gate completed one real PPO update with a changed LoRA hash, `mask_no_eos_with_zero=1`, entropy `0.22843`, and all 118 exported interactions containing exactly one prompt marker. GPU0 peaked at 66,714 MiB, below the 68,000 MiB guard.

The pre-fix Smoke checkpoint remains available as diagnostic evidence but is excluded from the healthy Pilot lineage.

## Reproduction

```bash
STUDYHUB_ALLOW_TRAINING=YES \
  bash scripts/train/run_controlled_grpo.sh 4b direct gate 6210
```

Then inspect `metrics/rollout-interactions.json` in the generated evidence bundle.

## Residual Risk

Hermes and AReaL still emit prefix-cache mismatch warnings during multi-turn tool use. The post-fix prompt marker evidence shows these warnings are not duplicate-system-prompt events, but cache behavior remains an upstream runtime diagnostic rather than a StudyHub training claim.
