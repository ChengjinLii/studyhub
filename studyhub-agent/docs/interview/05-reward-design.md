# Agent Reward 怎样设计并防止 Reward Hacking？

## 30 秒回答

Reward v2 不把一个模糊总分直接交给 GRPO，而是拆成任务成功、答案、证据、引用、工具质量和效率，并保留每项日志。安全或协议错误采用 hard gate；空回答、缺必要引用、未调用工具最多得 0 分。Verifier 对模型隐藏，gold answer、gold tool sequence 和 gold evidence 不进入 rollout context。

## 深入解释

当前总分为：

```text
0.40 * task_success
+ 0.25 * evidence
+ 0.15 * citation
+ 0.15 * tool_quality
+ 0.05 * efficiency
- violation penalty
```

Function Calling 的 `task_success` 再拆为 `0.70 * call correctness + 0.30 * answer quality`。这修复了“工具调对但不回答仍拿高分”的 shortcut。

以下错误直接把总 Reward 设为 `-1`：非法引用、source 不存在、工具预算耗尽、未知工具和不支持的 capability。空 final、缺引用或完全没调工具虽然不一定是安全错误，但总分不能大于 0。

## 防 Hacking 的四层设计

1. 输入隔离：公开 task 不含 expected answer/call/evidence。
2. 环境约束：不能猜 source 直接读，错误参数不会返回成功 fixture。
3. Reward 约束：答案、过程证据、引用和工具行为同时计分。
4. 独立评测：训练 Reward 上升必须由固定 Eval32 的 strict success、pass@4、consistent@4 验证。

## 当前局限

- 字符串包含与 token F1 对开放式答案仍较粗糙，QASPER 语义等价答案可能被低估。
- `efficiency` 只根据调用数计算，尚未表达“有效 reformulation”和“无效重复搜索”的差异。
- 当前没有人工校准的 learned Reward Model；不能把 Reward v2 当作普遍的教育质量评分器。

这些局限应通过 disagreement bucket、人工抽样和受控 hacking 回归处理，而不是在正式训练中临时改权重。

## 可能追问

- Outcome reward 和 process reward 怎么选？当前以可验证 outcome 为主，证据、引用、工具质量提供轻量过程约束；不对无法可靠验证的 CoT 中间文本强打分。
- Hard gate 会不会太强？只用于明确的环境/权限/协议错误；普通答错仍保留连续分数，避免全部坍缩为同一 Reward。
- 如何发现 hacking？检查 Reward component 背离、训练 Reward 与 holdout 背离、异常短答/长答、无工具高分和代表轨迹。

## 代码与实验依据

- `training/rl/reward_v2.py`
- `training/rl/frozen_environment.py`
- `tests/test_reward_v2.py`
- `artifacts/areal/reward-v2/<scale>/<trial>/reward-v2.jsonl`
- `artifacts/experiments/<trial>/metrics/reward-summary.json`
