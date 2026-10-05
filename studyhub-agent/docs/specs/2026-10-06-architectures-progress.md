# Agent v3 五种架构实现记录

日期：2026-10-06。对应 [执行计划](../plans/2026-09-26-architectures-benchmark-plan.md) 的 Task 4–6，复用已完成的统一执行器、运行契约和结构化证据。

---

## 交付概览

| 架构 | 实现 | 轨迹字段 |
| --- | --- | --- |
| `react` | 原有工具调用循环，保持固定基础轨迹回归 | 标准回合与工具观察 |
| `react_verify` | 引用来源核查与有界纠正 | `citation_checks`、`citation_verified`、`verify_rejections` |
| `plan_execute` | 首轮计划、执行反馈与发送视图中的计划提醒 | `plan`、`plan_turn`、`plan_truncated`、`plan_skipped` |
| `react_context` | 真实 token 阈值触发的确定性工具结果摘要 | `compactions`，含回合、消息索引及压缩前后 token 数 |
| `cascade` | 解析错误、引用失败或预算阈值触发的单向升级 | `escalated_at`、`escalation_reason`、`escalation_pending` |

五种架构已完成代码与离线验收，均由 `EpisodeRunner` 执行。本次不构成真实模型效果比较，也没有产出 AgentBench v3 的正式结果。

---

## 规划后执行

`PlanExecuteArchitecture(max_plan_chars=400)` 在初始化时注入注册的规划要求。首个最终文本作为计划，而非任务答案；执行器保存完整助手消息，trace 与提醒只保留计划前 400 字，再通过 `Continue` 要求模型执行。

提醒只添加在本回合发送视图的末尾，不覆盖 `Episode.messages`。后续最终文本按普通回答处理，不重新捕获为计划。

首轮工具调用或解析错误时，在后续钩子中标记跳过计划，继续原有执行逻辑。空计划不产生空提醒，但仍要求继续执行。规划消耗一轮任务预算；若最后一轮才生成计划，终止结果是 `max_turns`，不会另开执行循环。

提示来自 `studyhub.agent.plan_request@1.0` 与 `studyhub.agent.plan_reminder@1.0`；截断参数与提示正文计入契约哈希。

---

## 上下文压缩

`ReactContextArchitecture(context_threshold=0.5, keep_recent_tools=2, max_text_chars=120)` 使用 Runner 注入的 `RunContext.count_tokens(messages)` 统计完整渲染视图，包含工具定义、聊天模板与 thinking 设置，不用字符数替代真实 tokenizer。

超过上下文预算的指定比例后，仅压缩较早的、具有调用 ID 的工具结果。最近两条工具结果和所有运行时反馈保持完整；资料 ID、页码、标题、引用、数值和结构沿用模型已经见过的 payload，正文、片段和记忆长值截断。`Observation.details` 不进入摘要。

摘要标记为 `{"compacted":true,"result":...}`，发送视图另附注册的压缩说明。计数包含这条说明；如果实际 token 数没有下降，就保留原视图。执行器随后仍按本步发送视图检查硬上下文预算，压缩不是预算豁免。

原始消息、回合和观察完整保留。再次处理原始历史得到相同摘要，已压缩结果不会再套一层摘要。非 JSON 和过深 JSON 有回退处理，不因摘要解析而中断任务。

提示来自 `studyhub.agent.compaction_note@1.0`；阈值、近期保留量、摘要长度与提示正文均计入契约哈希。

---

## 小到大模型级联

`CascadeArchitecture(escalate_ratio=0.7, max_rejections=2)` 要求命名策略 `small` 与 `large`，并在环境重置前检查模型、tokenizer revision 和对应计数器。不存在大模型客户端时直接拒绝配置，不运行到一半才发现缺失。

| 触发条件 | 原因字段 |
| --- | --- |
| 上一回合解析失败 | `parse_error` |
| 工具调用量达到预算比例 | `tool_calls` |
| 回合数达到预算比例 | `turns` |
| 最终回答引用核查失败，且仍允许纠正 | `citation` |

多个条件同时成立时，优先处理待引用纠正、解析错误、工具调用量和回合数。升级只执行一次，此后一直选择 `large`，完整传递历史；每回合记录实际策略与模型。

引用纠正次数在两个模型之间共享。`max_rejections=0` 表示关闭引用纠正，此时不会仅因已接受的未核查回答而追加大模型回合。最终允许回合被拒绝时只记录 `escalation_pending`，没有实际后续选择就不记录 `escalated_at`。

升级后的上下文预算用大模型自己的 tokenizer 检查。不同 revision 未配对应计数器、元数据不完整或缺少大模型策略，均作为配置错误处理。

### 成本记录

`cascade_token_cost(episode)` 汇总每回合的输入与输出 token，使用 4B 权重 1.0、9B 权重 2.25。Token 客户端优先使用实际采样输出；兼容客户端使用统一模板的输入编码与规范化输出编码。这是参数量加权 token 指标，不是服务器账单。

本次补齐兼容客户端的 `prompt_token_ids`，解析错误也保留可用的输入和文本编码。缺失 token 记录时成本函数报错，不把缺失数据当作零成本。

---

## 使用入口

`scripts/smoke_episodes.py` 支持五种 `--architecture`，参数和双模型命令见 [Agent README](../../README.md#架构选择)。级联额外要求 `--large-model-dir` 与 `--large-sglang-url`，可用 `--large-model-id` 指定模型标识。

命令行在创建结果文件前检查架构参数、tokenizer 文件、任务及快照路径。级联参数不接受用于单模型架构，避免大模型配置被悄悄忽略。

---

## 验收记录

测试环境：独立 Python 3.12 环境，Transformers 4.57.6、tokenizers 0.22.2。只读取本地 4B / 9B tokenizer，不加载权重或启动推理服务。

| 检查 | 结果 |
| --- | --- |
| 全套 pytest，含两种模型的本地聊天模板验收 | 317 项通过，包覆盖率 97.85% |
| 五种架构的单元与执行器集成测试 | 计划、跳过、截断、压缩、升级、预算和跨任务状态隔离通过 |
| 真实客户端代码的离线集成 | TokenPolicyClient 模拟生成后端与兼容接口 MockTransport 均走通新增架构 |
| 模板一致性 | 4B / 9B × thinking 开 / 关 × 五种消息场景，20 项通过 |
| Ruff 与 import-linter | 通过；运行层不依赖高层架构，判分器仍只依赖 contracts |
| Wheel 构建与非 editable 安装 | 干净环境中的五种架构均走通完整任务；压缩与引用纠正后级联通过 |
| 文档和提交检查 | 17 份维护文档的 103 个本地链接、标题锚点与代码围栏通过，工作流 YAML 和 Git 空白检查通过 |

复现完整测试，在 Agent 目录执行：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
STUDYHUB_AGENT_MODEL_DIR=/path/to/Qwen3.5-4B \
STUDYHUB_AGENT_LARGE_MODEL_DIR=/path/to/Qwen3.5-9B \
python -m pytest --cov --cov-report=term-missing
ruff check src tests scripts/smoke_episodes.py
lint-imports --config .importlinter
```

未设置 tokenizer 路径时，相应模板验收跳过，其余测试不需要模型服务。

---

## 后续工作

按 Task 7–11 完成故障注入、任务模型、曝光记录、确定性判分与校准、合成快照、oracle 和隔离划分，再开展 Dev 架构比较与配对统计。正式 Test 保持封存；完成评测门禁后再推进 SFT / RL。
