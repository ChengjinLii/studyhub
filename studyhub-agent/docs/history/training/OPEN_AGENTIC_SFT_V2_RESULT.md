# Open-Agentic SFT v2 Result

## Scope

This experiment changed the SFT data while keeping the 9B model and training recipe fixed. It used only audited open-source sources and did not use StudyHub deterministic fixtures, AgentBench tasks, Sealed data, BFCL test data, or tau2 tasks for training.

The checkpoint was evaluated in two layers:

1. frozen StudyHub AgentBench v2 Development;
2. test-only subsets from the official BFCL V4 and tau2 implementations.

No RL or Sealed evaluation was run.

## Training

| Item | Value |
|---|---:|
| Model | Qwen3.5-9B `c202236235762e1c871ad0ccb60c8ee5ba337b9a` |
| Framework | AReaL 2.0.0, FSDP2, BF16 |
| LoRA | r16 / alpha16; `o_proj`, `gate_proj`, `up_proj`, `down_proj` |
| Optimizer updates | 2,100 |
| Sequences | 16,800 |
| Total train tokens | 19,188,650 |
| Assistant-loss tokens | 3,107,404 |
| Global batch | 8 |
| Seed | 20260827 |
| Final-step loss | 0.087568 |
| Final-step gradient norm | 0.24398 |
| Final-step LR | 1.4093e-5 |
| Productive run peak GPU memory | 62,601 MiB |

The formal run resumed from update 1,260 and completed update 2,100. The final LR continuity audit covered all 2,100 updates and passed. The final adapter SHA-256 is:

```text
909d0e2a415da04ef8c3035bb04bccab84bb044fc5c2ca3bbe58cd489e4bfede
```

## Training Data

The train split contains 16,800 rows. Source shares below are measured by assistant-loss tokens, not row count.

| Source family | Share |
|---|---:|
| Hermes | 37.61% |
| ToolBench | 25.00% |
| Agent-FLAN | 11.98% |
| 2Wiki/QASPER replay | 14.99% |
| COIG | 6.39% |
| ToolACE complete | 4.03% |

Behavior coverage:

| Behavior | Share |
|---|---:|
| Observation-conditioned | 84.86% |
| Multi-turn | 62.92% |
| Multi-tool | 60.99% |
| Recovery/negative | 22.97% |
| Oracle replay | 14.99% |
| Planning-only | 8.00% |

Data gates passed with zero action-only rows, zero StudyHub custom rows, zero public Benchmark overlap, zero split group overlap, and zero audited exact/near/semantic cross-group duplicates.

## StudyHub AgentBench v2

Frozen 51-task Development, temperature 0, identical Hermes/runtime/evaluator, and zero infrastructure exclusions:

| Model | Strict | Mean diagnostic | Mean tool calls |
|---|---:|---:|---:|
| Base | 6/51 (11.76%) | 0.283758 | 2.882 |
| Mixed-v3.0 SFT | 4/51 (7.84%) | 0.249346 | 2.275 |
| Open-Agentic v2 SFT | 5/51 (9.80%) | 0.294346 | 2.824 |

Open-Agentic v2 versus Base: 2 paired wins, 3 losses, and 46 ties. Open-Agentic v2 versus Mixed-v3.0: 3 wins, 2 losses, and 46 ties.

The checkpoint recovered part of the Mixed-v3.0 regression and restored tool-call volume, but it did not reach Base strict success. The higher diagnostic score is not sufficient for promotion because strict success remained lower and the Development set has only 51 tasks.

## BFCL V4

The pinned official BFCL evaluator was used at commit `f7cf7359b7ac615a0b294831c5ba2bc95ee4a000`. The test-only subset contains 10 deterministic official IDs in each of seven categories. The same 70 IDs were used for Base and SFT.

| Category | Base | Open-Agentic v2 |
|---|---:|---:|
| Simple Python | 9/10 | 8/10 |
| Parallel | 10/10 | 10/10 |
| Multiple | 8/10 | 9/10 |
| Irrelevance | 10/10 | 7/10 |
| Multi-turn base | 4/10 | 6/10 |
| Multi-turn missing function | 4/10 | 2/10 |
| Multi-turn missing parameter | 5/10 | 5/10 |
| **Selected-subset micro** | **50/70** | **47/70** |

Paired result: 5 SFT wins, 8 losses, and 57 ties. Exact two-sided McNemar p = 0.5811.

The SFT checkpoint improved multi-function and basic multi-turn execution, but reduced irrelevance detection and missing-function recovery. This is not a complete BFCL leaderboard run. Qwen3.5 was registered through the closest official Qwen function-calling handler because the pinned BFCL revision has no native Qwen3.5 registry entry.

## tau2

The pinned official tau2 environment and DB/COMMUNICATE reward were used at commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`. The subset contains five tasks per domain, one trial each, with an enforced communication protocol.

| Domain | Base | Open-Agentic v2 |
|---|---:|---:|
| Airline | 0/5 | 3/5 |
| Retail | 0/5 | 0/5 |
| Telecom | 0/5 | 0/5 |
| **Total** | **0/15** | **3/15** |

The SFT run had 6 agent errors, 2 user-simulator errors, and 2 max-step terminations. Base had 15 agent errors. A frequent SFT failure was returning user-facing text and a tool call in the same turn, which the official communication protocol rejects.

The result is directional only. A local Qwen3.5-9B Base model was used as the fixed user simulator on the second GPU, so this subset is not directly comparable with the official leaderboard configuration.

## Decision

```text
NO_BROAD_AGENT_IMPROVEMENT_DEMONSTRATED
```

Open-Agentic v2 is better than Mixed-v3.0 on the internal strict metric and shows targeted gains in BFCL multi-tool/multi-turn and the tau2 airline slice. It remains below Base on AgentBench strict success and BFCL selected-subset micro accuracy. The current evidence supports a data-direction diagnosis, not checkpoint promotion.

The next experiment should be a small, controlled ablation focused on protocol-safe final/tool-call separation, irrelevance/tool abstention, and missing-function recovery. It must not tune against the BFCL or tau2 test instances used here.

## Evidence

- `docs/training/evidence/open-agentic-sft-v2-data-audit.json`
- `docs/training/evidence/open-agentic-sft-v2-development-comparison-20260830.json`
- `docs/training/evidence/open-agentic-sft-v2-external-benchmarks-20260830.json`
- local completion marker: `artifacts/areal/checkpoints/chengjin/studyhub-open-agentic-sft-v2-9b/open-agentic-sft-v2-formal-r16-seed-20260827/OPEN_AGENTIC_SFT_V2_COMPLETE.json`

Raw model weights, trajectories, benchmark outputs, and GPU logs remain Git-ignored.
