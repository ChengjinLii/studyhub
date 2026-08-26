# 当前不能对外宣称的结论

这份清单随实验推进更新。它不是项目缺陷列表，而是控制简历、报告和面试表述的事实边界。

## 模型效果

- 不能宣称 4B SFT、Direct RL 或 SFT→RL 已提高 Eval32，直到对应 checkpoint 和成对评测完成。
- 不能用训练 Reward 上升替代 strict success、pass@4、consistent@4 或 sealed test。
- 不能把 2B Open SFT Pilot 的结果外推到 4B/9B。
- 不能宣称 9B 比 4B 更好；9B 当前只有模型、数据、脚本和配方准备。
- 不能宣称 LoRA 与全参数训练等效；本项目选择 LoRA 是资源和对照实验取舍。

## 算法

- 当前真实主线是 AReaL 的 PPO/GRPO 配方；未实跑的 DAPO、OPD、KDRL、DPO、GSPO、Dr.GRPO、KTO、IPO 等只能按 C/D 级讨论。
- 不能把“借鉴 Search-R1 的多轮检索思想”说成“原样复现并训练了 Search-R1”。
- 不能把 FrozenTaskEnvironment 的词法 search 说成 BM25、Dense 或 Hybrid Retriever。
- 不能把 Reward v2 说成经过大规模人工校准的 Reward Model。

## 数据与评测

- Eval32 v2 是固定开发集，不是密封 final benchmark。
- 开放数据的 license、revision、adapter 和 hash 可证明来源与处理，但不能证明这些数据覆盖所有 StudyHub 用户分布。
- QASPER 的 token-F1/字符串 Reward 存在语义等价误判风险，未完成人工 disagreement 校准前不能声称完全客观。
- 当前 RL 环境是 fixture/frozen corpus；不能外推为生产网络、数据库或真实用户在线 RL 的安全性。

## 系统与规模

- 双 H100 上的 4B Gate/Smoke 只证明当前配方可运行，不证明百卡扩展、9B 稳定性或其他 GPU 的相同吞吐。
- prefix-cache warning 尚未证明影响训练正确性，也未完全根除；不能把“进程成功”写成“所有上游 runtime 行为已验证”。
- 当前 eval 通过一次 `lr=0` trainer path 触发；只有 LoRA 前后 hash 一致时才能认定该次权重未改变。
- 生产网站、数据库、付费资料权限和 OSS 不在训练环境内；不能说 RL 已上线或已验证在线业务收益。

## 故障材料

- 自然出现的事故标为 A，并保留原始 trial 与回归 trial。
- 主动制造的熵坍塌、Reward hacking、OOM、错误 parser 等必须标为 B/CONTROLLED。
- 截图、经验帖和压缩包中的案例只用于生成问题，除非在本项目复现，否则不能讲成亲历事故。
