# ADR-002：采用 Search-R1 行为协议，不复制其产品或训练源码

- 状态：Accepted
- 日期：2026-07-26
- 范围：DeepResearchSearchAgent 与后续训练 Adapter

## 决定

StudyHub 采用 Search-R1 的“推理—检索—观察—再决策”行为协议作为 DeepResearch 的历史基线。产品代码只实现本项目的类型化 Tool、Evidence Ledger、ResearchPacket 和 Adapter；外部仓库仅在 `.local-research/vendor/` 中以锁定 SHA 供研究，不作为 Git submodule，也不提交到业务仓库。

## 后果

- 内部资料/PDF、Web、Scholar 和 Python 能力都经由 StudyHub Skill/Tool 契约提供。
- Tool Observation 的训练可见性由 Token Role 契约控制；不能把 Observation 当作 trainable assistant token。
- Search-R1 的旧 Python、Torch、vLLM、veRL pin、Wikipedia 数据路径和字符串标签协议不进入产品后端。
- 后续导出保持 Search-R1-compatible 数据 Adapter，但训练运行时使用届时锁定的 veRL Adapter，而非 Search-R1 旧训练栈。
