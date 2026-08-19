# StudyHub Web Research Pilot

This package contains the isolated evaluation, SFT, and RL path for Web-enabled
DeepResearch. Runtime Web access is implemented separately in
`../backend/app/agentic_platform/deepresearch/web_adapter.py` and remains controlled
by capability flags.

## Search-R1 mapping

The RL implementation is pinned to
[`PeterGriffinJin/Search-R1`](https://github.com/PeterGriffinJin/Search-R1) commit
`598e61bd1d36895726d28a8d06b3a15bed19f5d3`.

| Search-R1 contract | StudyHub implementation |
| --- | --- |
| Iterative generation and environment observations | `FrozenWebResearchEnvironment` updates `DeepResearchState` after each action |
| Same-question grouped rollouts | Five free-generation trajectories per scenario |
| GRPO outcome advantage | Final trajectory rewards are normalized within each scenario group |
| State masking | Prompt and observation tokens are excluded; only generated decision tokens receive loss |
| PPO clipping | Token-level ratio clipping with `clip_ratio=0.2` |
| Reference regularization | Frozen SFT adapter with low-variance KL, coefficient `0.001` |
| Search/answer output boundaries | The first complete `ResearchDecision` JSON object is the executable action boundary |

The model is never given candidate actions. It freely emits one typed
`ResearchDecision` per turn and can search internally, search the frozen Web,
read a source, finalize, or abort.

## Frozen data

`build_web_rl_pilot_scenarios()` creates 75 deterministic multi-turn scenarios:

- 45 train scenarios, 9 per family.
- 15 validation scenarios, 3 per family.
- 15 held-out test scenarios, 3 per family.
- Families: internal evidence, empty internal fallback, current Web research,
  cross-source research, and sensitive externalization refusal.

The mixed SFT export contains 186 train, 62 validation, and 62 test records.
Every source, observation, and evidence excerpt is a local fixture. The training
path rejects configured API and database endpoints.

## Reproduction

Run these commands from the standalone project root:

```bash
cd /data/chengjin/studyhub/studyhub-agent
```

Export the mixed single-turn and trajectory SFT data:

```bash
PYTHONPATH=.:../backend ../backend/.venv/bin/python \
  -m ml.agentic_platform.web_research.export_sft \
  --dataset-dir training_artifacts/studyhub_agent_sft/web_router_v5_expanded_trajectories/llamafactory \
  --include-multi-turn
```

Run the expanded SFT continuation:

```bash
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /data/chengjin/LLaMA-Factory/.venv/bin/llamafactory-cli train \
  ml/agentic_platform/web_research/configs/qwen35_2b_web_router_expanded_trajectories_seed_7703.yaml
```

Run Search-R1-style GRPO:

```bash
STUDYHUB_SEARCH_R1_SFT_ADAPTER=training_artifacts/studyhub_agent_sft/web_router_v5_expanded_trajectories/qwen35_2b_lora_seed_7703 \
STUDYHUB_SEARCH_R1_OUTPUT_DIR=training_artifacts/studyhub_agent_rl/web_search_r1_pilot_v5/seed_7703 \
STUDYHUB_SEARCH_R1_TEMPERATURE=1.2 \
scripts/research/train-search-r1-web-pilot.sh
```

Run evaluation without creating an optimizer:

```bash
STUDYHUB_SEARCH_R1_SFT_ADAPTER=training_artifacts/studyhub_agent_rl/web_search_r1_pilot_v5/seed_7703/adapter \
STUDYHUB_SEARCH_R1_OUTPUT_DIR=evaluation_artifacts/studyhub_agent/web_search_r1_pilot_v5/held_out_test_seed_7703 \
STUDYHUB_SEARCH_R1_EVAL_ONLY_SPLIT=test \
scripts/research/train-search-r1-web-pilot.sh
```

## Seed 7703 result

| Check | Result |
| --- | --- |
| Frozen single-turn Router validation | 20/20, all 11 Gate checks passed |
| Multi-turn validation before GRPO | 15/15 |
| Sampled training trajectories | 17/25 completed |
| Non-zero group-advantage trajectories | 20/25 |
| PPO optimizer update | Executed, gradient norm `1.1520` |
| Multi-turn validation after GRPO | 15/15 |
| New held-out multi-turn test | 15/15 |
| Peak GRPO CUDA allocation | 18,938 MiB |

Generated datasets, adapters, trajectories, and evaluation artifacts live under
`training_artifacts/` and `evaluation_artifacts/`; both directories are ignored
by Git. This Pilot evaluates routing and tool-use trajectories, not factual answer
quality over live Web documents.
