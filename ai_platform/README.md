# AI Platform

`ai_platform/` 用于承载 StudyHub 后续所有 AI 相关能力，和现有 `backend/` 并行存在。

当前约定：

- `backend/` 继续负责现有业务接口、鉴权、状态流转和数据库主写入。
- `ai_platform/` 负责 AI 相关实现，包括预处理、训练、检索、推荐、审核、Agent、评测与在线推理。
- 现阶段只创建目录骨架，不修改已有 `backend/` 代码。

建议分工：

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

后续如果要继续落地，建议优先顺序：

1. `retrieval/`
2. `recommendation/`
3. `moderation/`
4. `agents/`
5. `training/` 与 `evals/`
