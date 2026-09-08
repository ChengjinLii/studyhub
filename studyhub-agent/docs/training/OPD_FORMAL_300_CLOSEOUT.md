# Formal OPD closeout audit (2026-09-08)

Run: `qwen35-4b-opd-formal-seed-20260827-attempt-20260907_115956`.
The training log records ordered updates 1 through 300, all successful,
with LR 3e-6. Final global step is 299; the last update completed at
2026-09-08 03:20:56 +08:00. Launcher exit status was not captured. The
cause of the missing launcher postprocessing is unknown; the old metadata
and stopped/waiting evaluation records have not been rewritten as successes.

## Checkpoint verification

- M2 initialization is exact across 208 adapter tensors.
- All 208 final tensors are finite and changed from M2.
- DCP LoRA tensors match the final adapter exactly; all 208 optimizer steps are 300.
- Recovery metadata identifies global step 299. DCP storage extents and file
  hashes were verified, without starting a load/resume training experiment.
- Final adapter SHA256: `6551b6ae3fdf242561a13aae5c7379b12526c746894320cad13fd227b7995ca8`.

## Rollout accounting

Raw reward logs contain 4,802 rows: 4,801 SCORED and one INFRA_EXCLUDED
(`context_budget_finalization_failed`). The associated two-response task group
is absent from every training export. The frozen workflow raises on infra
failures and requires complete groups. Exports contain exactly eight task groups
for each policy version 0 through 299, giving 2,400 groups / 4,800 episodes.
Per-task reward multiplicities match those exports. The accepted cohort and the
two excluded records are both preserved in the evidence bundle; no failure was
silently discarded or reclassified as successful.

The original stage verifier was rerun unchanged on this reconciled cohort:
OPD_COMPLETE, final loss 0.13766, mean loss 0.12093623, 1,123,630 teacher-scored
tokens, mean tool validity 0.9088968265. These are training diagnostics, not
independent model quality results.

## Evidence and evaluation

Canonical artifact root: `/data/chengjin/studyhub/studyhub-agent`.
Evidence: `artifacts/experiments/<run>/recovered-closeout.json`, plus trainer,
GPU, checkpoint, raw trajectory indexes and hashes. The original evidence
completeness remains PARTIAL_EVIDENCE solely for unknown process exit status.
The separate audit grants PASS_CHECKPOINT_FOR_EVALUATION on verified weights.
The reconstructed completion marker explicitly binds that audit and retains
`original_exit_status: null` and `completion_reconstructed: true`.

Evaluation may use `--closeout-audit` only after checking its source metadata,
artifact hashes and adapter binding. It does not invent a successful launcher
exit. Fresh M2 and OPD evaluation uses the existing Protocol128, Development51,
BFCL70 and tau2-15 panels with unchanged metrics. No training is rerun and no
Sealed data is used.

The first evaluation launch on September 8 failed before model loading: shared
GPU admission required 64,000 MiB but the own-process cap plus reserved headroom
required 76,000 MiB. All eight stage exits were infrastructure failures, not
model scores. That suite remains preserved under
`artifacts/evaluation-suite/qwen35-4b-opd-closeout-20260908`.
The retry uses a consistent 76,000 MiB admission check while retaining the
64,000 MiB own-memory cap and 12,000 MiB runtime reserve. It reuses the verified
merged checkpoint and writes a new output directory.

The managed retry then exposed a separate server argument bug: a randomly
generated temporary key beginning with a dash was parsed as an option.
Both Protocol servers exited before inference. The service was stopped;
its output remains in the `-managed` directory. Passing `--api-key=<value>`
fixes argument parsing without changing authentication or evaluation settings.
