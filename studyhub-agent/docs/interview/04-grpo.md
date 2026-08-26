# GRPO 的 Group 是什么，怎样判断有学习信号？

## 30 秒回答

对同一个任务采样 4 条轨迹，按组内 Reward 均值和标准差归一化，得到相对 advantage。高于组内平均的行为被增强，低于平均的被抑制。若 4 条轨迹 Reward 完全一样，组内方差为零，这组几乎没有相对学习信号，所以必须监控 zero-variance group rate，而不能只看平均 Reward。

## 深入解释

对任务组 `G` 中第 `i` 条轨迹，简化的 group advantage 为：

```text
A_i = (r_i - mean(r_G)) / (std(r_G) + epsilon)
```

策略更新仍使用 PPO 风格 ratio 与 clip：

```text
ratio_t = exp(log pi_theta(a_t|s_t) - log pi_old(a_t|s_t))
L_clip = min(ratio_t * A_t, clip(ratio_t, 1-eps, 1+eps) * A_t)
```

当前配置 `n_samples=4`、`eps_clip=0.2`、`kl_ctl=0.02`、group reward normalization、token-level ratio rejection，超过 ratio 5 的 token 被 mask。缺 EOS 的截断轨迹把 outcome reward 置零，而不是声称整条轨迹从所有损失项消失。

## StudyHub 的监控

每个 trial 独立保存：

- group mean/std、best-worst gap；
- complete/incomplete/zero-variance groups；
- family slice；
- entropy、KL、ratio、clip fraction、grad norm、LR；
- tool calls、预算错误、Reward components、token 与时长。

`drop_incomplete_group=true`，因为缺少样本的 group 会改变 advantage 语义。Gate 是 1 step/8 tasks/32 trajectories，Smoke 是 10/80/320，Pilot 是 25/200/800；三者分别验证链路、分布和短期趋势。

## 当前实测边界

4B Direct Smoke 已完成 10 次更新、80 个 task、320 条 rollout；Reward 均值约 `0.1292`、标准差约 `0.5035`，zero-variance group rate 为 `0.2875`，LoRA hash 发生变化。这证明链路有非零组内信号并完成更新，不等于证明 holdout 能力提升；v2 Eval32 与 Pilot 正在重新建立可比较结果。

## 可能追问

- GRPO 与 PPO 的主要区别？当前实践中去掉 learned value critic，使用同 prompt 多样本的相对 Reward 构造 advantage，但更新仍保留 PPO 的 ratio、clip、KL 等稳定机制。
- group size 越大越好吗？更大通常改善相对排序估计但线性增加 rollout 成本；还要看 mixed-group 比例和有效 action tokens。
- Reward 上升为什么不够？可能是 hacking、长度偏置或某一 family 过拟合，必须看冻结 Eval32、strict success 和独立切片。

## 代码与实验依据

- `configs/train/open-grpo-qwen35-4b.yaml`
- `scripts/train/summarize_reward_groups.py`
- `scripts/train/build_experiment_evidence.py`
- `artifacts/experiments/direct-smoke-seed-6209-20260826_120243/`
