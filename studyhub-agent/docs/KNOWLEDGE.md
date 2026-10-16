# 独立知识服务配置

日期：2026-10-16。

新知识入口为 `studyhub-knowledge` 或 `python -m studyhub_agent.cli`，安装方法见 [README](../README.md)。下文命令均在 `studyhub-agent/` 执行。

---

## 数据与命令

默认快照为 `.knowledge/corpus.json`，该目录被 Git 忽略。可用 `--corpus` 显式指定另一份独立数据文件。

| 命令 | 用途 |
| --- | --- |
| `index <文件...>` | 导入或更新 Markdown/TXT、PDF 与图片 |
| `delete <文档ID>` | 删除当前知识库内的文档和父子索引 |
| `wiki-build` | 增量抽取并发布实体、概念 Wiki |
| `wiki-search <问题>` | 按知识范围查询 Wiki 及其来源 |
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

Markdown/TXT 单文件上限为 4 MB；PDF 与图片上限为 32 MB。解析后原文上限为 200 万字符，PDF 最多 200 页，每页渲染不超过 1200 万像素。拒绝符号链接、不支持的格式和超过 12000 字符的完整公式、代码或表格保护块。

安装 `.[documents]` 提供 PDFium 和图片依赖，OCR 使用系统 Tesseract 与 `chi_sim+eng` 语言包。`index --ocr-languages eng` 可指定识别语言。PDF 逐页根据图像覆盖率和文本层情况选择原生提取或 OCR；图片占主导时，即使存在文本层也重新识别，避免沿用错误的隐藏 OCR 层。解析失败或扫描页未得到有效文字时，本次导入整体失败，不发布半份文档。

快照是第一阶段的本地单写入者存储；不支持多个进程同时修改同一份快照。后续服务化改用独立存储与任务锁，而非依赖本地 JSON 处理多用户写入。

---

## 增量 Wiki

模型抽取使用显式的 OpenAI 兼容完整端点，不会自动连接任何模型或网站服务：

```bash
studyhub-knowledge --corpus /tmp/studyhub-kb/corpus.json --kb demo \
  wiki-build --output /tmp/studyhub-kb/wiki.json \
  --model-endpoint http://127.0.0.1:30411/v1/chat/completions \
  --model Qwen/Qwen3.5-4B

studyhub-knowledge --corpus /tmp/studyhub-kb/corpus.json --kb demo \
  --wiki /tmp/studyhub-kb/wiki.json wiki-search "正交投影"
```

Map 按 Chunk 生成实体、概念、别名、声明与原文引句；引句必须实际包含在对应 Chunk 中。Reduce 按知识库、类型和规范名称聚合，显式别名可连接同一身份；相同声明合并来源，不同声明分别保留。每项来源包含文档、Chunk、版本及页码。

重复执行同一个 `wiki-build --output ...`，仅重新抽取新增或变化的 Chunk。已删除文档的记录不会进入下一次 Reduce，旧声明或无来源页面随之撤回；抽取器身份变化会使缓存失效。抽取、校验及聚合全部成功后才原子替换 Wiki 快照。

`--extractive` 显式启用离线标题与原文摘录基线，便于无模型验证 Map-Reduce、缓存和更新流程，不代表语义实体抽取已由模型完成。

在 `search` 或 `ask` 前增加全局 `--wiki <文件>`，将 Wiki 匹配的原文 Chunk 加入 RRF 候选，再统一重排和父块补全。Wiki 正文不替代原始证据；RAG 和 Agent 仍引用实际展示的原文 Chunk。知识范围过滤发生在 Wiki 聚合和召回前；过期 Wiki 快照必须重建，不能继续引用删除的来源。

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

正文证据包含 `document_id`、`chunk_id`、`parent_id`、`revision`、`page_start/page_end`、`start/end`、`line_start/line_end` 和标题路径。页码和行号从 1 开始；无分页的 Markdown/TXT 页码为空。字符区间以 Python Unicode 字符计数，不是 UTF-8 字节位置；Markdown 的换行保留原样。PDF 源文件摘要、页码边界与解析器身份参与版本计算。

子块用于 BM25、向量召回、RRF 与重排。排序后按父块去重，补充完整父块内的子块作为 `context`，每一项都有自己的 Chunk 引用；超出输出预算则省略整个父块，不截断后继续冒用原引用。`read <parent_id>` 可读取父块下的全部子块。

`[k_片段标识]` 只证明引用指向本轮模型见到的版本化原文。事实是否被原文支持，需要后续带标注的评测，不由引用正则表达式判断。

程序接口可构造 `KnowledgeScope(knowledge_base_ids=..., document_ids=...)`。文档集合与知识库集合取交集；`document_ids=None` 表示知识库内不限文档，空集合表示没有文档。过滤先于 BM25、向量计算、重排和上下文扩展。模型工具没有修改该范围的参数。

范围是内部执行约束，不是已经完成的账号认证或网络服务授权系统。后续 API 必须从自己的身份系统构造可信范围，不可直接接受未授权的请求参数作为范围。
