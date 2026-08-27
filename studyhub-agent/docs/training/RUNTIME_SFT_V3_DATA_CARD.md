# Runtime-native SFT v3 Data Card

Status: `ACCEPTED_FOR_SFT_GATE`  
Accepted: 2026-08-27

## Purpose

This dataset bootstraps Qwen3.5-9B in the same tool-call policy space used by
the StudyHub Hermes runtime. It is independent from frozen StudyHub AgentBench
v2 and is intended for the SFT Gate, profile, and formal SFT stages.

## Final Dataset

| Item | Value |
| --- | ---: |
| Candidate trajectories | 105,690 |
| Selected trajectories | 48,500 |
| Train / validation / protocol holdout | 43,650 / 2,425 / 2,425 |
| Runtime-native multi-turn | 36,574 (75.41%) |
| Complete / action-only | 42,342 / 6,158 |
| Total / assistant-loss tokens | 61,725,581 / 9,062,215 |
| Maximum sequence length | 4,446 of 8,192 |
| Largest source share | 24.74% |
| Largest semantic-template cluster | 1.61% |

The source mixture is ToolACE 6,400; Hermes Function Calling 2,600; COIG
4,500; 2Wiki 12,000; QASPER 3,000; and 20,000 StudyHub replay trajectories
covering metadata retrieval, memory, ACL recovery, Web fallback, and isolated
state tools.

## Quality Labels

The labels describe provenance, not an inferred quality score:

- `expert_complete`: 6,695 complete demonstrations from open datasets.
- `expert_action_synthetic_observation`: 647 expert actions paired with clearly
  marked synthetic observations.
- `expert_action_only`: 6,158 tool/JSON actions without a final answer target.
- `oracle_derived_expert_complete`: 15,000 2Wiki/QASPER demonstrations built
  from hidden gold evidence.
- `deterministic_fixture_complete`: 20,000 StudyHub replay trajectories built
  from deterministic fixtures.

No row is described as `teacher_verified`; no per-row human or external-LLM
semantic review was performed.

## Isolation

- Exact split group overlap is zero.
- All 98 frozen AgentBench v2 prompts and 34 benchmark material IDs are excluded.
- Normalized Benchmark v2 prompt overlap is zero.
- The 12,000 selected 2Wiki rows come from 12,000 distinct support-document
  connected components. Across 24,652 support titles, cross-split overlap is zero.
- Tokenization uses the local official Qwen3.5-9B template. Loss is applied only
  to assistant tool actions and final answers; tool observations are masked out.

## Reproducibility

The machine-readable card at
`configs/program-v3/runtime-sft-v3-data-card.json` records source revisions,
licenses through the source registry, Benchmark locks, artifact hashes, tokenizer
revision, and the full audit result. Large JSONL/Hugging Face artifacts remain
Git-ignored; their exact hashes are committed instead.

## Limitations

2Wiki and QASPER traces are expert demonstrations created with oracle evidence;
they do not show that the model can autonomously discover evidence. ToolACE
action-only rows do not supervise final answers. StudyHub rows are deterministic
replays, not human-reviewed production interactions. Model capability claims must
therefore come from AgentBench v2 and official external evaluations, not SFT loss
or this data audit alone.
