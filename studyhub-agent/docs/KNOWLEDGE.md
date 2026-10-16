# 独立知识服务配置

日期：2026-10-16。

新知识入口为 `studyhub-knowledge` 或 `python -m studyhub_agent.cli`，安装方法见 [README](../README.md)。下文命令均在 `studyhub-agent/` 执行。

---

## 数据与命令

默认快照为 `.knowledge/corpus.json`，该目录被 Git 忽略。可用 `--corpus` 显式指定另一份独立数据文件。

| 命令 | 用途 |
| --- | --- |
| `index <文件...>` | 导入或更新 Markdown/TXT |
| `search <问题>` | 检索正文，输出结构化来源 |
| `list` | 列出当前知识库中的文档 |
| `read <文档ID或片段ID>` | 分页或扩展阅读 |
| `ask <问题> --mode rag` | 固定检索生成流程 |
| `ask <问题> --mode agent` | 使用三项知识工具的多步问答 |

`--corpus`、`--kb` 和检索模型配置属于全局参数，放在子命令前。`--kb` 默认为 `demo`，只影响本次知识范围，不依赖主站账户。

```bash
studyhub-knowledge --corpus /tmp/studyhub-kb/corpus.json --kb demo \
  index examples/knowledge/*.md

studyhub-knowledge --corpus /tmp/studyhub-kb/corpus.json --kb demo \
  search "投影公式的分母为什么不能为零" --mode keyword --limit 3

studyhub-knowledge --corpus /tmp/studyhub-kb/corpus.json \
  read <document_id> --offset 0 --limit 3

studyhub-knowledge --corpus /tmp/studyhub-kb/corpus.json \
  read <chunk_id> --context 1
```

同一知识库中，同一本地路径决定文档 ID；内容变化会生成新版本及新的片段 ID。不同路径视为不同来源。导入中任意一个文件失败时，本次全部结果都不发布，原快照保留。

当前接收显式 UTF-8 `.md`/`.txt` 文件，单文件不超过 4 MB，原文不超过 200 万字符。拒绝直接导入符号链接、未支持的文件类型和超过 12000 字符的完整公式、代码或表格保护块。未实现 PDF/OCR，不把文件扩展名改成 TXT 作为替代解析方式。

快照是第一阶段的本地单写入者存储；不支持多个进程同时修改同一份快照。后续服务化改用独立存储与任务锁，而非依赖本地 JSON 处理多用户写入。

---

## 检索模型端点

只有提供端点及模型标识后才创建相应 HTTP 客户端。未配置时，本地导入、列表、关键词检索和阅读不访问网络。

```bash
studyhub-knowledge \
  --corpus /tmp/studyhub-kb/corpus.json --kb demo \
  --embedding-endpoint http://127.0.0.1:30421/v1/embeddings \
  --embedding-model <embedding-model-and-revision> \
  --rerank-endpoint http://127.0.0.1:30422/v1/rerank \
  --rerank-model <reranker-model-and-revision> \
  search "如何用几何方法理解最小二乘" --mode hybrid
```

端口仅为命令示例，不会自动启动服务。端点为完整 URL，不替用户推断路径。

### Embedding 协议

请求：

```json
{"model":"embedding@revision","input":["问题或文档片段"]}
```

响应：

```json
{"data":[{"index":0,"embedding":[0.1,0.2,0.3]}]}
```

### Rerank 协议

请求：

```json
{"model":"reranker@revision","query":"问题","documents":["片段一","片段二"]}
```

响应必须返回所有候选的索引和分数，顺序可以不同：

```json
{"results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.2}]}
```

这是当前适配器支持的协议，不表示任意供应商都能直接兼容。特殊协议应增加独立适配器，不能让模型臆造缺失分数。

### 密钥与错误

可通过 `STUDYHUB_KNOWLEDGE_MODEL_API_KEY` 显式提供模型服务密钥。程序不扫描网站 `.env` 文件。端点 URL 不接受内嵌账号密码、查询参数或 fragment；HTTP 客户端不自动使用系统代理环境。

超时、错误响应、重复索引、缺失候选、无效维数、零向量和非有限数值都作为基础设施错误处理。hybrid 仅在“未配置 embedding”时明确降为 keyword；已配置模型运行失败时不会悄悄降级。原始相似度、RRF 和重排分数都不等同于校准置信度。

---

## 生成模型

RAG 与 Agent 复用已有兼容模型客户端，`--model-url` 是不含 `/v1` 的模型根地址；`--model-dir` 指向本地 tokenizer。

```bash
studyhub-knowledge --corpus /tmp/studyhub-kb/corpus.json --kb demo \
  ask "比较两份笔记对正交性的描述" \
  --mode agent \
  --model-url http://127.0.0.1:30411 \
  --model Qwen/Qwen3.5-4B \
  --model-dir /path/to/Qwen3.5-4B
```

`--mode rag` 只生成一次，不运行工具循环。`--mode agent` 使用 `EpisodeRunner` 和 `knowledge_verify`，工具只有 `search_knowledge`、`read_document`、`list_documents`。网站规则、购买和付费权限不进入该工具契约。

没有知识证据时，固定 RAG 返回 `no_evidence`，不请求生成模型。上下文不足返回 `context_budget`。生成不是有效最终文本时返回 `invalid_generation`；引用无效时返回 `unverified` 且 `answer=null`。CLI 对后面三种状态返回退出码 2。

Agent 持续反馈无效引用，达到运行预算后返回相应终止状态和完整轨迹，不将失败引用包装成成功回答。

---

## 来源与范围

正文证据包含 `document_id`、`chunk_id`、`revision`、`start/end`、`line_start/line_end` 和标题路径。字符区间以 Python Unicode 字符计数，不是 UTF-8 字节位置；行号从 1 开始。Markdown 的换行保留原样。

`[k_片段标识]` 只证明引用指向本轮模型见到的版本化原文。事实是否被原文支持，需要后续带标注的评测，不由引用正则表达式判断。

程序接口可构造 `KnowledgeScope(knowledge_base_ids=..., document_ids=...)`。文档集合与知识库集合取交集；`document_ids=None` 表示知识库内不限文档，空集合表示没有文档。过滤先于 BM25、向量计算、重排和上下文扩展。模型工具没有修改该范围的参数。

范围是内部执行约束，不是已经完成的账号认证或网络服务授权系统。后续 API 必须从自己的身份系统构造可信范围，不可直接接受未授权的请求参数作为范围。
