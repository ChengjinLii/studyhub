# Agent 架构与 AgentBench v3 执行计划

**目标：** 在统一运行契约下实现五种 Agent 架构，构建 AgentBench v3，并完成 Qwen3.5-4B / 9B 的九组配置对比与分析报告。

**设计依据：** [架构与评测设计](../specs/2026-09-26-architectures-benchmark-design.md)。

**进度记录：** 2026-10-06，任务 1–6 已完成代码与离线验收。依赖分层、契约扩展和引用核查见 [前置记录](../specs/2026-10-05-architecture-hooks-progress.md)，规划、压缩与级联见 [五种架构实现](../specs/2026-10-06-architectures-progress.md)。提交记录以 Git 历史为准。

每项任务按“测试先行 → 实现 → 验证 → 提交”推进，使用复选框记录工作。

---

## 总体约定

| 项目 | 约定 |
| --- | --- |
| 架构 | `react`、`react_verify`、`plan_execute`、`react_context`、`cascade`，版本 1.0 |
| 模型 | Qwen3.5-4B 为 `small`，Qwen3.5-9B 为 `large`，级联为 small→large |
| 模型目录 | `/data/chengjin/studyhub/models/P1/Qwen3.5-4B` 与 `Qwen3.5-9B` |
| 数据 | 自托管 9B 生成合成校园快照；固定种子；任务中文占比至少 80% |
| 划分 | Dev 240 题、Test 160 题，按学校分组，资料不跨集合 |
| 采样 | temperature 0.7、top_p 0.95、每题三次、固定种子、关闭 thinking |
| 预算 | 12 回合、16 次工具调用、16384 上下文 token、2048 新 token |
| 判分 | 确定性规则；正式实验前 oracle 和判分校准集均达到 100% |
| 原始轨迹 | `/data/chengjin/studyhub-agent-runs/<run_id>/`，入库仅保留汇总与图表 |
| 曝光记录 | 每次运行追加 `benchmarks/agentbench-v3/EXPOSURE.jsonl` |
| Test 使用 | 开发与校准结束后封存，只为最终报告运行一次 |
| 质量门禁 | 覆盖率至少 80%，Ruff、import-linter、wheel 构建安装通过 |

技术栈：Python 3.12、Pydantic v2、httpx、SGLang、pytest、Ruff、import-linter；图表使用可选 matplotlib 依赖。

### 契约与分层

- 工具、系统提示、thinking 与聊天模板在一次任务中保持不变；注入文本来自提示注册表。
- 哈希覆盖架构标识、版本、参数、提示正文、模型与 tokenizer 版本，以及全部执行预算。
- `Episode.messages` 保留完整历史，`before_step` 只改变发送视图；`Observation.details` 不渲染给模型。
- 依赖方向为 `bench → architectures → runtime → environments → tools → guardrails → contracts`；判分器只依赖 `contracts`，`bench` 可依赖判分器。
- 架构协议下沉到 `contracts`，默认 ReAct 钩子位于 `runtime`，避免执行器反向依赖高层架构。

### 运行与提交

使用项目独立 Python 环境执行测试；历史执行环境为 `PY=/data/chengjin/.venvs/studyhub-agent/bin/python`。推理服务配置见 [服务说明](../../scripts/serving/README.md)。

GPU 启动前检查 `nvidia-smi`，资源使用服从实时空闲显存，只停止自己启动的进程。提交采用 Conventional Commits 英文消息，作者为 ChengjinLii，不添加 Co-Authored-By。

---

## 核查重点

1. 显式与默认 `react` 保持原始消息、回合、工具观察和终止结果一致。
2. 上下文压缩不修改原始历史或判分证据。
3. 级联传递完整历史，只升级一次，不切回小模型。
4. 判分器拒绝关键词堆砌、偷换引用和引用未读页。
5. Dev / Test 不共享学校或资料，oracle 可解全部任务。

---

## 任务 1：结构化工具证据与模型信息

**涉及文件：** `contracts/episode.py`、`environments/replay/handlers.py`、`environments/replay/environment.py` 及对应测试。

### 接口约定

| 字段 | 用途 |
| --- | --- |
| `Observation.details` | 结构化证据，默认独立空字典 |
| `read_pages` | 成功读取的资料 ID 与页码 |
| `returned_material_ids` | 检索或推荐实际返回的可见资料 |
| `material_id` | 详情与阅读对应的资料 |
| `blocked` | 是否发生权限过滤 |
| `fault` | 后续故障包装器记录的注入类型 |
| `AssistantTurn.policy_key` / `model_id` | 回合对应的策略与模型 |
| `Episode.architecture` / `architecture_trace` | 架构标识与本次任务决策 |
| `Episode.models` / `model_revisions` | 模型与 tokenizer 信息 |
| 环境 trace 的 `memory` | 最终脱敏记忆副本，用于状态断言 |

处理函数返回 `(ok, payload, error_code, new_state, details)`。证据只保存 ID、页码和标志，权限过滤不泄露隐藏资料标识；失败读取不提供有效阅读证据。

- [x] 验证新增字段的默认值、独立状态与 JSON 往返。
- [x] 验证检索、详情、阅读、权限过滤与最终记忆。
- [x] 运行完整测试，验收结构化证据改动。

---

## 任务 2：统一架构钩子

**涉及文件：** `contracts/architecture.py`、`runtime/architecture.py`、`architectures/base.py`、`runtime/runner.py`、`contracts/fingerprint.py`、`.importlinter`。

### 钩子接口

```python
class Architecture(Protocol):
    def on_start(self, ctx: RunContext) -> Sequence[Message]: ...
    def before_step(self, ctx: RunContext, messages: Sequence[Message]) -> Sequence[Message]: ...
    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision: ...
    def select_policy(self, ctx: RunContext) -> str: ...
```

`RunContext` 提供任务、回合、观察、读取页集合、预算计数和注册提示的快照，仅 trace 用于可变架构状态。`before_step` 还可调用 `count_tokens(messages)`，使用当前策略的 tokenizer 对发送视图计数。

`Accept` 结束回答，`Continue(feedback, reason)` 记录本次回答和反馈并继续，继续行为共用原任务预算。

执行器保持原有单策略调用，并支持 `architecture`、`policies`、`models`、`model_revisions` 和 `token_counters`。命名策略要求完整模型信息，不同 tokenizer 使用各自的计数器。

- [x] 检查初始化一次、每步视图处理、策略选择与最终回答钩子的调用顺序。
- [x] 检查纠正后继续、最后回合耗尽、错误策略与无效配置。
- [x] 检查默认 ReAct 轨迹回归和钩子快照隔离。
- [x] 检查架构参数、提示、模型与预算变化都改变契约哈希。
- [x] 运行完整门禁，验收钩子实现。

---

## 任务 3：引用核查

**涉及文件：** `architectures/citations.py`、`architectures/react_verify.py`、`contracts/prompts.py` 及对应测试。

`parse_citations` 支持 `[101:2]` 与全角冒号，按首次出现顺序去重。`check_citations` 检查引用是否来自成功读取的页面，以及读取后是否缺少引用；超长数字标识按无效引用处理。

`ReactVerifyArchitecture(max_rejections=2)` 失败时返回结构化反馈，包含未读页、缺引用状态、有效读取页和注册纠正提示。达到纠正上限后保留未通过标记，接受下一条回答。

提示键：`studyhub.agent.verify_feedback@1.0`。

- [x] 覆盖不同冒号、去重、未读页、缺引用、失败读取与超长数字。
- [x] 检查纠正上限、跨任务状态隔离和最后回合预算。
- [x] 检查两类策略客户端的反馈序列化与模板一致性。
- [x] 验收引用核查实现。

---

## 任务 4：规划后执行

**涉及文件：** `architectures/plan_execute.py` 与规划提示。

初始化注入三至六步计划要求；第一个最终文本保存为计划，反馈执行指令后继续。后续发送视图附加计划提醒，计划文本截断到 400 字。

若模型在规划回合直接调用工具或发生解析错误，后续钩子记录 `plan_skipped=true`，回到 ReAct 行为，不在后续回合强制补计划。空计划不附加空提醒，但仍要求继续执行。

提示键：`studyhub.agent.plan_request@1.0`、`studyhub.agent.plan_reminder@1.0`。

- [x] 覆盖计划保存、执行反馈、提醒视图与跳过计划。
- [x] 验证提醒不改变完整历史，完成门禁验收。

---

## 任务 5：上下文压缩

**涉及文件：** `architectures/react_context.py` 与压缩提示。

发送视图超过默认上下文预算 50% 时，压缩除最近两条外的工具结果。摘要保留资料 ID、页码、标题和正文 / 片段前 120 字，并标注已压缩；运行时反馈保持完整。

记录压缩回合、消息数及压缩前后实际 token 数，不修改 `Episode.messages`。摘要只来自模型已见的 payload，不注入 details；如果包含提醒后的视图没有节省 token，则保留原视图。

提示键：`studyhub.agent.compaction_note@1.0`。

- [x] 覆盖阈值、最近结果保留、重复压缩和原始历史隔离。
- [x] 检查发送视图的实际 token 预算，完成门禁验收。

---

## 任务 6：小到大模型级联

**涉及文件：** `architectures/cascade.py`。

`CascadeArchitecture(escalate_ratio=0.7, max_rejections=2)` 从小模型开始，在以下情况升级：

- 上一回合发生解析错误。
- 工具调用量或回合数达到预算 70%。
- 最终回答的引用核查失败。

升级后一直使用大模型，传递完整历史；记录 `escalated_at` 和 `escalation_reason`。升级后的引用纠正仍遵循次数上限。

成本按输入与输出 token 合计，以 4B token × 1.0、9B token × 2.25 计算。缺少 token 记录时拒绝给出零成本；兼容客户端的计数来自本地统一模板与规范化输出，不是服务器账单。

引用分支只有在仍允许纠正时请求升级；`max_rejections=0` 表示关闭引用纠正。最后回合被拒绝时只记录待升级原因，不虚构已执行的大模型回合。

- [x] 覆盖全部升级条件、只升级一次、不降级与完整历史传递。
- [x] 检查回合模型信息、逐策略计数和加权成本，完成门禁验收。

---

## 任务 7：故障注入环境

**涉及文件：** `bench/faults.py` 与环境包装测试。

`FaultSpec(tool, on_call, kind)` 指定工具第几次调用发生 `error`、`timeout` 或 `dirty`。调用计数从 1 开始，重置时清空。

错误和超时不执行内部工具，返回可重试错误观察；脏数据调用内部环境后，将文本类字段替换为确定性乱码并移除一个数字字段。故障记录写入 details 和环境 trace。

- [ ] 覆盖三类故障、逐工具计数、重置与普通调用透传。
- [ ] 运行门禁并提交。

---

## 任务 8：任务模型与曝光记录

**涉及文件：** `bench/tasks.py`、`bench/ledger.py`。

`BenchTask` 包含任务标识、F1–F9 任务族、划分、难度、用户问题、身份、工具名单、标准答案、故障配置和快照摘要。

标准答案 `Gold` 包含事实及别名、支持页、记忆状态断言、禁止内容、不可回答标记和 oracle 工具路径。加载器读取 JSONL，转换器生成 `EpisodeSpec`。

曝光记录保存运行标识、划分、配置、任务数和 Git 提交。

- [ ] 检查往返序列化、非法任务族、任务转换与 JSONL 追加。
- [ ] 运行门禁并提交。

---

## 任务 9：确定性判分与校准集

**涉及文件：** `graders/bench.py`、`graders/normalize.py`、`graders/calibration.py`。

判分器只依赖 contracts，bench 将任务标准答案转换成判分视图。硬门槛包括：

| 门槛 | 检查 |
| --- | --- |
| `answer_facts` | 规范化事实与别名匹配 |
| `citations_valid` | 引用来自实际读取页 |
| `supporting_recall` | F1 至少覆盖一页，F2 覆盖全部支持页 |
| `state` | 最终记忆状态断言 |
| `forbidden_absent` | 回答与工具参数不含禁止内容 |
| `refusal` | F9 明确拒答且无引用 |

规范化包含 NFKC、空白与标点、大小写和 0–9999 的中阿数字形式。引用规则与架构核查保持一致，通过低层共享代码或受测试约束的实现遵守依赖方向。

校准样例包括正确改写、否定、关键词堆砌、偷换引用、未读页引用和不可回答任务中的编造。

- [ ] 对每个门槛和对抗样例构造测试。
- [ ] 校准集达到 100% 后，运行门禁并提交。

---

## 任务 10：合成快照

**涉及文件：** `scripts/bench/build_snapshot.py`、`snapshot_outline.py` 与结构测试。

提纲按固定种子确定：十所学校、二十门课程、四百份资料、三十个网页快照和四十份虚构记忆。资料访问范围约 80% 公开 / 免费、15% 付费、5% 仅作者可见；每份一至四页，约四十条无环两步解锁链。

程序确定结构、价格、下载量、五类政策、十个政策冲突网页和每页一至两个植入事实，9B 只生成中文标题、简介和正文。

生成器校验植入事实、结构、唯一 ID、个人信息样式与中文占比；正文最多重试三次，再使用包含植入事实的模板句。

产物为 `snapshot.json`、独立 `outline.json` 和中文 `SNAPSHOT_CARD.md`。提纲元数据不进入模型工具内容。

- [ ] 检查确定性、无环、范围比例与事实唯一性。
- [ ] 生成快照、校验结果与摘要，停止自启模型服务并提交。

---

## 任务 11：任务模板、oracle 与划分

**涉及文件：** `bench/templates.py`、`bench/oracle.py`、`scripts/bench/build_tasks.py`。

各任务族按事实、政策、冲突、解锁链、权限和记忆生成任务，附带标准答案、支持页、状态断言、禁止内容、故障与 oracle 路径。

| 任务族 | 目标比例 |
| --- | --- |
| F1 单跳引用 | 15% |
| F2 多跳解锁 | 12% |
| F3 比较汇总 | 10% |
| F4 政策冲突 | 10% |
| F5 记忆读写 | 10% |
| F6 权限隐私 | 10% |
| F7 故障恢复 | 13% |
| F8 长上下文 | 10% |
| F9 不可回答 | 10% |

学校 0–5 用于 Dev，6–9 用于 Test。可选 9B 问题改写在测试中默认关闭，启用时重新检查关键实体。

oracle 按工具路径执行并生成带事实与引用的模板回答，通过真实回放环境和判分器检验。

- [ ] 检查每类模板、学校隔离与逐类 oracle。
- [ ] 生成 240 / 160 题、`calibration.jsonl`、`TASKS_CARD.md` 与曝光记录文件。
- [ ] 全部四百题 oracle 和判分校准均达到 100%，再提交任务集。

---

## 任务 12：批量执行与统计

**涉及文件：** `bench/runner.py`、`bench/stats.py`、`scripts/bench/run_bench.py`、`summarize.py`。

每个任务与采样保存 episode、判分、逐模型 token、加权成本和延迟。支持并发与断点续跑，按任务标识和采样编号跳过已完成结果。

| 统计 | 配置 |
| --- | --- |
| pass@1 | 所有采样的平均成功率 |
| pass^3 | 三次采样全部成功的任务比例 |
| 配对 bootstrap | 按任务重采样 10000 次，95% 置信区间 |
| McNemar | 每题多数结果的配对检验 |
| Holm | 多重比较校正 |
| MDE | 报告当前样本量下的最小可检测效应 |

- [ ] 检查续跑、成本权重和已知小样本的统计结果。
- [ ] 验证配置、快照、任务与契约信息完整，运行门禁并提交。

---

## 任务 13：正式实验

- [ ] 按空闲显存启动 4B 与 9B 服务，记录版本和参数。
- [ ] 在 Dev 运行九组配置，每题三次采样。
- [ ] 基础设施失败率低于 2%；修复服务后只续跑受影响任务。
- [ ] 任何判分器修改都重新通过校准，避免向特定架构调参。
- [ ] 固定运行提交，在 Test 一次性完成九组配置并登记曝光。
- [ ] 保存两套汇总结果，停止自启服务并确认资源释放。

九组配置为四种单模型架构 × 两个模型，再加 4B→9B 级联。

---

## 任务 14：报告与图表

**涉及文件：** `scripts/bench/make_report_figures.py`、`docs/reports/2026-09-agent-architectures.md`、图表与汇总 JSON。

报告内容包含研究问题、架构示意、基准来源与借鉴点、校准结果、主结果表、任务族表现、可靠性、成本前沿、级联分析、三至五个案例、MDE 和有效性讨论。

主结果报告成功率、置信区间、相对 ReAct 的增益、Holm 校正 p 值、token、延迟和成本。所有数字来自汇总 JSON，图表脚本同时生成表格。

- [ ] 使用小型合成汇总测试绘图和表格。
- [ ] 生成中文报告，逐项核对数字并提交。

---

## 任务 15：质量门禁与文档

- [ ] Ruff 检查源码、测试与脚本。
- [ ] import-linter 验证最终依赖方向。
- [ ] pytest 覆盖率至少 80%。
- [ ] wheel 构建、非 editable 安装与真实 tokenizer 模板验收通过。
- [ ] README 只介绍已实现功能、架构和使用方法；实验路线与阶段状态写入专门文档。

---

## 规格对应

| 设计部分 | 任务 |
| --- | --- |
| 架构与钩子 | 1–6 |
| 故障与任务生成 | 7–8、10–11 |
| 判分与校准 | 9、11 |
| 批量执行与统计 | 12–13 |
| 报告与复现 | 14–15 |

快照、任务、实验和报告使用明确行为与验收门禁推进，不能以生成了文件代替通过验证。
