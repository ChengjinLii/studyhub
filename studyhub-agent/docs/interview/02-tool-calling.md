# 模型生成 Tool Call 后发生了什么？

## 30 秒回答

模型只看到当前任务公开的 tool schema。Hermes 解析 Qwen3 格式的调用，通过临时注册的异步 handler 交给冻结环境；环境校验工具名、参数、Search→Read 顺序和调用预算，再返回确定性 JSON observation。完整调用轨迹被记录，隐藏的正确调用或 gold evidence 只交给 verifier。

## 深入解释

Function Calling 任务把 ToolACE、Hermes FC 的专家轨迹拆成三个部分：公开 user request、公开 schema、隐藏 expected calls。SFT 模仿专家调用；RL 只看到任务与 schema，必须自己产生调用。

检索任务使用两个能力：

```text
knowledge_search(query, limit)
  -> source_id + title + snippet

knowledge_read(source_id)
  -> 仅允许读取本轮 search 已发现的 source_id
```

环境对未知工具、超预算、错误 source、未发现先读、缺参和 fixture 不匹配返回固定错误。`source_not_found`、未知工具、超预算等高风险错误进入 Reward hard gate。

## StudyHub 的实现与取舍

- `tool_call_parser=qwen3_coder`，`reasoning_parser=qwen3`，避免 parser 与模型模板不一致。
- 每个任务使用独立 toolset 名称；结束后注销，防止跨任务工具污染。
- ToolACE 多轮轨迹保留连续的 assistant/tool rounds，不能把中间 tool call 当 final answer。
- Runtime 统一限制为 6 个 model turns 和 6 个 tool calls；数据构建阶段会拒绝不可完成任务。
- 工具结果来自 fixture 或冻结 corpus，因此同一调用可重放，不依赖外部网络状态。

## 可能追问

- 为什么只靠 prompt 要求“先搜后读”不够？RL 会利用环境漏洞；顺序必须由环境状态机强制执行。
- 参数合法但与 fixture 不匹配怎么办？返回 `ok=false` 和稳定错误，不把错误调用伪装成成功 observation。
- 如何防无限循环？任务预算与 Hermes guardrail 双层限制；重复失败、同工具连续失败、无进展都会停止。

## 代码与实验依据

- `training/rl/frozen_environment.py`
- `training/rl/hermes_workflow.py`
- `training/rl/budget_contract.py`
- `datasets/processed/open_agent_rl_v2/budget-audit.json`
- `docs/interview/incidents/2026-08-26-rl-task-budget-contract.md`
