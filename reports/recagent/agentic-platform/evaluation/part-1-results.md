# 第一阶段 Agentic Platform 质量门记录

记录日期：2026-07-26

## 结论

第一阶段的实现已具备可重复的离线验收入口：

```bash
bash scripts/research/agentic-smoke.sh
```

该入口只运行 fixture/SQLite 测试，不启动大模型、训练任务、真实 Worker、浏览器或外部检索器。它验证的是运行时、权限、证据和数据契约，不将确定性 fixture 结果误表述为线上模型能力或训练收益。

## 必测场景映射

| 计划场景 | 自动化证据 |
| --- | --- |
| 8+ Turn、暂停、进程重启、Resume | `test_kernel_persists_interrupt_and_resumes_after_sqlite_process_restart` |
| Search Query 改写 | `test_policy_can_rewrite_an_empty_first_query_without_a_hardcoded_retry_path` |
| 多来源冲突与交叉验证 | `test_conflicting_internal_evidence_is_preserved_and_marked_for_cross_validation` |
| PDF 失败可恢复 | `test_unreadable_pdf_is_a_recoverable_observation_that_policy_can_retry` |
| Context Compression 不删证据 | `test_context_compaction_keeps_the_capability_catalog_while_only_compacting_the_view`、`test_context_compression_never_deletes_evidence_from_the_ledger` |
| Admin Pause/Resume 与一次性 Token | `test_resume_token_is_one_time_and_queues_durable_resume_job` |
| Worker Restart | `test_worker_restart_reclaims_stale_proactive_job` |
| Duplicate Event | `test_duplicate_material_event_dispatches_once_and_artifact_is_admin_visible` |
| Redis 镜像故障降级 | `test_redis_checkpoint_mirror_failure_does_not_interrupt_a_durable_run` |
| Invalid Citation | `test_invalid_citation_target_is_rejected_by_citation_validation` |
| Unsupported Claim | `test_unsupported_claim_is_rejected_by_citation_validation` |
| Developer/普通用户越权 | `test_admin_agentic_health_rejects_developer`、`test_admin_agentic_health_rejects_regular_user` |
| Snapshot Replay | `test_same_snapshot_seed_and_actions_replay_to_the_same_state_hash_for_ten_turns` |
| Artifact Version | `test_artifact_versions_increment_and_inline_content_stays_bounded` |
| Transition Token/Mask/Quarantine | `test_transition_sink_preserves_raw_token_ids_and_masks_observations`、`test_corrupted_trajectory_is_quarantined_before_a_fresh_trace_is_written` |

## 当前离线验收信号

| 硬指标 | 当前证据 | 结果边界 |
| --- | --- | --- |
| 管理员边界 | Admin 允许、Developer/普通用户/匿名拒绝的 API 测试 | fixture/API contract 已覆盖；生产访问日志另行审计 |
| Invalid Citation | CitationVerifier 对未知 Evidence ID 返回失败 | deterministic fixture 通过 |
| 8+ Turn 场景 | 持久化/重启测试记录 8 个 transition | deterministic fixture 通过 |
| Checkpoint 恢复 | SQLite process-restart 测试 | deterministic fixture 通过 |
| 双 Resume | Runtime 与 Admin API 的一次性 resume 测试 | deterministic fixture 通过 |
| Transition 必填字段 | 严格 Pydantic schema + golden fingerprint | contract 级覆盖 |
| Replay State Hash | 同 Snapshot + Seed + 10 Actions 的两次 replay hash 完全一致 | fixture 样本为 100%；不替代真实环境统计 |
| 轨迹损坏 | JSONL 损坏后整条轨迹移入 Quarantine | deterministic fixture 通过 |
| Redis 失败 | 可选 Redis mirror 不影响权威 checkpoint/run 结果 | deterministic fixture 通过 |

## 未在第一阶段宣称的结果

- 尚未运行模型训练、SFT、REINFORCE/RLOO、GRPO、GiGPO、TIPS 或 reward 权重比较；
- 尚未以真实线上用户数据计算成功率、越权率、Citation 率或 Replay 统计置信区间；
- 未将 fixture 场景的通过率等同于开放式 Agent 的能力上限。

这些数据将在具有授权的 Snapshot/Simulated 环境和独立训练/评估作业中收集。线上 Runtime 继续只负责可审计调度、权限、预算、幂等和类型化状态边界，不预设业务行动序列。
