# 为什么 Agent 评测不能只看平均 Reward？

## 30 秒回答

平均 Reward 是训练诊断，不是最终结论。它会混合不同任务 family，也可能被 Reward 权重或 shortcut 推高。StudyHub 使用固定 32-task Dev Eval，每题 4 次 rollout，报告 strict success、pass@4、consistent@4、hard-gate rate 和 family slice；B0/B1/B2/B3 必须在相同任务、seed、环境和 verifier 上比较。

## 深入解释

- `strict success`：单条轨迹同时满足任务、工具、证据和引用要求。
- `pass@4`：同一任务 4 条中至少一条 strict success，反映能力上限与探索覆盖。
- `consistent@4`：4 条全部 strict success，反映可靠性。
- `hard-gate rate`：触发安全/协议失败的比例。
- `family slice`：Function Calling、2Wiki search、QASPER grounding 分别统计，避免总体均值掩盖退化。

评测器 fail closed：每个 task 必须恰好 4 条 rollout，否则拒绝产出 `pass@4/consistent@4`。开发评测使用固定 task IDs、request seed、确定性 AReaL sampling 和 SGLang deterministic inference。

## StudyHub 的公平比较

```text
同一 Eval32 v2
同一 4-rollout 协议
同一环境与 verifier hash
同一 max turns/tool calls
同一解析器与模板
```

Eval 当前通过一次 `lr=0` 的 trainer path 触发 evaluator，因此证据包还必须证明 initial/final LoRA hash 完全一致。后续可再实现纯 eval driver，但在此之前不把“lr=0”口头等同于没有变化。

正式结论还需要独立 final test；Eval32 是开发集，反复查看后不能冒充密封测试集。比较差值时使用 paired bootstrap CI，并同时报告逐任务胜负与退化样本。

## 可能追问

- pass@4 高但 consistent@4 低说明什么？模型偶尔能找到正确路径，但策略可靠性或采样稳定性不足。
- Reward 提高、strict success 下降怎么办？优先检查 component 权重、长度、引用 parser、某一 family 过拟合和 verifier shortcut，暂停扩大训练。
- 为什么 deterministic eval 还保留 4 条？四条 request 使用固定但不同 seed，用于稳定重放同一采样集合，而不是四条贪心复制。

## 代码与实验依据

- `scripts/train/evaluate_dev_rollouts.py`
- `datasets/processed/open_agent_rl_dev_eval32_v2/manifest.json`
- `scripts/train/run_controlled_grpo.sh` 的 `eval` 模式
- `scripts/train/build_experiment_evidence.py`
- 当前 v2 Base Eval 完成后追加 summary 与可重复性哈希。
