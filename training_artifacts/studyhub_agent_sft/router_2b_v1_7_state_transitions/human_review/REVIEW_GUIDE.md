# StudyHub SFT 人工复核指南

本复核包只用于离线 SFT 数据验收，不连接生产数据库、API 或 OSS。

逐行检查：用户问题与当前状态是否匹配；`mode` 和工具是否是唯一合理下一步；参数中的 `material_id`、页码与观察是否一致；最终回答是否严格受证据约束；是否拒绝越权且能安全继续只读任务；输出是否为单个合法 JSON。

填写规则：`human_review_status` 只能是 `approved`、`rejected` 或 `needs_revision`；`human_correctness` 填 `yes/no`；`human_safety` 填 `pass/fail`；同时填写 reviewer 和 ISO 8601 格式的 reviewed_at。任何拒绝或待修订项都不能计为 human gold。

完成后运行：

```bash
backend/.venv/bin/python -m ml.agentic_platform.sft.build_human_review_packet validate \
  --review-csv <artifact_dir>/human_review/validation_review.csv
```
