# RL Task Budget Contract and QASPER Annotation Binding

## Classification

- Evidence: `A_REAL_REPRODUCED` for the data-contract defect; no model-quality claim.
- Discovery: natural audit before the v2 Pilot.
- Affected data: `open_agent_rl_v1`.
- Regression data: `open_agent_rl_v2` and `open_agent_rl_dev_eval32_v2`.

## Problem

The runtime had been reduced to six model turns while public RL tasks still declared
up to ten steps and eight tool calls. The v1 QASPER adapter also combined answers and
evidence from different annotators. That union could require the policy to read many
unrelated paper sections before producing one answer, so some tasks were impossible
under either the public tool budget or the actual Hermes runtime budget.

## Evidence

The audit infers a conservative reference path for grounded tasks:

```text
one search + one read per required source + one final model turn
```

| Dataset | QASPER tasks | Reference path over 6 turns | Required calls over 8 | Maximum gold sources |
| --- | ---: | ---: | ---: | ---: |
| RL v1 | 600 | 35 | 15 | 21 |
| RL v2 | 600 | 0 | 0 | 4 |

The v2 independent audit covers all 2,400 tasks and reports:

- zero task and group overlap between train and validation;
- zero overlap with selected SFT source/group lineage;
- no public oracle fields;
- no budget-contract violations;
- reference model turns in `[2, 6]` and required tool calls in `[1, 6]`.

Local evidence:

- `artifacts/areal/rl-budget-transition-v1-v2.json`
- `datasets/processed/open_agent_rl_v2/budget-audit.json`
- `artifacts/areal/open-rl-dataset-audit-v2.json`
- `datasets/processed/open_agent_rl_dev_eval32_v2/manifest.json`

## Competing Explanations

1. Parallel tool calls might make every task feasible. This does not resolve the 15
   v1 cases whose required calls exceeded the public tool budget, and it is not a safe
   assumption for sequential search/read trajectories.
2. The model could answer without reading every gold source. Reward v2 requires the
   hidden gold evidence set for grounded tasks, so skipping required sources cannot be
   treated as the reference success path.
3. Raising `max_turns` back to ten would avoid rebuilding data. It would increase
   sequence cost and still leave the 15 tool-budget violations and annotation mismatch.

## Root Cause

- The runtime limit and dataset task budget were configured independently.
- QASPER answers and evidence were unioned across annotators instead of binding one
  answer to its own evidence annotation.
- No fail-closed feasibility audit compared hidden verifier requirements with the
  public task and runtime budgets.

## Fix

`training/rl/budget_contract.py` is now the shared source of truth for six model turns
and six tool calls. Dataset v2 stores a hidden per-task budget contract and rejects any
candidate whose reference path cannot finish within it.

The QASPER adapter selects one deterministic canonical annotation, keeps that answer
bound to only its own evidence, prefers feasible answerable annotations, and uses an
unanswerable annotation only when necessary. Function-calling adapters preserve the
number of sequential assistant tool rounds and include a final-answer turn.

The verifier, preflight, and unit tests independently recompute the contract. Eval32 v2
inherits the same policy and is frozen by manifest and task hashes.

## Regression Result

The rebuilt dataset contains `2,000 train / 400 validation` tasks. Its full audit and
the CPU-only controlled-experiment preflight both pass. All 71 project tests pass from
a normal shell, including annotation binding, infeasible-task rejection, exact Eval32
group size, Hermes tool-loop integration, and oracle isolation tests.

No GPU result from v1 is reused as a v2 paired comparison. The previous healthy Smoke
remains diagnostic runtime evidence only; Base Eval and Pilot are rerun on v2.

## Reproduction

```bash
bash studyhub-agent/scripts/train/prepare_controlled_experiment.sh verify
```

The command performs model, SFT, RL v2, Eval32 v2, upstream-lock, and runtime checks
without starting a trainer.

## Residual Risk

The reference path is deliberately conservative. A model may batch parallel function
calls in fewer turns, while difficult search tasks may need query reformulation beyond
the reference. Pilot metrics must therefore still report budget exhaustion, premature
final answers, tool loops, per-family success, and sequence truncation rather than
assuming that static feasibility guarantees practical solvability.
