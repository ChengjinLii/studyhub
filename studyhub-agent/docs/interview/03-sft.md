# StudyHub 的 SFT 学什么，为什么还要 RL？

## 30 秒回答

SFT 先建立稳定的行为先验：对话格式、Tool Call JSON、给定证据下的多跳推理、论文证据回答和中文讲解。它使用 assistant token 上的交叉熵模仿专家轨迹。RL 随后解决“何时搜、搜什么、读什么、何时停止”这类没有唯一专家路径的策略问题。

## 深入解释

当前 4B/9B SFT 数据共 3,000 条，按 source group 切分为 `2,550 train / 300 validation / 150 test`：

| 来源 | 数量 | 训练作用 |
| --- | ---: | --- |
| ToolACE | 300 | 工具协议、参数结构 |
| Hermes Function Calling | 300 | Function Call、JSON、多轮格式 |
| 2WikiMultihopQA | 900 | 给定证据下的多跳组合 |
| QASPER | 600 | 给定论文证据下的 grounded QA |
| COIG Exam | 900 | 中文教育问答与解释 |

2Wiki 和 QASPER 的 SFT 样本不宣称训练了检索策略，因为 supporting evidence 已作为输入提供；真正的 Search→Read policy 在 RL 冻结环境里学习。

4B 配方固定为 Qwen3.5-4B、BF16、LoRA rank/alpha 16、目标层 `o_proj/gate_proj/up_proj/down_proj`、gradient checkpointing、两轮、Adam、cosine LR `2e-5`。B1 和 B3 必须共享同一个 SFT checkpoint，避免重复训练造成额外变量。

## StudyHub 的实验问题

同一规模比较四个逻辑模型：

```text
B0 Base
B1 SFT-only
B2 RL-only
B3 SFT -> RL
```

`B1-B0` 衡量监督冷启动，`B2-B0` 衡量 direct RL，`B3-B1` 衡量 SFT 后 RL 的增量，`B3-B2-B1+B0` 用来观察协同作用。4B 先验证设计，9B 再按同一协议复现 scale effect。

## 可能追问

- SFT 什么时候“够”？不能只看 train loss；要看冻结任务上的格式有效率、工具调用、pass@k、全成功/全失败/mixed group 比例和新增样本的边际收益。
- 为什么用 LoRA？受控实验关心策略差异并受双卡资源约束，LoRA 可降低训练和 checkpoint 成本；它不是“效果一定等同全参”的结论。
- 为什么不直接 RL？Base 可能因格式错误产生大量无效 rollout；RL-only 保留为重要 baseline，用于量化 SFT 初始化的价值。

## 代码与实验依据

- `training/sft/open_bootstrap_driver.py`
- `configs/train/open-sft-qwen35-4b.yaml`
- `scripts/train/run_controlled_sft.sh`
- `datasets/processed/open_sft_bootstrap_v2_qwen35_4b/manifest.json`
- `docs/StudyHub_Open_SFT_Training_Report.html`
- 4B 正式 SFT 结果尚未写入；完成后追加 trial、loss、checkpoint 和 Eval32 对照。
