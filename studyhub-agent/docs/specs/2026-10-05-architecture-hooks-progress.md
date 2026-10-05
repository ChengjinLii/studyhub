# Agent v3 架构钩子开发记录

- 日期：2026-10-05
- 后续进度：Task 4–6 已于 2026-10-06 完成代码与离线验收，见 [五种架构实现记录](2026-10-06-architectures-progress.md)。本文保留前置阶段的实现与验收记录。
- 路线：沿用 [子项目 2 设计](2026-09-26-architectures-benchmark-design.md) 与 [执行计划](../plans/2026-09-26-architectures-benchmark-plan.md)，先开发计划中 Task 1-3，不跳过 benchmark 直接增加多智能体或启动训练。
- 边界：独立 Python 包与冻结快照，不接主站、生产 API、数据库、对象存储或 Review-Jev，不启动生产服务。

---

## 已实现

| 能力 | 实现与边界 |
| --- | --- |
| 结构化证据 | `Observation.details` 记录成功读取的 `(material_id, page)`、实际返回的可见资料 ID 与权限过滤标志；不渲染进工具消息，不把失败读取算成证据 |
| 环境状态 | Replay trace 返回当前 episode 的脱敏记忆副本，供后续确定性状态断言使用，不写数据库 |
| 统一编排 | 同一个 `EpisodeRunner` 支持 `on_start`、`before_step`、`on_final`、`select_policy`；默认仍是无附加行为的 ReAct |
| 轨迹隔离 | 钩子的上下文与发送消息为独立快照，压缩或修改发送视图不覆盖保存的原始消息、回合与观察；返回 trace 也与钩子状态隔离 |
| 模型溯源 | 每回合记录 `policy_key`、`model_id`，episode 记录架构、决策 trace、模型及 tokenizer revision 映射 |
| 引用自检 | `react_verify@1.0` 检查未读页引用和读取后缺引用，失败时注入注册表中的纠正提示，默认最多纠正两次 |
| 使用入口 | 现有 `scripts/smoke_episodes.py` 可指定 `--architecture react_verify`，仍只面向用户自行启动的推理服务 |

---

## 实现调整

原方案把 `Architecture` 协议与默认架构都放在高层 `architectures` 包，但同时要求 `runtime` 不导入它。为避免循环依赖和破坏 import-linter，协议、`RunContext` 与 `Accept` / `Continue` 下沉到 `contracts/architecture.py`，无操作 ReAct 钩子放在 `runtime/architecture.py`，`architectures/base.py` 提供统一公开导出。高层 `react_verify` 依赖基础层，Runner 不反向依赖它。

所有架构状态放在本次 episode 的 trace，配置对象本身不保存纠正次数；同一架构实例可重复运行，不会继承上一条任务的计数。钩子收到冻结的数据容器及独立数据副本，只有 trace 用于记录决策。

契约哈希除原有字段外，覆盖架构 ID / 版本、注册提示正文、架构参数、命名模型 / tokenizer revision，以及回合、工具、解析错误预算。否则 `max_rejections=0` 与 `2`、不同工具预算等会落到同一个哈希，污染实验比较。参数字典与模型映射顺序不影响哈希，实际渲染工具顺序仍影响哈希。

命名策略要求完整且非空的模型和 tokenizer revision 信息；不同 tokenizer revision 必须提供对应策略的 token 计数器。每步用本步实际策略的计数器检查发送视图，避免未来级联时用小模型的计数器代替大模型。旧单策略调用仍兼容；未提供模型名时不猜测模型身份。

新字段保留默认值，旧 episode JSON 仍可读；新契约哈希会改变，历史样本不能重标或与新契约混用。

---

## 引用核查边界

这是**引用来源检查和有界纠正策略**，不是事实蕴含判分、版权审核或硬安全门禁。一个引用来自已读页，不等于该页支持回答中的全部断言。

按原设计，达到两次纠正上限后会接受下一条回答，即使引用仍不通过。trace 必须保留 `citation_verified=false`、`verify_limit_reached=true` 与逐次 `citation_checks`；下游不能仅凭 `termination=final_answer` 宣称回答已验证。若最后允许的回合仍被拒绝，则结果为 `max_turns`，没有最终答案，不能突破原预算继续生成。

引用核查只认可 `ok=true` 的 `materials_read` 结构化证据，不认可搜索标题、`materials_get`、模型自述、错误 payload 或其他工具伪造的 `read_pages`。

资料 ID 与页码的数字文本超过 20 位时标记 `invalid=true` 并进入纠正，不尝试超长整数转换，避免模型异常输出使整个 episode 或 JSON 序列化崩溃。

---

## 验证

使用独立 Python 3.12 检查环境运行测试，不修改原有 `.venv` / `.venv-train`。测试覆盖默认 ReAct 与显式 ReAct 等价、钩子顺序、纠正后继续、最终回合预算、上下文视图隔离、命名策略溯源与逐策略计数、错误配置提前拒绝、哈希差异、读取失败不生成有效证据、跨 episode 状态隔离。

| 本地验收 | 结果 |
| --- | --- |
| 全套 pytest，含本地 Qwen3.5-4B tokenizer 模板验收 | 225 passed，包覆盖率 97.43% |
| 新增纠正反馈的模板兼容性 | Transformers 4.57.6，thinking 开 / 关均通过，仅读本地 tokenizer、不加载模型权重 |
| 两类真实客户端代码的离线集成测试 | TokenPolicyClient 的模拟生成后端、OpenAI-compatible 的 httpx MockTransport 均走通未读页引用→反馈→修正，不是真实模型推理 |
| Ruff 与 import-linter | 通过；Runner 不反向依赖高层架构，grader 仍只依赖 contracts |
| Wheel 构建与非 editable 安装 | 新包完整包含模板与架构模块，在干净环境通过四回合脚本化引用纠正流程 |
| Git diff 空白检查 | 通过 |

CI 的 Agent 工作流追加冒烟脚本 lint 与 wheel 中的架构导入检查；未执行远端 CI。本次没有启动 SGLang、训练、正式模型效果评测、网站服务或真实数据库。

本次完整测试的复现方式（在 `studyhub-agent/` 下，需要已安装 `[dev,tokenizers,acceptance]` 与本地模型 tokenizer）：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
STUDYHUB_AGENT_MODEL_DIR=/path/to/Qwen3.5-4B \
python -m pytest --cov --cov-report=term-missing
ruff check src tests scripts/smoke_episodes.py
lint-imports --config .importlinter
```

未设置模型目录时，六项模板验收会跳过；其余单元与离线集成测试不依赖权重、GPU、网站或数据库。

另外直接加载修改前提交 `c2092207c41c41709a8c38343d0eefeb99668f4f` 中的 Runner，与新 Runner 比较检索阅读、解析错误恢复、解析预算耗尽、工具预算耗尽和最终回合五个脚本化场景；消息、回合、观察与终止结果一致。检索阅读场景的基础轨迹摘要还固定在回归测试中。该比较不要求新增元数据和契约哈希保持旧值，也不是大模型效果评测。

---

## 下一步

1. 按 Task 4-6 开发 `plan_execute`、`react_context`、`cascade`，全部复用现有循环、提示注册表和证据契约。
2. 按 Task 7-11 开发故障注入、任务加载、确定性 grader、对抗校准集与 oracle；先确保任务可解、判分不奖励关键词堆砌或未读页引用。
3. 再运行 Dev 架构对比、配对统计、成本分析，封存 Test 并登记曝光，不在没有实验依据时宣称某架构更好。
4. 只有完成这些门禁后，再推进训练框架 spike、SFT / RL 与小到大级联的效果优化，继续保持独立于网站。
