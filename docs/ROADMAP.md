# StudyHub 开发路线记录

本文用于维护项目方向和后续工作，README 负责介绍功能与使用方式。

---

## 平台方向

| 方向 | 工作内容 |
| --- | --- |
| 资料审核 | 完善投稿审核、版权风险识别与异常内容处理流程 |
| 语义搜索 | 为资料、经验和求购提供更自然的检索体验 |
| MCP 接口 | 维护面向智能体的能力入口、OAuth 权限、配额与返回边界 |
| 检索与推荐 | 优化资料推荐、贡献榜与校园集市排序 |

MCP 接口约定见 [MCP.md](../MCP.md)。

---

## Agent

Agent 沿运行契约、架构评测、训练流水线和强化学习四个阶段推进。当前工作记录见 [架构钩子开发记录](../studyhub-agent/docs/specs/2026-10-05-architecture-hooks-progress.md)，详细路线见 [Agent 开发路线](../studyhub-agent/docs/ROADMAP.md)。

架构比较和 AgentBench v3 的数据、判分与统计门禁完成后，再开展 SFT / RL 实验。评测结论以可复现的运行记录为依据。

---

## 内容审核

Review-Jev 保持纯文字 Qwen3Guard-Gen-0.6B、图片与图文 OneJev-4B 的分流方式。围绕校园投稿样本完善标注、规则评测、概率校准与审核流程设计，参考 [验证记录](../review-jev/VALIDATION.md)。
