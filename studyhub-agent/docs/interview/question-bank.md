# StudyHub Agent 高频面试问题

本表是导航，不代替主题文档。`A/B/C/D` 含义见 [README.md](README.md)。尚未完成的实验只写问题和证据缺口，不预填结论。

## 项目与架构

| 问题 | 当前等级 | 回答入口 |
| --- | --- | --- |
| 为什么这个任务需要 Agent，而不是一次普通 RAG 调用？ | A | [01-agent-architecture.md](01-agent-architecture.md) |
| Hermes、StudyHub workflow、AReaL、SGLang 分别做什么？ | A | [01-agent-architecture.md](01-agent-architecture.md) |
| 为什么保留 Hermes loop 而不是重写？ | A/C | [01-agent-architecture.md](01-agent-architecture.md) |
| Agentic RL 与普通 reasoning RL 有什么区别？ | A/D | [01-agent-architecture.md](01-agent-architecture.md)、[04-grpo.md](04-grpo.md) |
| 训练环境为什么不会影响 StudyHub 网站和数据库？ | A | [01-agent-architecture.md](01-agent-architecture.md) |

## 数据与 SFT

| 问题 | 当前等级 | 回答入口 |
| --- | --- | --- |
| 五个开放数据集分别训练什么能力？ | A | [03-sft.md](03-sft.md) |
| 为什么 2Wiki/QASPER SFT 不能宣称学会了 Search Policy？ | A | [03-sft.md](03-sft.md) |
| assistant-only loss mask 如何实现？ | A | `scripts/data/tokenize_areal_sft.py` |
| 如何做 group split、去重和 SFT/RL 防泄漏？ | A | `scripts/data/verify_open_sft_dataset.py`、`scripts/data/audit_open_rl_tasks.py` |
| 什么时候 SFT 数据算够？ | C，待 4B learning curve | [03-sft.md](03-sft.md) |
| 为什么 Base/SFT/RL/SFT→RL 四组缺一不可？ | A/C，结果待补 | [03-sft.md](03-sft.md) |
| 为什么使用 LoRA，目标层怎么选？ | A/C | [03-sft.md](03-sft.md)、[09-engineering.md](09-engineering.md) |

## 工具与环境

| 问题 | 当前等级 | 回答入口 |
| --- | --- | --- |
| Tool Call 从模型输出到真实执行经过哪些步骤？ | A | [02-tool-calling.md](02-tool-calling.md) |
| 为什么必须由环境强制 Search→Read？ | A | [02-tool-calling.md](02-tool-calling.md) |
| 如何防止工具死循环、重复失败和超预算？ | A | [02-tool-calling.md](02-tool-calling.md) |
| Gold answer/evidence/tool sequence 为什么不能给 Agent 看？ | A | [05-reward-design.md](05-reward-design.md) |
| Frozen Environment 与线上真实工具有什么区别？ | A | [02-tool-calling.md](02-tool-calling.md) |
| Parser、chat template、tool serialization 不一致会怎样？ | A/C | [02-tool-calling.md](02-tool-calling.md) |

## GRPO 与 Reward

| 问题 | 当前等级 | 回答入口 |
| --- | --- | --- |
| GRPO 与 PPO 的主要区别是什么？ | A/D | [04-grpo.md](04-grpo.md) |
| Group advantage 怎么算？为什么需要多条 rollout？ | A | [04-grpo.md](04-grpo.md) |
| zero-variance group 为什么没有有效学习信号？ | A | [04-grpo.md](04-grpo.md) |
| KL、clip、ratio rejection 和 entropy 分别监控什么？ | A/C | [04-grpo.md](04-grpo.md) |
| Reward v2 为什么拆成多个 component？ | A | [05-reward-design.md](05-reward-design.md) |
| 如何防止“调对工具但不回答”的 Reward shortcut？ | A | [05-reward-design.md](05-reward-design.md) |
| Hard gate 与软 penalty 如何分工？ | A | [05-reward-design.md](05-reward-design.md) |
| 如何诊断 reward hacking、熵坍塌和长度膨胀？ | A/B 待后续 campaign | [05-reward-design.md](05-reward-design.md)、`incidents/` |
| 为什么第一轮 RL 不把 COIG 作为主要 Agent task？ | C | [03-sft.md](03-sft.md) |

## 评测与复现

| 问题 | 当前等级 | 回答入口 |
| --- | --- | --- |
| 为什么平均 Reward 不能代表 Agent 变好？ | A | [06-agent-evaluation.md](06-agent-evaluation.md) |
| strict success、pass@4、consistent@4 各表示什么？ | A | [06-agent-evaluation.md](06-agent-evaluation.md) |
| 为什么评测必须要求每题恰好 4 条？ | A | [06-agent-evaluation.md](06-agent-evaluation.md) |
| 固定 seed 为什么仍不一定确定性？ | A/C | [08-reproducibility.md](08-reproducibility.md) |
| 如何证明训练更新了 LoRA、评测没有更新？ | A | [08-reproducibility.md](08-reproducibility.md) |
| 如何比较 B0/B1/B2/B3 并给出置信区间？ | C，结果待补 | [06-agent-evaluation.md](06-agent-evaluation.md) |
| 如何证明实验不是数据泄漏或 verifier shortcut？ | A | [05-reward-design.md](05-reward-design.md)、[08-reproducibility.md](08-reproducibility.md) |

## RAG 与工程

| 问题 | 当前等级 | 回答入口 |
| --- | --- | --- |
| StudyHub 是否真实实现过 BM25、Dense、Hybrid 和 reranker？ | A | [07-rag.md](07-rag.md) |
| 离线 Retriever 实验与当前 RL frozen search 有什么区别？ | A | [07-rag.md](07-rag.md) |
| 双卡上 actor/reference/rollout 如何放置？ | A | [09-engineering.md](09-engineering.md) |
| 参数、optimizer、activation、KV cache 如何影响显存？ | A/C | [09-engineering.md](09-engineering.md) |
| 多人共享 GPU 时如何避免误杀其他任务？ | A | [09-engineering.md](09-engineering.md) |
| 为什么暂时不把 9B 结果外推出来？ | A | [unsupported-claims.md](unsupported-claims.md) |

## 真实事故

| 问题 | 当前等级 | 回答入口 |
| --- | --- | --- |
| 讲一个真实 Agent RL runtime Bug。 | A | [incidents/2026-08-26-duplicate-training-system-prompt.md](incidents/2026-08-26-duplicate-training-system-prompt.md) |
| 讲一个数据与 runtime 契约不一致的问题。 | A | [incidents/2026-08-26-rl-task-budget-contract.md](incidents/2026-08-26-rl-task-budget-contract.md) |
| 如果自然训练没出现 entropy collapse/reward hacking 怎么办？ | B | 从健康 checkpoint 做短时隔离注入，标题和结论明确写 `CONTROLLED`，修复后回归同一 suite |
