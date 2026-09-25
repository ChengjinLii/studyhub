# StudyHub Agent RL v3 数据与 Reward 校准记录

状态：`STATIC_DATA_AND_CONTROLLED_REWARD_CALIBRATION_PASSED`。本记录只覆盖离线数据、环境、Reward 与程序化校准；未启动 GPU、GRPO 或 policy learnability rollout。

## 数据集

| 项目 | 结果 |
|---|---:|
| Candidate | 16,000 |
| Post-QA | 10,000 |
| Train / Validation / Protocol holdout | 8,000 / 1,000 / 1,000 |
| Custom / External | 6,000 / 4,000 |
| Unique source groups | 10,000 |
| Split group overlap | 0 |
| Exact goal duplicates | 0 |
| HF public rows validated | 9,000 |

定制数据来自确定性训练模拟器，不是线上行为轨迹。HF DatasetDict 只包含 8,000 条 train 和 1,000 条 validation public task；1,000 条 protocol holdout、verifier 与 solvability witness 均未进入训练传输层。

## Solvability QA

16,000 条候选中，canonical witness 通过 15,378 条、拒绝 622 条；alternative witness 通过 2,940 条、拒绝 20 条。最终 10,000 条只从 canonical 通过且不存在失败 alternative 的任务中选择。

## Reward v3 校准

| 指标 | 结果 |
|---|---:|
| Controlled cases | 800 |
| Strict label accuracy | 100.00% |
| False positive / false negative | 0 / 0 |
| Pairwise accuracy | 96.67% |
| Spearman / Kendall tau-b | 0.9393 / 0.8640 |
| Adversarial hard-gate rate | 100.00% |
| Alternative strict pass | 100.00% |
| Alternative p95 reward delta | 0.0000 |
| Normal vs hacking p05 margin | 0.5500 |

校准标签是程序化测试合同，不是 human review 或 teacher semantic review。179 条严格失败案例仍获得正的部分分；它们均未通过 strict success，也没有反超对应正常轨迹，因此保留为后续 GRPO group diagnostics 的重点监控项。

## 当前边界

- Reward calibration uses controlled programmatic labels, not human or independent teacher semantic review.
- Policy learnability rollouts have not run; the 10k set is not yet partitioned by current 9B policy outcome variance.
- The 6000 custom rows are deterministic training simulations, not production traffic or real user trajectories.
- 179 expected-reject cases receive positive partial credit, but none passes strict success or outranks its paired normal trajectory.
- QASPER contributes only 44 candidate rows after runtime-SFT source-group isolation; 2Wiki fills the remaining external long-context quota.
- No GRPO, GPU profile, or checkpoint comparison is authorized by this evidence.

下一门禁：`SEPARATE_POLICY_LEARNABILITY_EVAL_REQUIRES_EXPLICIT_GPU_AUTHORIZATION`。
