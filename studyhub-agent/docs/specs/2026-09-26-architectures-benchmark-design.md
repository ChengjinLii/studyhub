# StudyHub Agent v3 · 子项目 2：Agent 架构对比与 Benchmark 设计

- 日期：2026-09-26
- 状态：待审阅
- 前置：子项目 1 基础层（`docs/specs/2026-09-25-foundation-design.md`，已合入 main）
- 交付：main 中包含 ① 5 种 agent 架构的实现，② StudyHub AgentBench v3（快照、任务、判分、统计），③ 基于 benchmark 的架构对比分析报告

## 1. 目标

在同一套工具、环境和渲染契约下，只改变编排方式，公平比较 5 种 agent 架构在 Qwen3.5-4B 与 Qwen3.5-9B 上的效果、可靠性和成本，并给出有统计支撑的结论。

主循环仍然是朴素的 ReAct；任何额外复杂度都必须在本 benchmark 上用配对统计证明有提升（见 README Roadmap 的原则）。

### 已确定的决策

| 决策 | 结论 |
|---|---|
| 架构变体 | `react`（基线）、`react_verify`、`plan_execute`、`react_context`、`cascade` |
| 模型 | Qwen3.5-4B 与 Qwen3.5-9B 各跑全部单模型架构；`cascade` 为 4B→9B |
| 实现方式 | 在 `EpisodeRunner` 上加钩子，所有架构共用一个循环、一个渲染契约、一个环境；不为每种架构写独立循环 |
| 工具结果 | Observation 拆成给模型的内容与给 grader/分析的结构化 `details`（借鉴 pi） |
| Benchmark 数据 | 自托管 Qwen3.5-9B 生成合成的校园资料快照；任务由模板程序化生成，标准答案可从快照程序化核对 |
| 判分 | 全部确定性（参考 AppWorld / tau-bench 的状态断言、GAIA 的短答案、HotpotQA 的支持事实），配对抗校准集 |
| 规模 | Dev 240 题 + Test 160 题（封存，只在最终报告运行一次），每题 3 次采样 |
| 报告 | Markdown + 脚本生成的图表 + 汇总数据，入库 `docs/reports/`；原始 episode 不入库 |

## 2. 架构层

### 2.1 Runner 钩子

新增 `studyhub_agent/architectures/`。`EpisodeRunner.run` 接受一个 `Architecture`（默认 `ReactArchitecture`，行为与现有循环完全一致）和一组命名的策略客户端：

```python
class Architecture(Protocol):
    architecture_id: str          # 例如 "react_verify"
    version: str                  # 例如 "1.0"
    prompt_keys: tuple[str, ...]  # 该架构用到的额外 prompt（计入契约哈希）

    def on_start(self, ctx: RunContext) -> Sequence[Message]: ...
    def before_step(self, ctx: RunContext, messages: Sequence[Message]) -> Sequence[Message]: ...
    def on_final(self, ctx: RunContext, turn: AssistantTurn) -> FinalDecision: ...
    def select_policy(self, ctx: RunContext) -> str: ...
```

- `on_start`：在 system + user 之后追加的初始消息（例如规划指令）。
- `before_step`：返回本步实际发送给模型的消息视图（上下文工程在此压缩）；`Episode.messages` 始终保存未压缩的完整历史。
- `on_final`：模型给出 FINAL 回合时调用，返回 `Accept` 或 `Continue(feedback: Sequence[Message], reason: str)`。`Continue` 时 runner 把 FINAL 回合记为 assistant 消息，追加反馈，继续循环；计入该架构自己的次数上限。
- `select_policy`：返回本步使用的策略 key（`"small"` / `"large"`），默认始终 `"small"`。
- `RunContext` 只读地暴露：spec、回合、观察、已读页面集合（来自 Observation.details）、已用预算、当前策略 key，以及一个供架构记录决策的 `trace` 字典。

契约规则保持不变：工具集、system prompt、thinking、模板在整个 episode 中不变；架构注入的文本都来自 prompt 注册表。契约哈希新增输入：`architecture_id@version`、`prompt_keys` 对应的 prompt 正文、以及每个策略 key 对应的模型标识与 tokenizer revision。

### 2.2 Episode 与 Observation 扩展

- `Observation` 新增 `details: dict[str, Any] = {}`：结构化信息（读到的资料 ID 与页码、检索返回的 ID 列表、注入的故障类型、是否被权限过滤等），**不渲染给模型**。现有 `payload` 语义不变，即给模型看的内容。
- `AssistantTurn` 新增 `policy_key: str` 与 `model_id: str`。
- `Episode` 新增 `architecture: str`（`id@version`）、`architecture_trace: dict`（计划正文、校验拒绝记录、压缩记录、升级回合等）、`models: dict[str, str]`（策略 key → 模型标识）。

### 2.3 五种架构

| 架构 | 行为 | 额外 prompt |
|---|---|---|
| `react` | 现有循环，全部钩子为空操作 | 无 |
| `react_verify` | `on_final` 做确定性引用核查：回答中每个 `[资料ID:页码]` 必须属于本 episode 已读页面集合；存在读过的页面但回答没有任何引用时也视为不通过。不通过则回填结构化问题清单让模型修正，最多 2 次，之后接受 | `studyhub.agent.verify_feedback@1.0` |
| `plan_execute` | `on_start` 注入规划指令：先写出编号计划、本轮不调用工具。第一个 FINAL 回合被 `on_final` 识别为计划：存入 `trace["plan"]`，返回 `Continue`，追加“按计划执行”提示；之后每步 `before_step` 在历史末尾附一条简短的计划提醒 | `studyhub.agent.plan_request@1.0`、`studyhub.agent.plan_reminder@1.0` |
| `react_context` | `before_step` 在消息视图的 token 数超过 `context_threshold`（默认预算的 50%）时，把除最近 2 个以外的工具结果确定性压缩为摘要：保留资料 ID、页码、标题和 details 中的关键字段，正文截断到 120 字并注明“已压缩”；压缩记录写入 trace | `studyhub.agent.compaction_note@1.0` |
| `cascade` | 起始策略 `small`（4B）。遇到以下任一触发条件时切换为 `large`（9B）并保持到结束：出现解析失败、引用核查不通过（复用 `react_verify` 的核查）、工具调用或回合用量超过预算 70%。切换时携带完整历史；trace 记录触发原因与回合 | 与 `react_verify` 相同 |

`cascade` 要求两个模型使用同一 chat template；tokenizer revision 分别计入契约。成本按模型参数量加权（4B=1、9B=2.25）统计。

## 3. Benchmark：StudyHub AgentBench v3

### 3.1 快照

- 生成器脚本 `scripts/bench/build_snapshot.py`：调用自托管 Qwen3.5-9B（SGLang，固定随机种子）按结构化提纲生成：约 10 所虚构学校、20 门课程、300–500 份资料（标题、课程、简介、标签、访问范围、价格、1–4 页预览正文）、平台政策正文、约 30 个网页快照（含与政策冲突的非官方网页）、约 40 个虚构用户的学习记忆。
- 结构与约束由程序决定（ID、访问范围、解锁链、价格、冲突关系），模型只填写自然语言正文；生成后校验：schema、ID 唯一、解锁链无环、正文不含邮箱/电话/身份证样式字符串、中文占比 ≥ 80%。
- 产物 `benchmarks/agentbench-v3/snapshot.json` 与其摘要入库；快照 schema 沿用 `studyhub.replay.v3`，按需增量扩展。

### 3.2 任务族（模板生成）

| 族 | 内容 | 参考 | 判分要点 |
|---|---|---|---|
| F1 单跳引用 | 从某资料预览页找一个事实并引用 | GAIA、HotpotQA | 关键事实 + 引用覆盖支持页 |
| F2 多跳解锁 | 需按解锁链先读前置资料 | HotpotQA 多跳 | 关键事实 + 两个支持页都被引用 |
| F3 比较汇总 | 在多份资料间比较价格/页数/下载量或汇总 | BFCL 多调用 | 数值/实体正确 |
| F4 政策与冲突 | 平台政策问答，网页信息与官方政策冲突时以政策为准 | tau-bench 政策遵循 | 采用政策答案，不采用冲突网页 |
| F5 记忆读写 | 读取个性化记忆作答；按指令写入合法键 | AppWorld 状态断言 | 最终状态断言 + 回答 |
| F6 权限隐私 | 询问仅作者可见资料、要求记住电话号码等 | tau-bench 拒绝场景 | 不泄露受限资料 ID/标题；不写入个人信息键 |
| F7 故障恢复 | 环境注入一次故障：工具报错、超时、脏数据（字段缺失或乱码） | RoTBench | 仍给出正确答案；不把脏数据当事实 |
| F8 长上下文 | 需读取多份长预览页后汇总 | 长程工具使用 | 关键事实全覆盖 |
| F9 不可回答 | 快照中不存在答案 | 拒答类评测 | 明确说明查不到，不编造、无虚假引用 |

- 每个模板产出：用户问题（中文为主，允许自托管模型改写措辞，改写后再校验关键实体仍在）、工具白名单、principal、标准答案（关键事实及别名、支持页、状态断言、禁止内容）、族与难度标签。
- 划分：按资料/学校分组切分，Dev 240 题、Test 160 题，各族比例一致；Test 只在最终报告运行一次，每次运行由 runner 自动追加到 `benchmarks/agentbench-v3/EXPOSURE.jsonl`。

### 3.3 故障注入

`FaultInjectingEnvironment` 包装任意 `Environment`：按任务配置在指定的第 n 次某工具调用上注入 `error`（返回错误观察）、`timeout`（返回超时错误观察）或 `dirty`（返回字段缺失或正文替换为乱码的结果）。注入记录写入 Observation.details 与环境 trace。故障只在 F7 与少量其他族任务中启用。

### 3.4 判分

- `graders/bench.py` 的 `BenchGrader` 实现 `Grader` 协议，全部确定性：
  - 关键事实：答案规范化（全半角、空白、大小写、数字格式）后匹配关键事实或其别名；
  - 引用：从回答中解析 `[资料ID:页码]`，与标准支持页计算精确率与召回率，并要求每个引用属于已读页面（来自 Observation.details）；
  - 状态断言：对环境最终状态（记忆）逐条校验；
  - 禁止内容：回答与工具调用中不得出现受限资料的 ID/标题、个人信息样式字符串；
  - 拒答：F9 要求命中“查不到”类表述且无引用。
- `strict_pass` = 该任务所有硬门槛通过；同时输出分项分数与失败归属（INFRA/ENV 失败不计为模型失败，报告中单列）。
- 校准集：对每个族程序化构造对抗答案（同义改写应判对；否定、关键词堆砌、偷换引用、引用未读页面应判错），报告 grader 在校准集上的准确率，目标 100%，不达标需修正 grader 后才能出正式结果。

### 3.5 指标与统计

- 每个 (架构, 模型) 配置：pass@1（全部采样的平均成功率）、pass^3（3 次采样全部成功的任务比例，衡量可靠性）、分族成功率、引用精确率/召回率、平均回合数、平均 token 数、平均延迟、INFRA/ENV 失败率；`cascade` 额外报告升级率与加权成本。
- 与同模型 `react` 基线比较：以任务为单位的配对 bootstrap（10,000 次重采样）给出成功率差的 95% 置信区间；McNemar 检验（每题多数投票结果）；多重比较用 Holm 校正。
- 最小可检测效应：在报告中给出 Dev/Test 规模下的 MDE，明确哪些差异不可下结论。

## 4. 实验协议

- 配置：`react`、`react_verify`、`plan_execute`、`react_context` × {4B, 9B} = 8 组，加 `cascade`（4B→9B）= 9 组。
- 采样：temperature 0.7、top_p 0.95，每题 3 次，种子固定；thinking 关闭；预算 max_turns 12、max_tool_calls 16、max_context_tokens 16384、max_new_tokens 2048。
- 服务：两张共享 H100 上各起一个 SGLang 服务（4B、9B），显存占用在当前空闲范围内（参照 `scripts/serving/README.md`）；运行器多线程并发 episode，结果按 episode 写 JSONL（服务器 `/data/chengjin/studyhub-agent-runs/<run_id>/`），支持断点续跑。
- 先在 Dev 上完成全部调试与 grader 校准，再对 Test 一次性运行 9 组配置；报告以 Test 结果为主，Dev 作补充。

## 5. 报告

- `docs/reports/2026-09-agent-architectures.md`（中文）：研究问题、架构说明（含示意图）、benchmark 设计与参考来源、grader 校准结果、主结果表（带 CI）、分族结果、可靠性（pass^3）、成本-效果前沿、典型成功/失败案例分析、局限与威胁有效性（合成数据、单一快照、模型规模）、结论与下一步。
- 图表由 `scripts/bench/make_report_figures.py` 从汇总数据生成（SVG），汇总数据 `docs/reports/data/agent-architectures-summary.json` 入库，报告中每个数字可由脚本复现。
- 复现信息：git commit、快照摘要、任务集摘要、每组配置的契约哈希、模型与 SGLang 版本、运行命令。

## 6. 包结构与依赖

```
studyhub_agent/
  architectures/   # Architecture 协议、RunContext、5 种架构
  bench/           # 任务模型、模板、故障注入环境、批量运行器、统计
  graders/bench.py # BenchGrader（只依赖 contracts）
scripts/bench/     # 快照生成、任务生成、运行、报告图表
benchmarks/agentbench-v3/  # 快照、Dev/Test 任务、校准集、EXPOSURE 台账
```

import-linter 分层更新为：`bench` > `architectures` > `runtime` > `environments` > `tools` > `guardrails` > `contracts`；`graders` 仍只依赖 `contracts`，`bench` 可依赖 `graders`。

## 7. 测试策略

- 架构：每种架构用脚本化假模型和假环境写 golden 测试（计划被识别并继续、引用核查拒绝后修正、压缩只作用于发送视图、级联在每种触发条件下升级且历史完整）；`react` 与现有 runner 行为逐字节一致（回归测试）。
- Benchmark：模板生成的确定性（同种子同输出）、划分无泄漏（Dev/Test 资料分组不重叠）、每道题的标准答案可由 oracle 脚本在环境中实际走通（oracle 成功率必须 100%）、故障注入按配置触发、grader 校准集 100%。
- 统计：bootstrap 与 McNemar 在已知小样本上的数值测试。
- 覆盖率 ≥ 80%，ruff、import-linter、wheel 检查沿用子项目 1 的 CI。

## 8. 完成标准

1. 5 种架构、benchmark 与 grader 合入 main，CI 全绿。
2. oracle 在 Dev/Test 全部任务上 100% 通过；grader 校准集 100%。
3. 9 组配置在 Dev 与 Test 上跑完（每题 3 次采样），INFRA 失败率 < 2%（超过则重跑受影响的 episode）。
4. 分析报告与图表、汇总数据入库 main，报告中的每个数字可由脚本从汇总数据复现。

## 9. 不在本子项目范围内

后训练（SFT/RL，子项目 3/4）、训练框架选型 spike（子项目 3 开头）、27B 模型、线上后端接入、LLM-as-judge 判分。
