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
   and isolate AReaL's process-wide TMS region in `SGLangBackend.build_server_env`
   only for the new inference subprocess. The 12:47 attempt proved scheduling
   environment overrides ineffective: colocated workers inherit the actor's
   environment. Otherwise SGLang's tagged regions nest inside the inherited
   region and fail at initialization. Actor offload
   remains enabled. Do not bypass the 79,000 MiB/foreign-process guard.
5. A subsequent real rollout exposed SGLang's separate weight-backup contract:
   `enable_memory_saver` alone reallocates parameters without restoring their
   values. Since OPD reloads only adapters, enable the official
   `enable_weights_cpu_backup` option. The aborted attempt produced four
   incoherent, zero-tool trajectories and no optimizer update; it is excluded
   from all policy-quality claims. CPU-backup unit probes with explicit backup
   did not establish that the model loader actually enabled that option.
6. Explicitly disable thinking on every OPD request, using both chat-template
   kwargs and the existing AReaL metadata bridge. Previously only forced-final
   requests disabled it, inconsistent with the declared M2/teacher contract.
   Other workflows keep their prior default.

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

## First nonzero-LR execution

Attempt `20260905_134214`, run commit `f035f75`, completed eight optimizer
steps before the GPU guard stopped our process group at 14:00:28 +08:00.
An unrelated compute PID `1145327` appeared on GPU 1. Its owner was not
established; no external process was killed. This is a resource interruption,
not a completed 16-step probe or an Agent quality result.

- First step used the existing zero-LR warmup; seven subsequent steps used 1e-6.
- All eight reported `update_successful=1`, finite loss and gradients.
- Teacher scored 5,935 assistant tokens; 103 exported interactions span policy
  versions 0 through 7. All have exactly one v3 system prompt.
- GPU peaks: 65,864 MiB and 48,157 MiB. No OOM occurred in this attempt.
- 33 completed reward rows include one response from an interrupted group;
  only 16 complete two-response groups fed the eight completed updates.
- No final saved adapter exists: the original save cadence was 16. Logs show
  optimizer execution, but an initial/final file-hash comparison is NOT_DONE.
- Real multi-turn tool calls are present. Per-interaction export resets turn
  indices, so `opd_active_turns=1` must not be reported as episode-level depth.

Evidence is under the canonical artifact root at
`artifacts/experiments/qwen35-4b-opd-lr1e6-seed-20260827-attempt-20260905_134214/corrected-evidence/`.
Its artifact-completeness status concerns available files, not training success.
The raw shared rollout files remain intact. A manifest records the pre-run
37/57-row prefixes removed from the version-0 snapshot; later versions are new.

The next LR probe retains the same data, objective, learning rate and seed.
Save its adapter every step and use an attempt-specific AReaL artifact root.
These are evidence-preservation changes, not a new training recipe. An adapter
snapshot alone is not an optimizer/RNG recovery checkpoint; LR retries still
start independently from M2. Keep the foreign-process guard enabled.

## Saved weight update and shared-GPU interruption

Attempt `20260905_141157`, run commit `9e9f706`, saved global steps 0 and 1.
The zero-LR step is tensor-identical to M2. At step 1, all 208 LoRA tensors
differ from M2, with adapter SHA256
`b2a59db43442d704e0ac2197ac199c6180d94aaab20e1ffb84b0f333355264f6`.
Two optimizer steps are logged, one at nonzero LR, with 1,024 scored assistant
tokens. This proves a saved distillation update, not a completed probe.

At 14:19:43 the separate process inventory captured GPU 1 PID `1192213`,
UID `1001`, PGID `1192213`; training workers use UID `1002`, PGID `1175168`.
Thus the interruption is not an AReaL child-process classification error.
The launcher exited 70 after stopping only its own process group. Do not relax
the resource guard or repeatedly reload models into a busy GPU window.

Full attempt artifacts and checkpoint hashes are preserved under
`artifacts/experiments/qwen35-4b-opd-lr1e6-seed-20260827-attempt-20260905_141157/`.
Tracked summary: `docs/training/evidence/qwen35-4b-opd-saved-update-20260905.json`.
The 16-step probe, second LR probe, 64-step pilot, formal run and downstream
comparison are still incomplete/not run. No model-quality conclusion is made.

## User-authorized shared GPU policy

The subsequent user instruction explicitly permits coexistence with other GPU
jobs when StudyHub uses fewer resources. This supersedes the earlier exclusive
foreign-PID stop policy for this OPD experiment only. The old deferred idle-only
launcher has been cancelled. Generic launchers remain exclusive by default.

- SGLang static model/KV allocation: 0.65 -> 0.40; serving and rollout
  concurrency: 4 -> 2. This follows SGLang's documented memory-pool controls,
  not quantization, a new teacher, or a different distillation objective.
- Per selected GPU, admission needs 64,000 MiB free. Runtime monitors cap our
  process group's aggregate memory at 52,000 MiB and all use at 68,000 MiB,
  retaining at least 12,000 MiB free. Foreign PIDs alone no longer cause a stop.
- Other jobs may grow into the remaining space. If the reserve or either cap
  is breached, only our process group is stopped. Unknown process-memory
  accounting also fails closed. No other job, clock, power limit or MPS setting
  is changed.
- Telemetry separately records owned/external memory and external process count.
  These are sampled application guards, not a hard VRAM partition or a guarantee
  of isolated GPU compute throughput. Lower concurrency can still affect timing
  and stochastic rollout ordering; do not claim bitwise-equivalent trajectories.
- The model, M2 initialization, teacher, data, seed, learning rates, group size,
  per-mode batch/update counts, context budget and OPD loss remain unchanged.
  This is another independent M2-starting 16-step probe, not continuation from
  the interrupted adapter without optimizer state.

The new policy is fixed in the program, authorization and run metadata.
Primary reference: [SGLang memory and scheduling arguments](https://docs.sglang.io/docs/advanced_features/server_arguments).
