# StudyHub 是否真的实现了 BM25、Dense、Hybrid 和 Reranker？

## 30 秒回答

实现过，但位于与生产网站隔离的离线 RAG 实验项目中。它比较 TF-IDF、BM25、BGE-M3、Qwen3-Embedding、FAISS、加权 Hybrid、RRF 和 BGE cross-encoder reranking，并记录 Recall@10、MRR、nDCG@10、MAP、延迟和权限泄漏。当前 Agent RL 的冻结检索环境为了可复现采用简化词法 search，不应把两者混称为同一线上检索器。

## 深入解释

离线项目路径为 `ai_platform/rag_experiments/`，输入只允许本地备份中的免费资料；AST 隔离检查拒绝数据库驱动和生产后端 import。完整比较包括：

- sparse：TF-IDF 字符 n-gram、BM25；
- dense：BGE-M3、Qwen3-Embedding-0.6B；
- ANN：FAISS HNSW、IVFFlat；
- fusion：0.6/0.4 normalized weighted fusion、RRF；
- rerank：BGE-reranker-v2-m3 cross-encoder。

RAG 评测关注“相关内容是否召回”；Agent RL 还关注 query 生成、是否继续搜索、读哪个 source、是否引用和何时停止。Retriever 强并不自动等于 Agent policy 强。

## StudyHub 的边界

- 离线 RAG 代码和结果是真实实现，可用于方法对比。
- 当前 FrozenTaskEnvironment 的 search 是确定性词项打分，用于控制 RL 环境变量，不是 BM25/Dense。
- 生产网站没有因此自动获得 Hybrid RAG；上线需要单独的索引生命周期、权限过滤、延迟和回滚设计。
- RL Pilot 阶段不临时更换 Retriever，否则无法把策略变化与检索器变化分开归因。

## 可能追问

- 为什么 RRF 常比直接加权稳？它融合排名而非依赖不同检索器不可比的原始分数，参数敏感性较低。
- Cross-encoder 放在哪里？先由 sparse/dense 召回较大候选，再联合编码 query-document 对重排较小 Top-N，质量更高但延迟更大。
- 权限过滤应放在何处？候选进入检索与返回之前都要 fail closed；不能依赖 LLM 在答案阶段自行隐藏付费资料。

## 代码与实验依据

- `ai_platform/rag_experiments/README.md`
- `ai_platform/rag_experiments/src/studyhub_rag/`
- `ai_platform/rag_experiments/reports/RAG_EXPERIMENT_REPORT.md`
- `ai_platform/rag_experiments/reports/metrics.csv`
