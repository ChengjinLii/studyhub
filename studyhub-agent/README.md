<div align="center">

# StudyHub Agent v3

**面向高校学习场景的工具调用 Agent 与运行框架**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](#快速开始)
[![Qwen](https://img.shields.io/badge/Model-Qwen3.5--4B_%2F_9B-2563eb)](#能力概览)
[![Pydantic](https://img.shields.io/badge/Contracts-Pydantic-E92063)](#运行契约)
[![SGLang](https://img.shields.io/badge/Serving-SGLang-15803d)](#模型推理)

[能力概览](#能力概览) | [系统架构](#系统架构) | [架构选择](#架构选择) | [快速开始](#快速开始) | [开发文档](#开发文档)

</div>

StudyHub Agent 以 Qwen3.5-4B 为主要模型，将资料检索、预览阅读、政策查询与学习记忆统一到一个可记录、可回放的工具调用循环中。

**同一套执行器，同一份运行契约，完整保留每次任务的工具证据与决策轨迹。**

---

## 能力概览

| 场景 | 工具与能力 |
| --- | --- |
| 查找资料 | `materials_search`、`materials_recommend` |
| 查看资料 | `materials_get`、`materials_read` |
| 查询规则 | `platform_policy` |
| 提取网页 | `web_extract`，从网页快照获取内容 |
| 学习记忆 | `memory_get`、`memory_update` |
| 回答核查 | `react_verify`，检查引用页记录并反馈纠正 |
| 执行规划 | `plan_execute`，先生成简短计划，再开展工具调用 |
| 上下文管理 | `react_context`，按 token 阈值压缩较早的工具结果 |
| 模型级联 | `cascade`，根据解析错误、引用核查和预算用量从 4B 升级至 9B |
| 运行分析 | 记录回合、观察、预算、终止原因与模型信息 |

---

## 系统架构

```text
用户问题 -> 消息渲染 -> 策略生成 -> 工具执行 -> 观察记录
                            ^                   |
                            +-------------------+
                            |
                         最终回答 -> 引用核查（可选）
```

五种架构共用 `EpisodeRunner`，通过钩子控制规划、模型选择、消息视图与回答核查。

| 模块 | 职责 |
| --- | --- |
| `contracts` | 工具协议、提示注册表、任务与回合模型、消息渲染解析、契约哈希 |
| `guardrails` | 权限检查、隐私脱敏与网页访问策略 |
| `tools` | 八项工具定义及 MCP 名称映射 |
| `environments` | 环境协议与冻结快照回放 |
| `runtime` | 任务执行器、模型客户端与预算控制 |
| `architectures` | ReAct、引用核查、规划执行、上下文压缩与模型级联 |
| `graders` | 判分协议与精确匹配判分器 |

模块依赖方向由 import-linter 自动检查。

### 架构选择

| 架构 | 行为 | 默认参数 |
| --- | --- | --- |
| `react` | 按工具反馈逐步检索、阅读与回答 | 无附加参数 |
| `react_verify` | 回答后检查引用来源，并反馈修正 | 最多纠正 2 次 |
| `plan_execute` | 首轮生成计划，后续附加计划提醒 | 提醒保留计划前 400 字 |
| `react_context` | 超过 token 阈值后压缩较早的工具结果 | 阈值为上下文预算的 50%，保留最近 2 条结果，摘要前 120 字 |
| `cascade` | 从 `small` 升级至 `large`，随后持续使用大模型 | 预算触发比例 70%，最多纠正 2 次 |

规划和引用纠正共用任务回合预算；压缩只改变发送视图，原始消息与工具证据完整保留。架构参数、注册提示和模型版本共同计入契约哈希。

---

## 快速开始

在 `studyhub-agent/` 目录下执行：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,tokenizers]"
```

### 开发检查

```bash
.venv/bin/ruff check src tests scripts/smoke_episodes.py
.venv/bin/lint-imports --config .importlinter
.venv/bin/pytest --cov
```

### 模型推理

SGLang 服务的启动、参数配置与 GPU 使用方法见 [推理服务说明](scripts/serving/README.md)。

服务启动后，可以运行示例任务：

```bash
.venv/bin/python scripts/smoke_episodes.py \
  --model-dir ../models/P1/Qwen3.5-4B \
  --sglang-url http://127.0.0.1:30411 \
  --snapshot tests/fixtures/replay_snapshot.json \
  --tasks tests/fixtures/smoke_tasks.jsonl \
  --architecture react_verify \
  --model-id Qwen/Qwen3.5-4B \
  --out /tmp/studyhub-agent-smoke/episodes.jsonl
```

结果以 Episode JSONL 保存，包含最终回答、工具轨迹、引用核查与模型信息。历史运行样例见 [基础层冒烟记录](docs/evidence/foundation-smoke-2026-09-25.jsonl)。

替换 `--architecture` 即可使用单模型架构。对应参数如下：

| 架构 | 命令行参数 |
| --- | --- |
| `react_verify` | `--max-citation-rejections` |
| `plan_execute` | `--max-plan-chars` |
| `react_context` | `--context-threshold`、`--keep-recent-tools`、`--max-text-chars` |
| `cascade` | `--escalate-ratio`、`--max-citation-rejections`，以及大模型连接参数 |

### 双模型级联

分别准备 4B 与 9B 推理服务后，运行：

```bash
.venv/bin/python scripts/smoke_episodes.py \
  --model-dir ../models/P1/Qwen3.5-4B \
  --sglang-url http://127.0.0.1:30411 \
  --model-id Qwen/Qwen3.5-4B \
  --large-model-dir ../models/P1/Qwen3.5-9B \
  --large-sglang-url http://127.0.0.1:30412 \
  --large-model-id Qwen/Qwen3.5-9B \
  --snapshot tests/fixtures/replay_snapshot.json \
  --tasks tests/fixtures/smoke_tasks.jsonl \
  --architecture cascade \
  --out /tmp/studyhub-agent-smoke/cascade.jsonl
```

每回合记录实际使用的 `policy_key` 与 `model_id`。模型切换携带完整历史，各模型使用自己的 tokenizer 检查上下文预算。

---

## 引用核查

`react_verify` 支持 `[101:2]` 和全角冒号形式的资料页引用，以成功读取的页码记录为核查依据。核查失败时，执行器反馈问题清单，交由模型修正。

已有执行器、环境与策略客户端时，可直接指定架构：

```python
from studyhub_agent.architectures import ReactVerifyArchitecture

episode = runner.run(
    spec,
    environment,
    policy,
    architecture=ReactVerifyArchitecture(max_rejections=2),
)
```

| 参数或字段 | 含义 |
| --- | --- |
| `max_rejections` | 最大纠正次数，默认 2 |
| `citation_checks` | 每次引用核查的明细 |
| `citation_verified` | 最后一次引用核查是否通过 |
| `verify_limit_reached` | 是否达到纠正次数上限 |

引用核查与其他回合共用任务预算。具体判定规则和结果解释见 [架构实现说明](docs/specs/2026-10-05-architecture-hooks-progress.md#引用核查边界)。

---

## 运行契约

每次任务使用 `contract_hash` 标识运行配置，覆盖提示、工具定义、聊天模板、tokenizer 版本、执行预算、架构参数与模型信息。

工具观察分为两部分：`payload` 是模型可见内容，`details` 保存读取页码等结构化证据。架构钩子可调整本次发送的消息视图，任务记录保留完整原始历史。

| 记录 | 主要内容 |
| --- | --- |
| `Episode` | 任务、消息、回合、观察、最终回答与终止原因 |
| `AssistantTurn` | 生成文本、工具调用、token 数据、策略名称与模型名称 |
| `Observation` | 工具内容、执行状态与结构化证据 |
| `architecture_trace` | 计划、引用核查、压缩 token 用量与模型升级记录 |
| `models` / `model_revisions` | 模型与 tokenizer 版本映射 |

命名策略通过 `policies` 指定；不同 tokenizer 版本使用对应的 `token_counters` 进行预算计数。完整接口与兼容规则见 [基础层设计](docs/specs/2026-09-25-foundation-design.md) 和 [架构实现说明](docs/specs/2026-10-05-architecture-hooks-progress.md)。

---

## 开发文档

| 文档 | 内容 |
| --- | --- |
| [基础层设计](docs/specs/2026-09-25-foundation-design.md) | 运行契约、工具环境与执行器 |
| [架构设计](docs/specs/2026-09-26-architectures-benchmark-design.md) | 编排方案与评测协议 |
| [实现记录](docs/specs/2026-10-05-architecture-hooks-progress.md) | 架构钩子、引用核查与验证结果 |
| [五种架构实现](docs/specs/2026-10-06-architectures-progress.md) | 规划、压缩、级联的接口与验收 |
| [推理服务说明](scripts/serving/README.md) | SGLang 启动与示例任务 |
| [历史档案](docs/history/) | v2 设计、实验报告与复盘 |

旧版代码保留在 `legacy-agent-v2` 标签，OPD 分支档案使用 `archive/opd-*` 标签。
