# StudyHub Agent v3 · 子项目 1：基础层设计

- 日期：2026-09-25
- 状态：待审阅
- 范围：studyhub-agent 重构的第一个子项目（共 4 个：基础层 → 评测 → 训练流水线 → RL/OPD）

## 1. 背景与目标

2026-09 的两份设计评审得出结论：现有 studyhub-agent 的 `src/studyhub_agent` 契约层没有被任何真实路径使用。实际运行的是 4 套各自独立的 agent 循环，分别用于 teacher 数据生成、RL v2、RL v3/OPD 和评测。它们之间存在以下偏差：

- system prompt 至少有 7 份；
- thinking 开关不一致，同一条轨迹中途也会切换；
- 工具 schema 有两套（v1 共 7 个，v3 共 11 个）；
- 训练用 `web_fetch`，生产规定用 `web_extract`；
- 评测 runner 反向 import 了 training 的私有函数。

后训练方面，4B/9B 的 SFT、GRPO 和 OPD 都没有在统计上显著超过起点模型。4B 线从预训练 Base 起步，而官方 instruct 版的基线从未测过。

项目的首要目标是**研究与展示**：实验要能复现，评测要有统计效力，结论要站得住。基础层的职责是提供唯一的运行契约和唯一的执行器，让数据生成、RL rollout、评测三条路径逐 token 一致。

### 已确定的决策

| 决策 | 结论 |
|---|---|
| 主线模型 | Qwen3.5-4B（官方 post-trained instruct 版起步）；9B、27B 作 prompted 对照 |
| 数据来源 | 只用开源数据和自托管的开源教师；下线 Codex/gpt-5.6 生成的数据；生产素材最多只用公开预览，且去除上传者信息 |
| 执行循环 | 自写精简 `EpisodeRunner`，去掉 Hermes 依赖；AReaL 只作训练后端 |
| 模型接口 | 统一 `PolicyClient`，提供 token 级和 OpenAI 兼容两种实现 |
| thinking | 作为契约字段，默认关闭，整条轨迹固定；基线评测额外跑一组开启 |
| 工具环境 | 离线 replay 环境，工具接口对齐后端 MCP |
| 旧代码 | 新建干净的包，只移植精华；旧代码和旧分支删除，用 tag 留存历史 |
| 训练方法与数据集 | 不受旧方案约束，按评测结果选择 SFT/RL/OPD 和数据集（负责人 2026-09-25 授权） |

## 2. 包结构与依赖方向

目录仍为 `studyhub-agent/`，包名 `studyhub_agent`，`pyproject` 项目名改为 `studyhub-agent`，版本 3.0.0。

```
studyhub_agent/
  contracts/        # 纯数据定义，不依赖包内其他模块
    tools.py        # ToolSpec(name, version, json_schema, description) + schema lint
    prompts.py      # 版本化 system prompt 注册表，按 id@version 取用
    episode.py      # EpisodeSpec / Turn / ToolCall / Observation / Episode / FailureOwner
    render.py       # 唯一的 render(messages, tools, thinking) → token ids；工具调用解析
    fingerprint.py  # 契约哈希
  runtime/          # EpisodeRunner、PolicyClient 协议与两种实现、预算控制
  environments/     # Environment 协议 + ReplayEnvironment
  tools/            # 7 个工具的实现 + MCP 名称适配
  graders/          # Grader 协议 + 测试用精确匹配 grader
  guardrails/       # 移植：PermissionContext、隐私脱敏、SSRF 策略
```

依赖方向是单向的：`contracts` ← `guardrails` ← `tools` / `environments` ← `runtime` ← `graders`。子项目 2、3 的 eval 和 training 只能依赖这些层，不允许反向依赖。这一约束用 import-linter 写进 CI。

## 3. 运行契约

**契约哈希**由以下内容的规范化 JSON 取 SHA-256 得到：

- system prompt 的 id@version 与正文；
- 工具 ToolSpec 集合，按名称排序；
- thinking 开关；
- chat template 的 tokenizer revision；
- max context 和 max new tokens；
- 单回合互斥规则的版本号。

**契约规则**（每条都有对应测试）：

1. 一个 episode 在整个生命周期内契约哈希不变。prompt、工具、thinking、模板都不允许中途切换，包括"强制结束轮"。
2. 每个 assistant 回合要么是 1 个或多个工具调用，要么是最终文本，不能混合。混合输出按解析失败处理。
3. `EpisodeSpec`、SFT 样本、RL rollout、评测结果都记录契约哈希。哈希不一致的数据不能混入同一次训练或同一张对比表。
4. 所有配置对象使用 `extra="forbid"`，未知参数直接报错。
5. schema lint 拒绝非 JSON Schema 标准的类型（例如 `int`），拒绝缺少 `description` 的参数和超长的 enum。

**`render()`** 是唯一可以把消息转成 token 的函数：

- SFT 数据的 tokenize、token 计数、token 级 `PolicyClient`、parity 校验都调用它。
- 底层使用 tokenizer 自带的 chat template（Qwen3.5 官方 revision 固定在契约里），不做 overlay 软链。
- 工具调用的解析和渲染成对实现，并有往返测试：渲染后再解析，结果必须和原来一致。

## 4. EpisodeRunner

大约 300 行。输入：`EpisodeSpec`、`Environment`、`PolicyClient`、预算。循环逻辑：

1. 由 `EpisodeSpec` 构造初始消息，包括 system prompt、用户任务和可见的工具。
2. 调用 `policy.step(messages, tools, thinking)`，得到 `AssistantTurn`，它是以下三种之一：
   - 工具调用（`tool_calls`）；
   - 最终文本（`final_text`）；
   - 解析失败（`parse_error`）。
3. 解析失败时，把结构化错误作为 observation 回填，并计入 `parse_error_budget`。超出预算则以 MODEL 失败结束。
4. 工具调用依次经过 guardrails（权限、隐私）和预算检查（调用次数、上下文 token），再交给 Environment 执行，得到 observation。
5. 遇到最终文本、预算耗尽、达到最大轮数或 INFRA 错误时停止。

输出 `Episode`，包含：

- 完整消息；
- 每个回合的 token ids 与 logprob（仅 token 级客户端）；
- 契约哈希；
- 每轮耗时与 token 数；
- 终止原因；
- 失败归属（`MODEL` / `ENV` / `INFRA`）。

推理服务超时、连接错误等 INFRA 错误作为显式状态返回，不抛异常，也不依赖训练框架静默丢弃。

上下文预算控制移植自现有的 `ContextBudgetController`，只保留精确的 token 计数和遥测。它注入的"请收尾"引导文本属于 prompt 注册表的一部分，受契约哈希约束。

## 5. PolicyClient

```python
class PolicyClient(Protocol):
    def step(self, messages: Sequence[Message], tools: Sequence[ToolSpec], *, thinking: bool) -> AssistantTurn: ...
```

- **`TokenPolicyClient`**，用于学生模型：
  1. 用 `render()` 得到 input ids；
  2. 调 SGLang 原生 `/generate`，输入 token，输出 token 和 logprob；
  3. 用 `render` 模块里的解析器解析。

  RL 阶段由 AReaL 的推理引擎提供同一接口的实现，放在子项目 3/4 的 adapter 里。
- **`OpenAICompatPolicyClient`**，用于教师和对照基线：
  1. 调 `/v1/chat/completions`，传入 messages 和 tools；
  2. 回复用 `render()` 重新渲染一遍，作为标准化的 token 序列，SFT 数据只使用这份；
  3. 校验服务端解析出的工具调用和本地解析结果一致，不一致时记为 `PARSE_MISMATCH` 并计入指标。

## 6. 工具集与环境

工具名用下划线形式（部分 tool-call 格式不允许点号），由 `tools/mcp_names.py` 映射到后端 MCP 名称。

| 工具 | 对应后端 MCP | 数据来源 |
|---|---|---|
| `materials_search(query, filters?, limit?)` | `materials.search` | replay 快照 |
| `materials_get(material_id)` | `materials.get` | replay 快照 |
| `materials_recommend(context, limit?)` | `materials.recommend` | replay 快照 |
| `platform_policy(topic)` | `platform.policy` | 静态政策文本 |
| `materials_read(material_id, page?)` | 暂无，标记为 snapshot 能力 | 公开预览文本 |
| `web_extract(urls[])` | 暂无 | 锁定的网页快照 |
| `memory_get(keys?)` / `memory_update(key, value)` | 暂无 | fixture，经过隐私 guardrails |

`materials_read`、`web_extract`、`memory_*` 在 ToolSpec 里标注 `capability="snapshot"`。它们的评测结果不能被表述为线上产品能力。

`Environment` 协议如下：

```python
class Environment(Protocol):
    def reset(self, spec: EpisodeSpec) -> None: ...
    def tool_specs(self) -> Sequence[ToolSpec]: ...
    def execute(self, call: ToolCall) -> Observation: ...
    def trace(self) -> EnvironmentTrace: ...
```

`ReplayEnvironment` 从 `benchmark_v2/environment.py` 移植，保留两样东西：

- 发现/解锁门控：只有先通过搜索发现某份资料，才能读取它；
- 快照 manifest 哈希。

本子项目不负责快照数据的内容，数据由子项目 2 构建。这里只提供一份用于测试的小型 fixture 快照。

## 7. Grader 协议

```python
class Grader(Protocol):
    def grade(self, episode: Episode, task: TaskSpec) -> GradeResult: ...
```

`GradeResult` 包含以下字段：

- `strict_pass: bool`
- `hard_gates: dict[str, bool]`
- `scores: dict[str, float]`
- `failure_owner`
- `evidence: list[str]`

训练 reward 和 benchmark 评测是两个独立实现，由子项目 2 编写，并共用一套对抗校准集。本子项目只交付协议和测试用的 `ExactMatchGrader`。

## 8. 旧代码与旧分支的处理

1. 在删除之前的 main 上打 tag `legacy-agent-v2`。
2. 未合并的分支先打归档 tag 再删除：
   - `codex/qwen35-4b-opd-evaluation` → `archive/opd-evaluation`
   - `codex/qwen35-4b-opd-execution` → `archive/opd-execution`
   - `codex/qwen35-4b-opd-preflight` → `archive/opd-preflight`
3. 删除 `studyhub-agent/` 下除 `docs/`、`design-defects/` 以外的所有旧目录，包括：
   - `src`、`training`、`scripts`、`configs`、`benchmarks`
   - `ai_platform`、`eval`、`external_benchmarks`、`integrations`、`fixtures`、`tests`
   - 被 git 跟踪的 `data_registry`、`research`、`ml`、`TRAINING_READY.json` 等
4. 旧文档整体移到 `studyhub-agent/docs/history/`，design-defects 一并移入。OPD 分支上的评测结论整理为 `docs/history/opd-evaluation.md`。
5. 删除 GitHub 和服务器上与 agent 相关的旧分支与 worktree：
   - `agent-v2/*`、`agent/*`、`codex/*`、`research/*`
   - 服务器上本地的 `refactor/*`、`publish/*`
   - 对应的 9 个 worktree
6. **不在本子项目删除**：
   - 被 gitignore 的大体积产物，即 `artifacts/`（约 836G）、`training_artifacts/`、`evaluation_artifacts/`、`datasets/`。删除前需列出清单，再由负责人确认。
   - 与 agent 无关的远端分支，包括 dependabot、`upgrade/next-16`、`fix/payout-settlement-integrity`。

## 9. 测试策略

新包的覆盖率要求不低于 80%。

- **契约**：
  - schema lint 能拦下非法类型；
  - `render()` 的渲染/解析往返一致；
  - 混合回合被拒绝；
  - 契约哈希对每个组成字段都敏感。
- **执行器**：用脚本化的 fake policy 和 fake env 生成 golden episode，覆盖四种情况：
  - 正常结束；
  - 预算耗尽；
  - 解析失败回填，以及超出预算；
  - INFRA 失败。
- **一致性（parity）**：同一 `EpisodeSpec` 分别经 `TokenPolicyClient`（fake generate）和 `OpenAICompatPolicyClient`（fake server）运行，要求标准化 token ids 完全相同、契约哈希相同。
- **依赖方向**：import-linter。
- **guardrails**：随代码移植原有测试。
- **CI**：`.github/workflows` 新增 studyhub-agent job，运行 ruff、pytest 与覆盖率检查、import-linter。

## 10. 完成标准

1. 新包的 CI 全绿，覆盖率不低于 80%，parity 测试通过。
2. 在服务器上用 SGLang 部署官方 Qwen3.5-4B（instruct）。`EpisodeRunner` 跑通 fixture 快照中的 3 个任务，并生成带契约哈希的 `Episode` JSONL。
3. 第 8 节列出的旧代码、旧分支、旧 worktree 全部删除；tag 已推送。
4. README 按新架构重写。

## 11. 不在本子项目范围内

以下内容不属于本子项目：

- benchmark 数据构建与 grader 实现（子项目 2）；
- 数据注册、训练 launcher、run manifest、SFT（子项目 3）；
- RL/OPD（子项目 4）；
- 线上接入后端 MCP。
