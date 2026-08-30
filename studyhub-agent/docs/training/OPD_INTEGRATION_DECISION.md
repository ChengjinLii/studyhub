# OPD Integration Decision

## Scope

The controlled 4B track selects the exact THUNLP OPD recipe below:

```text
adv_estimator      = token_reward_direct
log_prob_top_k     = 16
top_k_strategy     = only_stu
reward_weight_mode = student_p
loss aggregation   = sum over K, then token mean
reference KL       = off
```

The algorithm source is locked to `thunlp/OPD@ac26e38d6f1572eb027597b48a9f4e01f6915ef8`.
The candidate runtime is locked to official `verl@ea53291385ce764019a2b40733605f21d8317583`.
Exact source hashes are recorded in `training/opd/upstream.lock.json`.

## Source Semantics

For every student-visited prefix, the THUNLP recipe:

1. selects the student's top-k token IDs;
2. evaluates teacher log probabilities on those same IDs;
3. computes conditional student weights by normalizing the student probabilities inside that top-k set;
4. creates the detached wing reward
   `A_i = (log p_teacher(i) - log p_student(i)) * weight_student(i)`;
5. applies the binary assistant response mask;
6. updates the student through the 3D on-policy PPO surrogate;
7. sums the k wing losses at each response position, then applies token-mean aggregation.

This is a policy-gradient surrogate with detached token rewards. It must not be described as direct differentiation
through a full-vocabulary reverse KL.

## Official verl Difference

The pinned official verl runtime provides the preferred teacher resource pool, agent-loop plumbing, FSDP/LoRA
integration, and two native distillation families:

- sampled-response-token reverse-KL estimators such as `k1`;
- teacher-top-k `forward_kl_topk` with direct loss backpropagation.

Neither is numerically identical to THUNLP `only_stu + student_p + token_reward_direct`. The official teacher-top-k
path chooses teacher IDs, while the selected recipe requires teacher scores on student-selected IDs. Renaming either
native loss would invalidate the controlled experiment.

## Decision

Use official verl as the operational base only after adding the smallest explicit compatibility extension that supplies:

```text
student top-k IDs
        -> frozen teacher scores those IDs at the same visible prefix
        -> detached 3D token rewards
        -> THUNLP-compatible on-policy surrogate
```

The independent implementation in `training/opd/token_reward_parity.py` is the mathematical oracle. It checks top-k
selection, student weighting, masking, K aggregation, token-mean loss, and gradient direction using finite differences.
It deliberately has no torch or verl dependency. `training/opd/verl_compat.py` is a separate Torch candidate kernel;
the compatibility spike requires its tensors, scalar loss, and backward gradient to match that oracle.

Passing this mathematical gate does **not** authorize OPD training. Before a GPU pilot, the actual verl compatibility
extension must reproduce the same fixed tensors and gradients, and the following independent gates must also pass:

- M2 exists and is frozen;
- 4B/9B tokenizer and thinking contracts pass;
- the 9B teacher novelty probe passes;
- the Hermes student rollout and teacher prefix inputs are visibility-identical;
- assistant-token masking is correct across multiple turns;
- the 2-GPU runtime backend parity gate passes.

Until then, runtime status remains `NOT_RUN`; official `k1` and `forward_kl_topk` remain optional, separately named
ablations rather than substitutes for the primary recipe.
