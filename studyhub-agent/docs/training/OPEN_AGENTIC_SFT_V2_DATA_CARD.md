# Open-Agentic SFT v2 Data Card

## Purpose

Hermes-centered open-source supervision for the controlled Qwen3.5-9B SFT comparison.
StudyHub deterministic fixtures, teacher reverse replay, and evaluation tasks are excluded.

## Scale

| Item | Value |
|---|---:|
| Train rows | 16,800 |
| Validation rows | 933 |
| Protocol holdout rows | 933 |
| Train total tokens | 19,188,650 |
| Train assistant-loss tokens | 3,107,404 |
| Assistant-token target delta | -30,615 |
| Total-token target delta | -2,129,760 |

## Source Mix

| Family | Assistant-loss token share |
|---|---:|
| agent_flan | 11.98% |
| coig | 6.39% |
| hermes | 37.61% |
| rag_replay | 14.99% |
| toolace | 4.03% |
| toolbench | 25.00% |

## Behavior Mix

| Behavior | Assistant-loss token share |
|---|---:|
| direct_abstention | 15.14% |
| multi_tool | 60.99% |
| multi_turn | 62.92% |
| observation_conditioned | 84.86% |
| oracle_replay | 14.99% |
| planning_only | 8.00% |
| recovery_negative | 22.97% |
| stateful_function | 8.32% |

## Quality Tiers

| Tier | Rows |
|---|---:|
| A | 10,099 |
| B | 3,233 |
| C | 3,468 |

## Tool Paths

| Abstract path | Assistant-loss token share |
|---|---:|
| direct -> final | 7.14% |
| failure -> retry -> final | 22.22% |
| planning/direct -> final | 8.00% |
| search -> read -> final | 14.27% |
| single-tool -> final | 12.81% |
| single-tool-repeat -> final | 10.57% |
| toolA -> toolB -> final | 25.00% |

## Group Concentration

- Unique train conversation groups: 12,697
- Rows/group p50, p90, max: 1, 1, 127
- Largest group assistant-token share: 0.71%
- Largest exact tool-path assistant-token share: 15.14%

## Source Detail

The table below covers all three splits.

| Source | Family | Rows | Assistant tokens | Groups | Group p90/max | Calls p50/p90 | Observation origin | License | Revision |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| agent_flan_toolbench_negative | agent_flan | 299 | 25,251 | 299 | 1/1 | 0/0 | open_dataset | Apache-2.0 | 8b25999e795a58b264fcb51e8746edb2faee9161 |
| agent_flan_toolbench_react | agent_flan | 1,413 | 386,306 | 1,413 | 1/1 | 3/4 | open_dataset | Apache-2.0 | 8b25999e795a58b264fcb51e8746edb2faee9161 |
| coig_exam | coig | 1,256 | 209,175 | 1,256 | 1/1 | 0/0 | open_dataset | Apache-2.0 (dataset-level; mixed-source notice retained) | 9f25758ec94f82762fb9c09a5c60e908cfb83632 |
| hermes_func_calling | hermes | 927 | 458,649 | 927 | 1/1 | 2/3 | open_dataset | Apache-2.0 | dae3e1d26f495a56f2570944488be3cf3916c2f9 |
| hermes_glaive_function_calling_5k | hermes | 3,764 | 539,246 | 1,148 | 5/127 | 2/2 | open_dataset | Apache-2.0 | dae3e1d26f495a56f2570944488be3cf3916c2f9 |
| hermes_json_mode_agentic | hermes | 1,123 | 186,762 | 1,123 | 1/1 | 0/0 | open_dataset | Apache-2.0 | dae3e1d26f495a56f2570944488be3cf3916c2f9 |
| hermes_json_mode_singleturn | hermes | 1,207 | 93,125 | 1,207 | 1/1 | 0/0 | open_dataset | Apache-2.0 | dae3e1d26f495a56f2570944488be3cf3916c2f9 |
| studyhub_2wiki_replay | rag_replay | 441 | 133,111 | 441 | 1/1 | 4/8 | frozen_open_corpus_replay | Apache-2.0 | 612bc5039a457880d9e7d84c3b0a4cf154b70e4f |
| studyhub_qasper_replay | rag_replay | 2,670 | 422,915 | 1,057 | 5/11 | 2/4 | frozen_open_corpus_replay | CC-BY-4.0 | v0.3 |
| toolace | toolace | 462 | 145,882 | 462 | 1/1 | 2/2 | open_dataset | Apache-2.0 | 6bda777c88d21e5a204703c1ee45597a8fa4f734 |
| toolbench_toolllama_g123_dfs_train | toolbench | 5,104 | 895,553 | 5,076 | 1/2 | 2/4 | open_dataset | Apache-2.0 | google-drive-data.zip:df035ef91551d5cdc9e66d782dc12c821c81e830da2e7d05f633c7b26ae06016 |

## Language

| Language | Rows |
|---|---:|
| en | 17,405 |
| zh | 1,261 |

## Semantic Deduplication

- Embedding contract: BAAI/bge-m3 CLS normalized cosine
- Neighbor count: 192
- Hard cross-group threshold: 0.995
- Hard cross-group pairs in the selected dataset: 0

## Isolation

- Action-only rows: 0
- StudyHub custom fixture rows: 0
- Public AgentBench prompt overlap: 0
- Sealed content read: false
- Train/validation/protocol source-group overlap: 0
- APIGen-MT: disabled
- xLAM 60k: skipped because access was gated

## Loss

Loss is applied only to assistant tool calls, assistant continuations, and final answers. System, user, and tool-observation tokens are masked.

## Boundary

2Wiki and QASPER remain oracle/replay auxiliaries and are capped. Passing this data audit does not establish downstream Agent capability.
