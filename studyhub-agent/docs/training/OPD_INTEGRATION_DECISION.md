# OPD Integration Decision

## Frozen Recipe

The controlled 4B experiment uses the exact THUNLP recipe below:

```text
adv_estimator      = token_reward_direct
log_prob_top_k     = 16
top_k_strategy     = only_stu
reward_weight_mode = student_p
loss aggregation   = sum over K, then token mean
reference KL       = off
```

The algorithm source is locked to
`thunlp/OPD@ac26e38d6f1572eb027597b48a9f4e01f6915ef8`. Official
`verl@ea53291385ce764019a2b40733605f21d8317583` and the existing StudyHub
`AReaL@cbff54d645d2cd8ee1f1c358a82f3f473588433d` runtime are locked as
independent implementation references. Critical source hashes are recorded in
`training/opd/upstream.lock.json`.

## Algorithm Semantics

For every student-visited prefix, the selected recipe:

1. selects the student's top-k token IDs;
2. evaluates teacher log probabilities on those same IDs and visible prefix;
3. normalizes student probabilities inside that top-k set;
4. creates detached wing rewards
   `A_i = (log p_teacher(i) - log p_student(i)) * weight_student(i)`;
5. masks everything except student-generated assistant tokens;
6. applies the three-dimensional on-policy PPO surrogate;
7. sums the K wing losses at each token and then takes a token mean.

This is a policy-gradient surrogate with detached token rewards. It is not
direct differentiation through a full-vocabulary reverse KL.

## Why Official verl Is Not the Runtime

Pinned official verl contains sampled-token reverse-KL estimators and a
teacher-top-k `forward_kl_topk` path. Neither is numerically identical to
THUNLP `only_stu + student_p + token_reward_direct`: the latter requires the
teacher to score student-selected token IDs. Calling either native verl loss
"OPD" would change the experiment.

Porting the already validated StudyHub Hermes workflow, frozen tool
environment, verifier, LoRA publication, and recovery path into verl would be a
second runtime implementation and a larger uncontrolled change. The current
experiment therefore keeps AReaL as the operational harness and adds only the
missing OPD operations.

## Chosen Integration

The primary implementation is a process-local AReaL extension:

```text
student Hermes rollout in AReaL
        -> actor computes student top-k IDs and anchor log probabilities
        -> frozen 9B teacher scores those IDs on the identical visible prefix
        -> detached THUNLP token rewards
        -> strict 3D on-policy update
        -> standard AReaL LoRA publication, checkpointing, and recovery
```

`training/opd/areal_runtime.py` supplies the sparse actor and teacher forward
operations and the update kernel. `training/runtime_shims/sitecustomize.py`
installs the extension only when `STUDYHUB_AREAL_OPD_BRIDGE=1`; upstream AReaL
and Hermes source trees remain unchanged. The actor is initialized from the
frozen M2 LoRA adapter and its path, rank, alpha, target modules, tensor count,
nonzero values, and weight hash are checked before training.

The runtime records token-weighted loss, teacher log-probability advantage,
student/teacher top-k mass, conditional top-k KL, conditional entropy, top-k
overlap, reward distribution, scored tokens, and per-turn slices. These are
diagnostics; promotion still depends on independent task evaluation.

## Gates

The pure-Python mathematical oracle and Torch compatibility kernel pass their
fixed tensor and gradient checks. This does not establish GPU runtime parity or
model quality. A real OPD pilot remains blocked until all of the following are
true:

- M2 exists, is evaluated, and its adapter is frozen;
- 4B/9B tokenizer and non-thinking contracts pass;
- the 500-task teacher novelty probe passes, including at least 20
  teacher-only successes;
- OPD prompts are disjoint from SFT, protocol holdout, AgentBench, BFCL, and
  tau2;
- the process-local extension and all three upstream locks pass preflight;
- a two-GPU runtime Gate proves identical visible prefixes, assistant-only
  masking, a successful optimizer update, and a changed LoRA hash.

Until that Gate runs, `runtime_backend_parity` and OPD model effect remain
`NOT_RUN`.
