# Open-Only SFT v1 Data Card

## Purpose

This dataset supports one controlled 9B SFT experiment: determine whether removing StudyHub deterministic and constructed trajectories changes the negative direction observed after Mixed-v3.0 SFT.

Only the training data changes. The model revision, seed, AReaL/FSDP2 runtime, BF16 precision, LoRA recipe, optimizer, scheduler, global batch size, assistant-loss token budget, and AgentBench v2 Development protocol remain fixed.

## Lineage

The candidate pool is the complete open-source subset of the already selected and tokenized runtime-SFT-v3.0 data. It does not introduce open-source examples that were absent from the Mixed control.

Allowed sources:

| Source | Candidate complete rows | Train rows | Train assistant-loss tokens | Train share |
|---|---:|---:|---:|---:|
| ToolACE | 647 | 400 | 160,000 | 5.10% |
| Hermes Function Calling | 2,195 | 1,600 | 350,000 | 11.15% |
| COIG Exam | 4,500 | 4,050 | 303,716 | 9.68% |
| 2Wiki replay | 12,000 | 8,050 | 1,885,550 | 60.09% |
| QASPER replay | 3,000 | 2,700 | 438,753 | 13.98% |

The COIG and QASPER complete pools cannot reach their requested 15-20% assistant-token ranges while also matching 16,800 sequences and 3.138M assistant-loss tokens. No action-only rows or duplicated samples were used to fill the shortfall. The unavoidable residual is assigned to 2Wiki and is recorded as a limitation.

## Controlled Budget

| Item | Mixed-v3.0 | Open-Only v1 |
|---|---:|---:|
| Train sequences | 16,800 | 16,800 |
| Optimizer updates | 2,100 | 2,100 |
| Assistant-loss tokens | 3,138,019 | 3,138,019 |
| Total train tokens | 21,318,410 | 22,333,694 |

Assistant-loss tokens match exactly. Total context tokens are 1,015,284 higher (+4.7625%) because complete open RAG trajectories contain longer masked user/tool observations. This affects throughput and GPU-hours, but not the number of tokens contributing directly to cross-entropy loss; it remains a documented residual control difference.

## Splits

| Split | Rows |
|---|---:|
| Train | 16,800 |
| Validation | 1,121 |
| Protocol holdout | 1,102 |
| Total selected | 19,023 |

All complete open-source validation and protocol-holdout rows from the existing v3.0 split are retained. Source groups do not cross split boundaries.

## Quality Gates

The build completed with:

- StudyHub custom rows: 0
- Action-only rows: 0
- Runtime contract failures: 0
- Exact duplicates: 0
- Near duplicates: 0
- Public Benchmark prompt overlap: 0
- Train/validation/holdout source-group overlap: 0
- Sealed task content read: false
- Train assistant-loss token delta: 0

Semantic/template diversity and tool-path diversity are reported separately in the generated `source-audit.json`; neither is substituted for the other.

## Limitations

2Wiki and QASPER remain oracle-derived replay trajectories. They provide RAG, evidence, and citation cold-start supervision, but they do not demonstrate autonomous teacher search policy. COIG is a direct-answer auxiliary lane rather than an Agent trajectory source. The 51-task Development comparison is a directional gate and cannot establish small general capability gains.
