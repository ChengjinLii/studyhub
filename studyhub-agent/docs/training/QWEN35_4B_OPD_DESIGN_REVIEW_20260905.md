# 4B <- 9B OPD: pre-run review, 2026-09-05

## Decision

Proceed with a bounded distillation pilot, not an unconditional 300-update run.
Student is the completed compact SFT2 M2 adapter (`4b7ee7462d82cd17...`);
teacher is Qwen3.5-9B revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`.
No new teacher collection, Spark, bulk task generation, Sealed access, website
changes, or main GRPO is needed.

The existing 500-task screening found teacher 241, student 165, teacher-only
126, and student-only 50 successes. Teacher advantages are concentrated in
function calling, memory and recovery. Direct answering and RAG are retention
risks, not demonstrated teacher strengths. This supports a targeted policy
transfer experiment, not a claim of broad Agent superiority. The screening
panel informed training selection and must not serve as held-out post-training
evidence.

## Corrections before this run

1. The previous recorder required mean teacher-minus-student log probability
   to be positive. That is not a distillation success criterion. Under full
   student-distribution expectation the difference is negative reverse KL;
   our unweighted top-k diagnostic is not even that expectation. Use absolute
   token gaps, finite loss, scored assistant tokens, gradients and actual LoRA
   updates for runtime health. Preserve the signed metric as a diagnostic.
   Independent task outcomes determine whether the model improved.
2. The previous validation selector took the tail of teacher-ranked tasks;
   function calling, memory and recovery were absent. Pool v1.1 reserves a
   family-balanced 128-task panel before ranking, excluding every source group
   in the 500-task screening. Training has 2,000 groups, validation 128, overlap
   zero. All 126 observed teacher-only successes remain in training. The new
   panel is balanced for family diagnostics, not a population-weighted estimate.
   Existing v1 evidence is unchanged; all tasks come from the existing 5,908
   audited candidates. No new tasks or teacher trajectories are generated.
3. Rollout accepts 16K contexts, but the former actor microbatch cap was 1,536
   tokens. Accept 16K individual sequences while requesting 128 microbatches,
   enough to isolate at most 8 prompts x 2 samples x 6 turns per update.
   This changes packing, not the global batch or token-mean objective.
4. Colocated SGLang must actually release memory. Enable its memory saver,
   and use scheduling environment variables to disable AReaL's process-wide
   TMS region only for the rollout worker. Otherwise SGLang's tagged regions
   nest inside the inherited region and fail at initialization. Actor offload
   remains enabled. Do not bypass the 79,000 MiB/foreign-process guard.

## Unchanged algorithm and execution

Use the pinned [THUNLP OPD recipe](https://github.com/thunlp/OPD/tree/ac26e38d6f1572eb027597b48a9f4e01f6915ef8):
`token_reward_direct`, student top-k 16, `student_p`, detached teacher scores,
sum over k then assistant-token mean. The 4B student executes real Hermes tool
rollouts; the frozen 9B scores the same student-visited contexts and does not
execute tools or receive hidden verifier answers. Environment rewards remain
diagnostic, not the optimized distillation target. AReaL is a local port of the
recipe, not the original upstream verl runner or a published-result replication.

Keep LoRA r32/alpha32, thinking disabled, seed 20260827, student temperature 0.7,
teacher temperature 1.0, two responses per prompt. Both 16-update LR probes
(1e-6, 3e-6) start independently from M2 on the same pool and seed. Then freeze
one LR, run 64 updates, and consider 300 only after healthy training and no
material task-level regression. Do not select a learning rate merely because
its signed teacher log-prob gap is larger.

Evaluation must compare frozen M2 and the pilot on the same v1.1 panel, with
per-family outcomes, tool validity, truncation, calls and stopping behavior.
AgentBench Development and official external tests remain evaluation-only.
Positive token diagnostics alone do not establish downstream benefit.

## Evidence and current limits

- Pool manifest: `docs/training/evidence/qwen35-4b-opd-pool-v1-1.json`.
- Config and dataset hashes are frozen in the regenerated authorization.
- Attempt-specific metadata, logs, telemetry and checkpoints remain separate.
- Startup failure on 20260905_122745 occurred before any optimizer update;
  it is not a failed model-quality result.
- GPU execution and downstream benefit after these corrections must be reported
  from actual run artifacts, not inferred from this design review or unit tests.
