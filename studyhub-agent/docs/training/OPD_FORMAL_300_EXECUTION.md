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
