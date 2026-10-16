<div align="center">

# StudyHub 知识库与 Agent

**从文档入库、正文检索到有据可查的知识问答**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](#快速开始)
[![RAG](https://img.shields.io/badge/Retrieval-BM25_%2B_Vector_%2B_RRF-0f766e)](#知识检索)
[![Qwen](https://img.shields.io/badge/Agent-Qwen3.5--4B_%2F_9B-2563eb)](#模型问答)
[![Pydantic](https://img.shields.io/badge/Contracts-Pydantic-E92063)](#运行记录)

[能力概览](#能力概览) | [快速开始](#快速开始) | [知识检索](#知识检索) | [增量 Wiki](#增量-wiki) | [模型问答](#模型问答) | [开发文档](#开发文档)

</div>

StudyHub 知识库与 Agent 是独立运行的文档知识产品，支持本地文档管理、正文检索、RAG 问答与多步 Agent。知识处理和工具设计参考 Tencent WeKnora，执行层沿用统一的运行契约、模型客户端与轨迹记录。

**先找到原文，再阅读上下文，让回答与来源对应。**

---

## 能力概览

| 能力 | 实现 |
| --- | --- |
| 文档解析 | Markdown/TXT、PDF 原生文本与扫描页面 OCR、图片 OCR，逐页记录来源 |
| 分层索引 | 结构感知切分、标题路径、公式与表格保护、Parent-Child 父子块及上下文补全 |
| 正文检索 | 中文与英文关键词召回，可配置向量召回、RRF 融合和模型重排 |
| 知识范围 | 按知识库与文档集合限制检索、阅读和模型输入 |
| 来源定位 | 文档、Chunk、版本、页码、字符区间、行号和独立引用 |
| 增量 Wiki | Map 抽取实体与概念，Reduce 跨文档聚合，缓存复用与删除撤回 |
| RAG 问答 | 固定检索与生成流程，检查 token 预算和片段引用 |
| Agent | 自主检索、分页阅读、邻域扩展及引用纠正 |
| 运行记录 | 保存语料指纹、模型身份、工具证据、预算与终止原因 |

---

## 系统架构

```text
本地文档 -> PDF/OCR 解析 -> Parent-Child 分层索引
                               /              \
                     混合检索与重排       Map-Reduce 增量 Wiki
                               \              /
                           版本化知识快照
                            |
                    统一检索与证据服务
                      /           \
                 固定 RAG       多步 Agent
                      \           /
                      引用与运行记录
```

RAG 和 Agent 共用知识服务。检索负责召回、融合和排序；Agent 决定何时查找、补读和回答。

---

## 快速开始

在 `studyhub-agent/` 目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,tokenizers,documents]"
```

### 导入示例文档

```bash
.venv/bin/studyhub-knowledge \
  --corpus /tmp/studyhub-knowledge/corpus.json \
  --kb demo \
  index examples/knowledge/*.md
```

示例文档为合成的向量投影与最小二乘笔记。

### 检索正文

```bash
.venv/bin/studyhub-knowledge \
  --corpus /tmp/studyhub-knowledge/corpus.json \
  --kb demo \
  search "最小二乘与正交投影有什么关系"
```

### 浏览和阅读

```bash
.venv/bin/studyhub-knowledge \
  --corpus /tmp/studyhub-knowledge/corpus.json list

# 将检索结果中的 chunk_id 传给 read，读取该片段及相邻内容。
.venv/bin/studyhub-knowledge \
  --corpus /tmp/studyhub-knowledge/corpus.json \
  read <chunk_id> --context 1
```

所有命令也可通过 `python -m studyhub_agent.cli` 运行。参数说明与模型协议见 [知识服务配置](docs/KNOWLEDGE.md)。

---

## 知识检索

| 模式 | 行为 |
| --- | --- |
| `keyword` | 对正文和标题路径进行关键词检索 |
| `semantic` | 使用显式配置的 embedding 服务检索语义相近片段 |
| `hybrid` | 分别召回关键词与向量候选，再用 RRF 按排名融合 |

可附加 rerank 服务，对候选重新排序。未配置 embedding 时，hybrid 返回明确的关键词降级标记；显式 semantic 需要配置 embedding 服务。

检索以子块召回和重排，再补全同一父块内的上下文；每个补充片段仍保留独立引用。PDF 证据包含页码，更新文档后旧版本片段与父块一并替换。

### Agent 工具

| 工具 | 用途 |
| --- | --- |
| `search_knowledge` | 查找相关正文片段 |
| `read_document` | 文档分页阅读或片段邻域扩展 |
| `list_documents` | 按标题浏览文档目录 |

工具共用调用方确定的知识范围。标题与元数据不计为已读正文；邻近片段各自保留引用。

---

## 增量 Wiki

Wiki 按 Chunk 抽取实体与概念，再按知识库和规范名称聚合。相同声明合并来源，不同声明分别保留；文档修改或删除后，旧贡献会撤回。未变更 Chunk 直接复用抽取缓存。

```bash
.venv/bin/studyhub-knowledge --corpus /tmp/studyhub-knowledge/corpus.json \
  wiki-build --output /tmp/studyhub-knowledge/wiki.json \
  --model-endpoint http://127.0.0.1:30411/v1/chat/completions \
  --model Qwen/Qwen3.5-4B

.venv/bin/studyhub-knowledge --corpus /tmp/studyhub-knowledge/corpus.json \
  --wiki /tmp/studyhub-knowledge/wiki.json wiki-search "正交投影"
```

对同一输出再次执行 `wiki-build` 即进行增量更新。给 `search` 或 `ask` 增加全局 `--wiki` 参数，可启用 Wiki 来源召回通道；回答仍引用原文 Chunk。离线标题抽取基线使用 `--extractive`，不依赖模型服务。

---

## 模型问答

分别通过 `rag` 和 `agent` 选择固定知识问答与多步工具调用：

```bash
.venv/bin/studyhub-knowledge \
  --corpus /tmp/studyhub-knowledge/corpus.json \
  --kb demo \
  ask "最小二乘与正交投影有什么关系？" \
  --mode rag \
  --model-url http://127.0.0.1:30411 \
  --model Qwen/Qwen3.5-4B \
  --model-dir /path/to/Qwen3.5-4B
```

将 `--mode rag` 改为 `--mode agent`，即可由 Agent 自行检索和阅读。模型地址使用服务根地址，模型目录用于加载真实 tokenizer 和检查上下文预算。

本地模型服务配置参考 [推理服务说明](scripts/serving/README.md)。

---

## 运行记录

片段引用格式为 `[k_片段标识]`。引用标识与文档版本及原文范围绑定，RAG 与 Agent 都检查引用是否属于实际展示的证据。

Agent 共用 `EpisodeRunner`，记录消息、工具输入输出、引用检查、预算、模型信息与终止原因。检索记录包含知识快照指纹、有效检索模式和模型身份。

历史五种编排架构与冻结快照环境保留在研究和回归入口中，说明见 [架构实现记录](docs/specs/2026-10-06-architectures-progress.md)。

---

## 开发检查

```bash
.venv/bin/ruff check src tests scripts/smoke_episodes.py
.venv/bin/lint-imports --config .importlinter
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/pytest --cov
```

---

## 开发文档

| 文档 | 内容 |
| --- | --- |
| [知识服务配置](docs/KNOWLEDGE.md) | 命令、数据格式和模型协议 |
| [源码对照与验收](docs/specs/2026-10-16-rag-wiki-guard-alignment.md) | WeKnora 对照、解析、分层索引与 Wiki 验证 |
| [独立产品设计](docs/specs/2026-10-16-independent-knowledge-design.md) | WeKnora 源码对照、替换关系与分层设计 |
| [开发路线](docs/ROADMAP.md) | 阶段安排和后续验收 |
| [运行契约](docs/specs/2026-09-25-foundation-design.md) | 消息、工具协议、任务轨迹和预算 |
| [历史架构实现](docs/specs/2026-10-06-architectures-progress.md) | 五种编排方案及离线验收 |
| [历史档案](docs/history/) | v2 设计、实验报告与复盘 |
