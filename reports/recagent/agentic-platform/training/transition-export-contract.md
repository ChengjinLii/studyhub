# PR11 Transition Export Contract

## Scope

PR11 prepares replay and training data interfaces only. It does not start a
trainer, import Search-R1/veRL into FastAPI, choose an RL algorithm, or attach
reward weights to the online Agent runtime.

`TransitionJsonlSink` is an explicit `AgentKernel` Transition Sink injection.
The kernel still receives its Policy, Skill registry, executor, and safety
boundaries from the caller. Export does not introduce a required Skill order,
intent classifier, replan cap, or hidden agent loop.

## Layout

Given an explicitly configured export root, one `thread_id` + `run_id` maps to
a path-safe trajectory ID and produces:

```text
transitions/<trajectory-id>.jsonl   # canonical AgentTransitionEvent rows
model_io/<trajectory-id>.jsonl      # token-preserving ModelIORecord rows
manifests/<trajectory-id>.json      # file hashes and state endpoints
quarantine/<trajectory-id>-.../     # isolated malformed/inconsistent trace
```

The canonical JSONL rows preserve the existing bounded Artifact references and
structured decisions. They do not copy a raw prompt, PDF body, tool secret, or
private chain-of-thought into the training export.

## Token and reward contract

- `token_ids` are copied directly from the rollout; no export path tokenizes
  text again.
- `TokenRoleSpan` is converted to `trainable_token_mask`. Only
  `assistant_action` and `assistant_final` can be `true`.
- System, user, tool-observation, and user-simulator-observation positions are
  always false in the mask.
- `RewardFacts` remains factual and now carries an optional
  `quarantine_reason`; reward-policy math is left to a future training job.

## Corruption handling

Malformed JSONL, invalid manifests, duplicate IDs, incompatible model-I/O rows,
overlapping token spans, and explicit runtime quarantine facts preserve their
source files under `quarantine/`. They are never silently treated as successful
training examples. A valid later retry starts a fresh active trajectory while
the rejected material remains available for audit.

## Offline adapters

`ml/agentic_platform/adapters/search_r1/` maps Model-I/O rows to the historical
`data_source`, `prompt`, `ability`, `reward_model`, and `extra_info` shape.
`ml/agentic_platform/adapters/verl/` consumes only the four-method
`AgentEnvironment` interface (`reset`, `step`, `snapshot`, `restore`). Both are
dependency-free boundaries for a future, separately version-locked training
environment.
