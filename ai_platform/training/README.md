# Training

`training/` 预留给 StudyHub 后续模型训练、微调和离线评测实验。

当前阶段刻意不放训练代码，原因是：

- 还没有经过授权和脱敏的真实训练数据。
- 还没有稳定的人工标注集。
- 还没有定义正式上线指标，例如搜索 NDCG、审核准确率、推荐点击率或长期留存。
- 当前 `ai_platform` 仍是隔离原型，不能读取生产数据库或影响线上服务。

未来适合放在这里的内容：

- `datasets/`：脱敏后的训练、验证、测试集。
- `configs/`：模型、特征、训练参数配置。
- `train_reranker.py`：搜索 reranker 训练脚本。
- `train_moderation_classifier.py`：资料审核分类器训练脚本。
- `train_ranking_model.py`：推荐排序模型训练脚本。
- `evaluate_embedding_model.py`：embedding / reranker 离线评测。

正式开始训练前必须满足：

- 数据来源经过明确授权。
- 样本已脱敏，不包含邮箱、手机号、QQ、网盘提取码等敏感字段。
- 有可复现的数据版本和评测脚本。
- 训练产物不直接覆盖生产排序、审核或搜索逻辑。

当前可先使用 `../evals/` 里的 deterministic tests 验证原型行为。
