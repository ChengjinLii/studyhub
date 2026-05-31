# AI Platform

`ai_platform/` 用于承载 StudyHub 后续所有 AI 相关能力。

- `backend/` 继续负责现有业务接口、鉴权、状态流转和数据库主写入。
- `ai_platform/` 负责 AI 相关实现，包括预处理、训练、检索、推荐、审核、Agent、评测与在线推理。

其中：
- `serving/`：在线推理接口、模型调用、embedding、rerank
- `retrieval/`：索引构建、召回、搜索
- `recommendation/`：推荐候选、排序、策略
- `moderation/`：内容审核、规则与模型判定
- `agents/`：题目讲解、题目推荐、学习 Agent
- `preprocessing/`：文档解析、chunk、清洗、特征生成
- `training/`：训练、微调、数据集配置
- `evals/`：离线评测、回归测试、基线对比
- `data/`：样例数据、标注、schema、prompts 资产
- `shared/`：公共配置、client、工具函数
- `scripts/`：开发、启动、批处理脚本

## 当前语义搜索原型

当前目录内提供了一套完全隔离的 embedding / 语义搜索最小验证流程。它只用于本地原型验证，不接入 StudyHub 正式后端、数据库、前端或公网服务。

隔离边界：

- 不修改生产数据库。
- 不读取真实生产数据。
- 不修改现有线上接口。
- 不修改前端搜索入口。
- 不部署到公网业务服务。
- 不需要外部 embedding API key。

当前实现采用更接近真实语义搜索系统的分层结构：

- `data/sample_documents.json`：手写样本文本，覆盖资料、经验分享和求购三类内容。
- `shared/mock_embedding.py`：确定性的本地 mock embedding provider，用哈希特征和少量同义词扩展模拟语义相似度。
- `retrieval/semantic_search.py`：
  - `DenseVectorIndex`：FAISS 风格的内存向量索引，负责 dense embedding top-k 检索。
  - `BM25Index`：稀疏关键词索引，负责传统词法召回。
  - `reciprocal_rank_fusion`：用 RRF 融合 dense 与 sparse 排名，模拟 Qdrant hybrid search 常见做法。
  - `InMemorySemanticSearch`：统一封装 `dense` / `sparse` / `hybrid` 三种检索模式。
- `scripts/semantic_search_demo.py`：命令行 demo。
- `evals/test_semantic_search_demo.py`：最小回归测试。

这仍然不是生产级 embedding 效果，因为当前没有调用真实模型；但代码结构已经把真实系统里常见的 embedding provider、向量索引、关键词索引、混合召回和结果融合边界拆开。后续替换为 OpenAI / 百炼 embedding、FAISS、Qdrant 或 MySQL/pgvector 时，不需要重写上层 demo 和评测入口。

运行示例：

```bash
cd /data/studyhub
python3 ai_platform/scripts/semantic_search_demo.py "通信原理期末怎么复习"
python3 ai_platform/scripts/semantic_search_demo.py "数据结构实验报告" --type request --top-k 3
python3 ai_platform/scripts/semantic_search_demo.py "高数微积分考点" --mode dense
python3 ai_platform/scripts/semantic_search_demo.py "高数微积分考点" --mode sparse
python3 ai_platform/scripts/semantic_search_demo.py "高数微积分考点" --mode hybrid
```

## 当前预处理原型

`preprocessing/` 定义如何把资料、经验分享和求购内容转换成统一 AI 文档，不读取生产数据库。

当前实现：

- `preprocessing/ai_document.py`：
  - `SourceRecord`：隔离样本输入。
  - `AIDocument`：统一 AI 文档输出。
  - `normalize_text`：文本清洗。
  - `redact_contacts`：邮箱、手机号、QQ 等直接联系方式脱敏。
  - `chunk_text`：固定窗口 chunk，支持 overlap。
  - `build_ai_documents`：把资料、经验、求购统一转换成 AI 文档。
- `scripts/preprocessing_demo.py`：基于 `data/sample_documents.json` 的本地转换 demo。

运行示例：

```bash
cd /data/studyhub
python3 ai_platform/scripts/preprocessing_demo.py
python3 ai_platform/scripts/preprocessing_demo.py --chunk-size 120 --overlap 20
```

## 当前 Serving 原型

`serving/` 定义 embedding provider 边界，但当前只提供 mock provider，不接外部 API、不需要密钥、不产生费用。

当前实现：

- `serving/embedding_provider.py`：
  - `EmbeddingProvider`：未来真实 provider 需要实现的接口。
  - `EmbeddingRequest` / `EmbeddingResponse`：批量 embedding 请求和响应结构。
  - `MockServingEmbeddingProvider`：本地确定性 mock provider。
  - `get_mock_embedding_provider`：原型默认 provider 工厂。
- `scripts/embedding_provider_demo.py`：本地 provider demo。

运行示例：

```bash
cd /data/studyhub
python3 ai_platform/scripts/embedding_provider_demo.py
python3 ai_platform/scripts/embedding_provider_demo.py "通信原理" "数据结构" --dimensions 32
```

## 当前 Training 边界

`training/` 当前只放说明文档，不写训练代码。等有明确授权、脱敏后的真实样本和稳定评测指标后，再考虑训练 reranker、审核分类器或推荐排序模型。

详见 `training/README.md`。

测试：

```bash
cd /data/studyhub
.venv/bin/pytest ai_platform/evals
```

后续如果要接真实 embedding API，应优先替换 `shared/mock_embedding.py` 中的 embedding provider，并保持 `retrieval/semantic_search.py` 的输入输出契约稳定。正式接入生产前，需要另行设计索引表、后台重建任务、失败重试、限流、成本统计和数据脱敏策略。

## 参考实现思路

这套原型没有复制第三方代码，但结构参考了主流开源检索系统的公开设计：

- SentenceTransformers：query embedding 与 corpus embedding 做相似度 top-k 检索。
- FAISS：向量先进入 index，再对 query vector 做 kNN search。
- Qdrant hybrid search：dense semantic retrieval 与 sparse/BM25 keyword retrieval 结合，并通过 RRF 或 rerank 得到最终排序。

## 当前资料审核原型

`moderation/` 目录提供了一个完全隔离的资料审核、版权风险和异常内容处理原型。它不接入生产资料表，也不会改变任何线上资料状态。

实现思路：

- `data/sample_moderation_materials.json`：手写资料样本，覆盖正常资料、需要人工复核、高风险版权内容和异常内容。
- `moderation/rule_engine.py`：
  - 使用 `ModerationRule` 描述独立规则。
  - 每条规则包含风险类别、权重、严重级别和命中原因。
  - `RuleBasedModerationEngine` 逐条匹配规则、累计风险分数，并按阈值输出审核动作。
  - 输出动作包括 `APPROVE`、`MANUAL_REVIEW`、`REJECT`、`HIDE`。
- `scripts/moderation_demo.py`：命令行 demo。
- `evals/test_moderation_demo.py`：规则命中和动作映射回归测试。

这个结构参考了 Apache SpamAssassin 一类开源规则评分系统的思路：多个独立规则命中后合并成全局分数，再由阈值决定处理动作。当前只用于本地验证，不是最终线上审核策略。

运行示例：

```bash
cd /data/studyhub
python3 ai_platform/scripts/moderation_demo.py
python3 ai_platform/scripts/moderation_demo.py --material-id material-hide-001
```

## 当前推荐与排序原型

`recommendation/` 目录提供了一个完全隔离的推荐排序原型，用样本数据模拟首页推荐、贡献榜和校园集市排序。

实现思路：

- `data/sample_recommendation_fixture.json`：手写用户、资料、经验内容、集市商品和贡献者样本。
- `recommendation/explainable_ranker.py`：
  - 使用 `RankableItem`、`Contributor`、`UserProfile` 表达候选、贡献者和用户画像。
  - `ExplainableRanker` 先计算可解释特征，再按场景权重求和排序。
  - 首页推荐特征包含兴趣匹配、内容质量、互动热度、新鲜度、风险惩罚和状态惩罚。
  - 集市排序更强调新鲜度、同校/兴趣匹配和商品状态惩罚。
  - 贡献榜综合有效下载、收藏、点赞、求购采纳、评分和违规惩罚。
  - 每个结果都会输出 `components` 和 `reasons`，便于调试排序原因。
- `scripts/recommendation_demo.py`：命令行 demo。
- `evals/test_recommendation_demo.py`：首页、集市和贡献榜排序回归测试。

这个结构参考了 OpenSearch LTR / Metarank / LensKit 一类推荐排序系统的方案思路：先做候选集和特征，再通过场景权重或学习排序模型得到 Top-N，并保留特征解释。当前不训练模型，只用确定性的加权分数跑通原型。

运行示例：

```bash
cd /data/studyhub
python3 ai_platform/scripts/recommendation_demo.py --scenario home
python3 ai_platform/scripts/recommendation_demo.py --scenario market
python3 ai_platform/scripts/recommendation_demo.py --scenario contributors
```

完整测试：

```bash
cd /data/studyhub
.venv/bin/pytest ai_platform/evals
```

## 当前 StudyCopilot v9 闭环原型

`agents/`、`router/`、`serving/rerank_provider.py` 和 `memory/` 现在提供一套完全隔离的 StudyHub AI StudyCopilot v9 最小闭环。

它对应 `/data/markdown/studyhub-optimization-suggestions-v9.md` 中的第一阶段目标：

```text
Query Understanding
  -> SearchRec Hybrid Retrieval
  -> Mock Rerank
  -> GenRec Agent
  -> Memory Candidate Extraction
  -> Offline Evals
```

当前实现：

- `router/query_understanding.py`：本地 mock Router，模拟未来 LLM API 的结构化输出，包含 intent、query rewrite、entities、search tasks 和 suggestions。
- `router/query_understanding.py`：同时提供 `LLMQueryUnderstandingRouter`，可使用 OpenAI-compatible Chat provider，并在 JSON 解析、字段校验或 API 失败时自动回退 mock Router。
- `router/query_suggestion.py`：Query Suggestion 原型，提供 mock 和 LLM-backed 两种实现，过滤联系方式、URL、密钥等不应出现在建议词里的内容。
- `serving/rerank_provider.py`：本地 mock rerank provider，模拟未来 rerank API 的输入输出契约。
- `serving/rerank_provider.py`：同时提供 `ChatRerankProvider`，可用 Chat API 模拟 rerank 输出；必须引用候选 ID，失败或编造 ID 时回退本地 mock rerank。
- `agents/genrec_agent.py`：候选约束的 GenRec Agent，先理解需求，再调用本地 hybrid search，然后 rerank，最后生成推荐理由、学习路径和反馈 hook；如果传入 Chat provider，会尝试使用 LLM 生成最终回答，但必须引用已召回候选 ID，失败或编造 ID 时回退本地生成。
- `memory/user_memory.py`：Hermes 双记忆候选提取原型，只输出 user/platform memory candidates，不写生产用户表。
- `memory/store.py`：隔离 JSON Hermes memory store，支持 upsert、按 scope 查询、删除和清空 scope，用于验证“可查看、可删除”的生产前契约。
- `memory/store.py`：同时支持 `userMemoryEnabled` 偏好开关；关闭后不再写入 user scope 记忆候选，并可清空既有 user scope 记忆。
- `feedback/processor.py`：反馈处理原型，校验 feedback hook、脱敏用户反馈文本，并把反馈转为 memory candidates。
- `tutoring/question_tutor.py`：错题/题目辅导 schema 原型，支持 mock 和 LLM-backed 讲解；LLM 输出必须引用已召回候选 ID，编造 ID 或命中 prompt injection 时自动回退。
- `moderation/llm_advisor.py`：LLM 辅助审核建议原型，只生成 review advice，不自动批准、隐藏或删除内容；LLM 不能降低规则引擎给出的风险动作。
- `memory/llm_summarizer.py`：反馈与 Hermes 记忆总结原型，使用 scope/key allow-list 生成 memory candidates，并过滤联系方式、URL、密钥等敏感值。
- `harness/tool_policy.py`：Engineering Harness 工具白名单，GenRec Agent 的 Router、SearchRec、Rerank、Compose 和 Memory 调用都会被校验并记录。
- `scripts/studycopilot_demo.py`：端到端命令行 demo。
- `scripts/query_understanding_demo.py`：Router 单模块 demo，可通过 `--use-api` 使用环境变量中的真实 Chat provider。
- `scripts/query_suggestion_demo.py`：Query Suggestion 单模块 demo，可通过 `--use-api` 使用环境变量中的真实 Chat provider。
- `scripts/feedback_memory_demo.py`：端到端反馈闭环 demo，把 StudyCopilot 输出、用户反馈和 Hermes memory store 串起来。
- `scripts/question_tutor_demo.py`：错题/题目辅导 demo，可通过 `--use-api` 使用环境变量中的真实 Chat provider。
- `scripts/moderation_advisor_demo.py`：LLM 辅助审核建议 demo，可通过 `--use-api` 使用环境变量中的真实 Chat provider。
- `scripts/memory_summary_demo.py`：反馈总结到 Hermes memory candidates 的 demo，可通过 `--use-api` 使用环境变量中的真实 Chat provider。
- `scripts/v9_shadow_smoke.py`：统一 admin/test shadow smoke runner，串起 Router、Suggestion、StudyCopilot、Tutor、Moderation、Memory 和 rollout gate；默认 mock，可通过 `--use-api` 做样例 API 验证。
- `evaluation/studycopilot_eval.py`：v9 离线验收评测 runner，逐条检查 intent、query rewrite、结构化字段、召回、重排、引用 ID、反馈 hook、记忆候选、隐私输出和 prompt injection security case。
- `scripts/studycopilot_eval.py`：输出机器可读 JSON 评测报告，作为生产灰度前的质量门槛雏形。
- `rollout/gate.py`：生产接入前置门禁，要求离线评测通过，并且灰度开关、回滚、成本监控、隐私策略、人工兜底等配置全部明确。
- `config/rollout_readiness.example.json`：默认阻断生产接入的示例配置，必须显式改为 ready 才允许 admin/test shadow 模式。
- `config/rollout_readiness.admin_shadow.json`：可机器校验的 admin/test shadow 准入配置；它允许隔离影子验证，但仍强制禁用生产数据库写入和公开前端入口。
- `config/rollout_readiness.admin_shadow.md`：对应 shadow 配置的人工审计说明，包括 feature flag、回滚、成本监控、隐私和人工兜底要求。
- `observability/usage_tracker.py`：隔离 JSONL usage tracker，只记录 provider、model、operation、token 数、输入/输出条数和状态，不记录 prompt、输入文本、响应正文或密钥。
- `shared/privacy.py`：模型调用前脱敏工具，Router、Chat rerank 和 GenRec composer 在发给模型前会移除邮箱、手机号、QQ 等直接联系方式。
- `shared/prompt_guard.py`：prompt injection guard，命中“忽略规则、泄露 prompt/API key、绕过权限”等风险时，LLM Router 不调用外部模型，直接回退本地 Router 并输出 warning。
- `evals/test_studycopilot_demo.py`：覆盖 v9 文档中的 5 类验收 query。
- `evals/test_query_understanding.py`：覆盖 LLM Router JSON 解析、字段校验和 fallback。
- `evals/test_query_suggestion.py`：覆盖 Query Suggestion 的 mock 输出、LLM 输出校验、敏感建议过滤和 prompt injection 回退。
- `evals/test_genrec_llm_composer.py`：覆盖 LLM 推荐生成、候选 ID 约束和防编造回退。
- `evals/test_question_tutor.py`：覆盖错题辅导 schema、候选 ID 引用约束和 prompt injection 回退。
- `evals/test_llm_moderation_advisor.py`：覆盖 LLM 审核建议、规则风险下限和 prompt injection 回退。
- `evals/test_llm_memory_summarizer.py`：覆盖反馈总结、memory scope/key allow-list、敏感值过滤和 prompt injection 回退。
- `evals/test_new_api_demos.py`：覆盖 Query Suggestion、Question Tutor、Moderation Advisor 和 Memory Summary 四个新增 demo 的默认 mock 路径。
- `evals/test_tool_policy.py`：覆盖 Agent 工具白名单、未知工具阻断和可审计 tool use records。
- `evals/test_v9_shadow_smoke.py`：覆盖统一 v9 admin/test shadow smoke runner 的隔离边界和闭环输出。
- `evals/test_chat_rerank_provider.py`：覆盖 Chat rerank、候选 ID 校验和 fallback。
- `evals/test_feedback_memory_loop.py`：覆盖反馈脱敏、无效 hook 拒绝、memory upsert/delete 和 selected item id 校验。
- `evals/test_studycopilot_eval.py`：覆盖 v9 五类验收 query 的离线评测报告。
- `evals/test_rollout_gate.py`：覆盖灰度门禁允许、阻断和 failed eval 阻断。
- `evals/test_usage_tracker.py`：覆盖 usage/cost 元数据记录，并验证不会落 prompt、输入文本或 key。
- `evals/test_model_privacy_sanitization.py`：覆盖 Router、Rerank、GenRec 三个模型 prompt 入口的联系方式脱敏。
- `evals/test_prompt_guard.py`：覆盖 prompt injection 风险识别和 LLM Router 不调用 provider 的回退行为。
- `serving/llm_provider.py`：可选 OpenAI-compatible Chat / LLM API provider 边界，只从环境变量读取配置。
- `serving/embedding_provider.py`：除 mock provider 外，也提供可选 OpenAI-compatible `/embeddings` provider，仍只从环境变量读取配置。
- `.env.example`：只保留 base URL 和 model 示例，不包含密钥。
- `scripts/api_smoke_demo.py`：真实 API smoke test 入口，默认只检查配置，不访问外网；必须显式传 `--run-api` 才会使用样例数据调用 provider。

运行示例：

```bash
cd /data/studyhub
python3 ai_platform/scripts/studycopilot_demo.py "我两周后考通信原理，基础一般，想找速成资料和真题解析。"
python3 ai_platform/scripts/studycopilot_demo.py "这道链表题为什么我写错了？"
python3 ai_platform/scripts/query_understanding_demo.py "有没有数据结构实验报告模板？"
python3 ai_platform/scripts/query_suggestion_demo.py "通信原理"
python3 ai_platform/scripts/question_tutor_demo.py "这道链表题为什么我写错了？"
python3 ai_platform/scripts/moderation_advisor_demo.py --material-id material-reject-001
python3 ai_platform/scripts/memory_summary_demo.py --note "真题解析有帮助" --item-id material-001
python3 ai_platform/scripts/v9_shadow_smoke.py
python3 ai_platform/scripts/feedback_memory_demo.py --hook useful --note "计划有帮助"
python3 ai_platform/scripts/feedback_memory_demo.py --disable-user-memory --hook useful --note "只保留平台统计"
python3 ai_platform/scripts/studycopilot_eval.py
python3 ai_platform/scripts/rollout_gate_demo.py
python3 ai_platform/scripts/rollout_gate_demo.py --config ai_platform/config/rollout_readiness.admin_shadow.json
```

隔离边界：

- 不接生产数据库。
- 不修改后端业务接口。
- 不修改前端入口。
- 不调用真实外部 API。
- 不保存真实用户长期记忆。
- 默认 feedback memory demo 只写 `ai_platform/data/demo_hermes_memory.local.json` 本地样例文件；该文件不应作为生产数据来源。
- 不提交任何 API key。

admin/test shadow 准入边界：

- `rollout_readiness.admin_shadow.json` 只表示可以做隔离影子验证，不表示可以公开上线。
- 该配置仍要求 `productionDatabaseWritesDisabled=true`、`frontendEntryDisabled=true` 和 `adminOrTestOnly=true`。
- 公开入口、生产数据写入、用户长期记忆落库和真实前端体验必须另走生产评审。

可选真实 LLM API smoke test 配置：

```bash
export STUDYHUB_LLM_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1"
export STUDYHUB_LLM_MODEL="mimo-v2.5-pro"
export STUDYHUB_LLM_API_KEY="..."
export STUDYHUB_EMBEDDING_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1"
export STUDYHUB_EMBEDDING_MODEL="..."
export STUDYHUB_EMBEDDING_API_KEY="..."
export STUDYHUB_USAGE_LOG_PATH="/data/studyhub/ai_platform/logs/usage.local.jsonl"
python3 ai_platform/scripts/query_understanding_demo.py --use-api "我两周后考通信原理，基础一般，想找速成资料和真题解析。"
python3 ai_platform/scripts/studycopilot_demo.py --use-api "我两周后考通信原理，基础一般，想找速成资料和真题解析。"
python3 ai_platform/scripts/api_smoke_demo.py --run-api
```

当前自动化测试不会强制访问外网；有环境变量后可以通过 `api_smoke_demo.py --run-api`、`query_understanding_demo.py --use-api` 或 `studycopilot_demo.py --use-api` 启用真实 provider。真实 smoke test 只使用样例 query 和样例文本，不打印完整 prompt，不打印密钥。密钥只能通过环境变量传入，不写入仓库。
