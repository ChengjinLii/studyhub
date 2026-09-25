# 4B / 9B Training Readiness

> **Historical v2 document.** It preserves the original 3k SFT / 2.4k RL
> reproduction contract. It is not the current 9B training entry point. See
> `StudyHub_9B_Agentic_Post_Training_Program_v3.html` for the active program.

## Current state

- `Qwen/Qwen3.5-4B` is fixed at revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` under `models/P1/Qwen3.5-4B`.
- `Qwen/Qwen3.5-9B` is fixed at revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a` under `models/P1/Qwen3.5-9B`.
- AReaL `2.0.0` is fixed at commit `cbff54d645d2cd8ee1f1c358a82f3f473588433d`; SGLang is `0.5.10.post1`.
- Hermes is a clean checkout fixed at commit `5c1a304ce890276a4334d8ced3f29ffeedbbbf93`.
- A real 4B Direct GRPO Gate and 10-step Smoke have completed as diagnostic runtime
  evidence. Full SFT, the v2 paired evaluations, and claim-bearing RL runs have not
  completed yet.

Models, datasets, checkpoints, logs, and generated audits are Git-ignored.
Configs, builders, verifiers, launchers, and this document are tracked source.

## Prepared data

The 4B and 9B SFT datasets use the same 3,000 source records and split groups,
but are compiled independently with the official tokenizer for each model.

| Source | Records | SFT role |
| --- | ---: | --- |
| ToolACE | 300 | Tool protocol and arguments |
| Hermes Function Calling | 300 | Function calling and JSON serialization |
| 2WikiMultihopQA | 900 | Multi-hop reasoning over supplied evidence |
| QASPER | 600 | Grounded paper QA and insufficient-evidence behavior |
| COIG Exam | 900 | Chinese educational answers and explanations |

Each tokenizer-specific dataset contains `2,550 train / 300 validation / 150 test`
records. Group overlap is zero; the maximum sequence length is 2,021 tokens.

RL uses separate source groups and exposes only Task, tool schema, and frozen
environment data to the model:

| Family | Train | Validation | Environment |
| --- | ---: | ---: | --- |
| Function calling | 667 | 133 | Deterministic fixture tools |
| Search / multi-hop | 833 | 167 | Frozen 2Wiki corpus with search/read |
| Evidence grounding | 500 | 100 | Frozen QASPER papers with search/read |

Gold answers, tool sequences, and evidence labels remain in server-side
verifiers. The RL audit confirms zero SFT overlap and zero train/validation
group overlap. ToolACE multi-round conversations are converted as one complete
tool trajectory; an intermediate tool call is never treated as the final answer.
RL v2 also binds each QASPER answer to one canonical annotation and rejects any
task that cannot complete within the shared six-model-turn/six-tool-call budget.

The frozen 32-task development evaluation uses four rollouts per task. Its v2
protocol requires stable request seeds, deterministic SGLang inference, exact
four-sample groups, a zero optimizer learning rate, and identical initial/final
LoRA hashes. It is a development set, not a sealed final benchmark.

## Experiment branches

For each scale, the launchers support `B0 Base`, `B1 SFT`, `B2 Direct RL`, and
`B3 SFT -> RL`. B1 and B3 share one SFT checkpoint. B3 starts from a CPU-merged
copy of that LoRA adapter; B2 starts from the official base model.

```bash
# Full CPU-only validation; never trains.
bash studyhub-agent/scripts/train/prepare_controlled_experiment.sh verify

# Default mode is also check-only.
bash studyhub-agent/scripts/train/run_controlled_sft.sh 4b check
bash studyhub-agent/scripts/train/run_controlled_grpo.sh 4b direct check
bash studyhub-agent/scripts/train/run_controlled_grpo.sh 4b sft check
```

After a completed SFT run, merge its adapter before the B3 branch:

```bash
studyhub-agent/.venv-train/bin/python \
  studyhub-agent/scripts/train/merge_sft_lora.py \
  --base models/P1/Qwen3.5-4B \
  --adapter /path/to/areal/sft/adapter \
  --output studyhub-agent/artifacts/areal/merged-sft-qwen35-4b
```

Actual training is deliberately double-gated. It requires a non-`check` mode
and the explicit environment variable below:

```bash
STUDYHUB_ALLOW_TRAINING=YES \
  bash studyhub-agent/scripts/train/run_controlled_sft.sh 4b gate 6209

STUDYHUB_ALLOW_TRAINING=YES \
  bash studyhub-agent/scripts/train/run_controlled_grpo.sh 4b direct gate 6209
```

GRPO modes have distinct budgets with `batch_size=8` and `n_samples=4`:

| Mode | Optimizer steps | Tasks | Expected trajectories | Purpose |
| --- | ---: | ---: | ---: | --- |
| `gate` | 1 | 8 | 32 | End-to-end runtime and GPU-guard check |
| `smoke` | 10 | 80 | 320 | Short reward-distribution check |
| `pilot` | 25 | 200 | 800 | The controlled 200-task pilot |
| `run` | Full epoch | 2,000 | 8,000 | Formal run after gates pass |

Counts assume complete four-sample groups. AReaL retries rejected groups, while
the reward diagnostics report incomplete groups explicitly.

Each launch writes rewards to a trial-specific directory under
`artifacts/areal/reward-v2/<scale>/<trial>/`. The log records task, rollout-group,
rollout, family, seed, trace errors, and every reward component without storing
the raw final answer. Training rewards stay at the trial root; evaluator rewards
use its `validation/` child directory so the two distributions cannot mix.
Summarize a completed training trial with:

```bash
studyhub-agent/.venv-train/bin/python \
  studyhub-agent/scripts/train/summarize_reward_groups.py \
  studyhub-agent/artifacts/areal/reward-v2/4b/<trial>
```

Reward v2 combines function-call correctness and final-answer quality at
`70% / 30%`. Empty answers, missing required citations, or no tool call cannot
receive positive reward. Invalid citations, nonexistent sources, unknown tools,
unsupported capabilities, and tool-budget overruns are hard-gated to `-1`.
Corpus reads are accepted only for source IDs returned by an earlier search in
the same rollout; unmatched fixture arguments return a deterministic error.

SFT reserves one otherwise idle GPU. GRPO reserves two otherwise idle GPUs.
The guard refuses to start on a busy GPU, samples memory every five seconds,
and stops only its own process group if the configured memory ceiling is
crossed or another GPU process appears. The one-step Gate and 10-step Smoke
observed AReaL/SGLang child-process handling without crossing the 68,000 MiB
ceiling; each new scale or materially changed recipe still starts with a Gate.
