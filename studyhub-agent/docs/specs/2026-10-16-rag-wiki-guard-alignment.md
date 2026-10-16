# 知识库、增量 Wiki 与双 Guard 实现对照

日期：2026-10-16。本文记录本次实现和验证范围，不作为模型效果报告。

---

## 产品边界

`studyhub-agent` 提供独立文档解析、知识索引、RAG、Wiki 与 Agent；`review-jev` 提供独立审核 API 和命令行。二者不导入网站运行代码，不读取网站环境配置，也不访问网站业务数据库或对象存储。

开发数据为本地显式文件、合成测试样例和单独配置的模型端点。已有网站代码及真实业务不因本次变更而接入这些能力。

---

## WeKnora 源码对照

参考版本：`Tencent/WeKnora@cf7aabeaca98f5b33d2f26efc1713d45c32cd401`。

| WeKnora 参考位置 | 采用的设计 | StudyHub 实现 |
| --- | --- | --- |
| `docreader/parser/pdf_parser.py` | 原生文本页与扫描页分别路由，以图像覆盖率优先识别扫描页；PDFium 进程级锁 | `knowledge/parsing.py`，逐页解析、OCR、页码与源文件摘要 |
| `internal/types/chunk.go` | 文档与父子块关联 | `contracts/knowledge.py`，真实父块实体与子块索引 |
| `internal/application/service/knowledgebase_search_results.go` | 召回后补充父块与上下文，避免孤立片段 | `knowledge/retrieval.py`，子块排序、父块去重、整父块上下文补全 |
| `internal/application/service/knowledgebase_search_fusion.go` | 多路召回后统一融合 | 已有 BM25、向量、RRF、Rerank 流程，并增加可选 Wiki 原文召回 |
| `internal/application/service/wiki_ingest_batch.go` | Map 提取、按 Wiki 身份 Reduce、跨来源更新及撤回 | `knowledge/wiki.py`，Chunk 级缓存、实体和概念聚合、修改与删除处理 |
| `internal/application/service/wiki_ingest_dedup.go` | 规范身份与别名去重 | 按知识库、类型、规范名称和显式别名聚合，保留不同来源声明 |

以上为设计迁移和 Python 适配，不是原样搬运 WeKnora 的完整 Go 服务。没有宣称复现其分布式任务、数据库、前端、全部解析器和 Wiki 编辑体系。原项目许可见 [WeKnora LICENSE](https://github.com/Tencent/WeKnora/blob/cf7aabeaca98f5b33d2f26efc1713d45c32cd401/LICENSE)。

---

## 知识链路

```text
Markdown / TXT / PDF / 图片
             |
       原生文本 / 逐页 OCR
             |
  文档版本 + 页码 + 标题结构
             |
      Parent-Child 分层索引
        /                  \
BM25 + 向量召回       Map 实体与概念抽取
        |                  |
       RRF          Reduce 跨文档聚合
        |                  |
     Rerank           增量 Wiki 快照
        |                  |
        +--- 原文证据召回 ---+
                    |
           RAG / 多步 Agent
```

检索上下文以完整子块为最小引用单位，父块只负责组织与补全，不伪造新的原文。PDF 的页码、源文件摘要和解析器身份参与版本计算；Wiki 来源保存文档、Chunk、版本、页码和原文引句。

Wiki 的 Map 可使用显式配置的模型服务，或明确标记的离线标题摘录基线。Reduce 为确定性聚合：合并同一声明的来源，保留不同声明，不由程序擅自消解来源间的冲突。

新增或变化的 Chunk 重新抽取，未变更记录复用；删除来源时撤回相应贡献。整个更新成功后原子发布快照。Wiki 过期时拒绝继续用于检索，防止旧来源被重新带回。

---

## 双 Guard 链路

| 分支 | Backbone | 评分方式 |
| --- | --- | --- |
| 文字、正文与 OCR | Qwen3Guard-Gen-0.6B | 三个完整候选标签的序列条件对数概率，再进行候选归一化 |
| 图像 | ShieldGemma 2-4B | 原生三项政策分别读取 Yes/No Logits |

分支按实际内容触发；普通图片在 OCR 未检出文字时不调用 Qwen。正文不作为 ShieldGemma 的政策输入。低置信度、原生输出分歧、OCR 或模型不可用时转人工，不再使用 OneJev 4B / 9B 升级。

概率、原始分数、模态、输入 ID、政策、模型版本及校准工件各自保留。规则融合不对两个模型的分数直接求平均。版权声明、许可和参考匹配检查继续独立运行。

---

## 验证入口

| 范围 | 测试入口 |
| --- | --- |
| 真实合成 PDF、逐页 OCR 路由、父块与页码引用 | `tests/knowledge/test_documents.py` |
| Wiki 抽取协议、跨文档聚合、缓存复用、删除撤回、知识范围 | `tests/knowledge/test_wiki.py` |
| 双 Guard 路由、融合、分支异常和类别分歧 | `review-jev/tests/test_review_routing.py` |
| 完整候选评分和 Yes/No 映射 | `review-jev/tests/test_review_guard.py`、`test_review_models.py` |
| OCR 进程、概率校准工件及非法输出 | `review-jev/tests/test_review_scoring.py` |

Qwen 概率评分使用本地真实权重完成冒烟；ShieldGemma 当前权重访问返回 401，已验证适配器、模拟 Logits 与路由，不将其记录为实模通过。没有使用真实网站投稿，也没有宣称完成目标场景准确率或概率校准。

### 本轮验收结果

| 检查 | 结果 |
| --- | --- |
| Agent 全量测试 | **393 项通过，20 项跳过**，覆盖率 **96.38%** |
| 审核 Python 3.12 测试 | **156 项通过，3 项跳过** |
| 审核 Python 3.10 基础依赖环境 | **153 项通过，6 项跳过** |
| 分层与隔离契约 | 三项 Import Linter 契约全部通过 |
| 独立安装 | 两个 wheel 在临时环境安装并从 `/tmp` 运行通过，无需网站或模型推理依赖 |
| Wiki 命令链路 | 两份示例文档首次抽取 5 个 Chunk；再次执行复用全部 5 个缓存，未重复抽取 |
| 真实 OCR | 合成图像和扫描 PDF 使用临时 Tesseract 环境验证通过 |

Wiki 的模型抽取协议使用受控 HTTP 响应验证；实际模型的语义抽取质量仍需单独测试。Agent 跳过项依赖可选模型、tokenizer 或其本地文件。完整审核验证见 [审核验证记录](../../../review-jev/VALIDATION.md)。
