# ADR-001：产品运行时采用 LangGraph 低层 StateGraph

- 状态：Accepted
- 日期：2026-07-26
- 范围：StudyHub Agentic Learning & DeepResearch Platform 第一阶段

## 决定

产品运行时将在 PR 6 引入 LangGraph v1 的低层 `StateGraph`，但它只负责节点调度、路由和 checkpoint 接口；业务领域状态始终由 `backend/app/agentic_platform/domain/` 中的 Pydantic v2 模型定义。

实现时将增加与 LangGraph 分离的 `AgentKernel`、`AgentPolicy`、`AgentEnvironment`、`StateDelta` 和持久化 Adapter。测试使用 InMemory/SQLite，研究环境使用 Redis checkpoint，权威 Run/Step 摘要和版本化 Artifact 使用现有 MySQL/SQLite ORM 基础设施。

## 后果

- 不采用预制 ReAct Agent，不使用 `MessageState` 作为业务模型。
- 依赖在 PR 6 才加入 `backend/pyproject.toml`；PR 0 不改变后端运行时。
- 新 Domain 模型统一使用 Pydantic v2 和 `ConfigDict(extra="forbid")`。
- Runtime 的每一步只能产出 `StateDelta`，不能原地突变业务 State 或携带 DB Session。
- LangGraph `1.2.9` 与 `langgraph-checkpoint-sqlite` `3.1.0` 在 PR 6 锁定；Redis 继续复用现有 `redis` 客户端实现 Adapter，不把第三方训练运行时装入 FastAPI 进程。
- `langgraph` 的传递依赖中虽包含 `langgraph-prebuilt`，StudyHub 不导入或使用其中的预制 Agent；运行时仅使用低层 `StateGraph`、`Command`、`interrupt` 和 Checkpointer 接口。

## 被否决的方案

- 在 `AiService` 内继续扩展同步 `for`/`while` 工具循环；它无法提供可靠的恢复、重放和训练轨迹契约。
- 用 LangGraph 消息列表替代业务 State；这会丢失 Plan、Artifact、权限和环境快照的类型化边界。
