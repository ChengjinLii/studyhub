# OPD formal 300-update execution

## Frozen recipe

The 64-update pilot completed with `OPD_PILOT_PASS`: 512 rollouts,
92,143 teacher-scored tokens, and final adapter SHA256
`4539a1efe2d3ec301f7ae0e5166242edf81a28251da15f747575909341213fbf`.
This is an execution gate, not evidence of downstream improvement.

Formal starts independently from the frozen M2 adapter, not the pilot weights.
Keep LR 3e-6, batch 8, two responses per prompt, 300 optimizer updates,
and the existing 2,000-task training pool. AReaL's epoch ceiling must be two:
one epoch permits only 250 updates. The step cap remains 300, consuming
2,400 prompt slots (a partial second pass), not 2,400 unique tasks.
No data, objective, LoRA, teacher, or benchmark changes are introduced.

Save checkpoints/recovery every 50 updates. Keep the existing eight-hour
wall-time limit and shared GPU memory guards. Completion requires the actual
300-update marker, changed finite LoRA tensors, and auditable run evidence.
An interrupted run is not a completed experiment.

## Independent evaluation

After completion, evaluate the final adapter against the frozen M2 using the
same protocol, public AgentBench Development, BFCL and tau2 subsets. Reuse
existing evaluators and task selections; verify baseline model/task hashes.
Keep raw results, task-paired summaries, infra exclusions, and checkpoint
lineage. Do not use Sealed or the teacher-selection panel as a final test.
Report task outcomes separately from OPD loss and tool validity; no capability
improvement claim is justified until the independent comparisons finish.

The follow-up script is `scripts/train/run_qwen35_4b_opd_evaluation_suite.py`.
It waits for the specific launcher's successful exit and the formal completion
marker, validates adapter/authorization/benchmark hashes, then CPU-merges the
adapter and sequentially runs both M2 and OPD on the same four fixed panels.
Protocol uses 128 rows (multiple assistant-turn items per row), AgentBench uses
51 Development tasks, BFCL uses 70 public cases, and tau2 uses 15 public tasks.
The existing tau2 config retains seed 20260830; the other panels retain 20260827.
These are public diagnostic comparisons, not new unseen holdout results.

The old M2 protocol summary contains nine infra-excluded items and the old
tau2 manifest is incomplete. Neither is treated as a complete comparison:
both models will be freshly evaluated under identical scripts/configurations.
Policy failures remain results; missing outputs and infra exclusions remain
explicit failures or partial results, not zero-success model scores.

Training and evaluation use separate clean worktrees. Evaluation starts only
after training completes and memory headroom returns. It retains GPU telemetry,
raw outputs, commands, config hashes, model lineage and paired AgentBench counts
in its output directory. `suite.json` is the live status, not a completion claim;
`PARTIAL_EVALUATION` or `STOPPED` requires follow-up, not automatic promotion.
