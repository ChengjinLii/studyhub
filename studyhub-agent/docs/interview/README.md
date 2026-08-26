# StudyHub Agent 面试知识库

这里记录项目中可以由代码、配置或实验产物复核的 Agentic SFT/RL 经验。正常技术主题与故障案例分开维护，避免把理论知识、受控注入或经验帖内容写成真实项目结论。

## 阅读顺序

| 文档 | 核心问题 | 当前证据 |
| --- | --- | --- |
| [01-agent-architecture.md](01-agent-architecture.md) | Hermes、AReaL、SGLang 和 StudyHub 分别做什么 | A：真实 Gate/Smoke |
| [02-tool-calling.md](02-tool-calling.md) | Tool Call 如何生成、执行、返回并受约束 | A：真实轨迹与冻结环境 |
| [03-sft.md](03-sft.md) | SFT 学什么，怎样与 RL 衔接 | A：2B Pilot；4B 配方待主实验 |
| [04-grpo.md](04-grpo.md) | GRPO 的 group、advantage、KL 和有效信号 | A：4B Gate/Smoke |
| [05-reward-design.md](05-reward-design.md) | Reward 如何拆分、校准并防止 shortcut | A：Reward v2 与真实轨迹 |
| [06-agent-evaluation.md](06-agent-evaluation.md) | 为什么不能只看平均 Reward | A：Eval32 v2 协议；结果持续追加 |
| [07-rag.md](07-rag.md) | BM25、Dense、Hybrid、Reranker 与 Agent RL 的边界 | A：离线 RAG 实验；未接生产 |
| [08-reproducibility.md](08-reproducibility.md) | 如何证明一次训练可复现、可审计 | A：Gate/Smoke 证据包 |
| [09-engineering.md](09-engineering.md) | 双卡、FSDP、SGLang、LoRA 与 GPU 安全 | A：真实运行 |
| [incidents/](incidents/) | 自然发现或明确标注的受控故障闭环 | A/B，逐篇标注 |

## 统一回答格式

每篇按以下顺序组织：

1. 面试问题。
2. 30 秒回答。
3. 深入解释。
4. StudyHub 的实现与取舍。
5. 可能追问。
6. 代码与实验依据。

## 证据等级

- `A`：在真实训练或评测运行中复现，有原始日志、轨迹、指标或 checkpoint。
- `B`：在隔离环境中主动构造并完成修复回归的受控实验。
- `C`：代码或机制 smoke，不能外推为模型能力提升。
- `D`：论文、上游源码或理论理解，未在本项目实跑。

任何具体数字都应能回到 `artifacts/experiments/<trial>/`、数据 manifest 或固定报告。经验帖和压缩包截图只用于补齐问题覆盖，不作为项目事实。
