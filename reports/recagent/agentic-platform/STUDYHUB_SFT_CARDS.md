# StudyHub Agent SFT 数据卡、模型卡与复现清单

更新时间：2026-08-11
状态：离线研究候选，未接入生产

## 1. 任务卡

本轮 SFT 分为两条相互隔离的任务线：

| 任务线 | 基础模型 | 目标 | 生产状态 |
|---|---|---|---|
| Router 2B | Qwen3.5-2B | 在 `tools` / `final` 间路由，选择只读工具并保持参数、ID、页码和安全边界 | Gate 未完成前保持关闭 |
| Grounded Tutor 9B | Qwen3.5-9B | 基于免费资料的元数据和页级证据，生成带引用的讲解、总结、比较和学习计划 | 封存集 Gate 未通过，保持关闭 |

共同边界：不访问生产数据库、生产 API、OSS 写接口或付费资料；不训练购买、下载、改价、审核或其他写操作。

## 2. 数据卡

### Router 2B v1.7

- 数据版本：`router_2b_v1_7_state_transitions`
- 标签等级：教师审校 Silver，`human_gold=false`
- 总量：1,640；训练 1,476；验证 164；无训练可用测试样本
- 运行时路径：raw 820 / runtime_state 820
- 资料范围：119 个免费资料、302 个公开证据 chunk
- 数据类别：public_synthetic 1,520 / synthetic 120
- 主要任务族：概念证据读取、个人记忆、提示注入恢复、强制收尾、显式页码、搜索、拒绝越权和旧能力 Replay
- 数据 SHA-256：`89ac4ffda706693cd5ec59b1f9b46938324ec511970d2fb19956189160e3eb14`
- 审计 SHA-256：`5133cf4bf5672c372137566ddb601f0a7632f3c5063de080a8a8d2c9f3b1e9e6`
- 生产提示 SHA-256：`181dcc551c24484ed9ca1c9e20882589ba9497c9a5c584786ae123e01a4f8a93`
- Token：总长度均值 1,375.52、P95 1,549、最大 1,731；target 均值 125.98、最大 292
- 截断：0；空 target：0；重复对：0
- 泄漏审计：与 300 条开发诊断集的 query、payload、target 精确重叠均为 0；封存测试集未读取

注意：v1.7 包含 439 条旧 target Replay，这是有意的防遗忘设计，不是开发诊断集泄漏。

### Grounded Tutor 9B v1.0

- 数据版本：`grounded_tutor_9b_v1_0`
- 标签等级：教师审校 Silver，`human_gold=false`
- 证据源：69 个免费资料、223 个清洗页；数据集使用 62 个资料和 244 个 chunk
- 训练/验证：960 / 120，按 material 隔离为 55 / 7 个资料
- 封存测试：120 条、7 个独立资料；只允许一次评测，禁止回流训练
- 任务族：页级讲解、页级摘要、主动回忆、带证据学习计划、资料比较、引用保真、证据不足、纠错和不可信观察
- 数据 SHA-256：`85f5f211b913991beffbfea88daf45c4cf3291c5cf802d5b2d49ddb6befca0e4`
- 清洗 chunk SHA-256：`26a0cf8878b69b912988700a8ec02c6e2151bab55783bc830cf4fe766f549227`
- System Prompt SHA-256：`5831319b198c6d2e2e22c6f4da58793e47850a8966d4ef7f05252f71f7198e27`
- Token：总长度均值 1,324.37、P95 1,754、最大 2,233；target 均值 312.92、最大 551
- 截断：0；空 target：0；重复对：0；material split 泄漏：0

## 3. 模型卡

### Router 2B v1.7 LoRA

- 基础模型：本地 Qwen3.5-2B，Apache-2.0；revision `15852e8c16360a2fea060d615a32b45270f8a8fc`；合并后参数量 2,213,241,664
- 本轮是 BF16 LoRA，不是 QLoRA；NF4 只用于合并模型的推理对照
- 训练策略：在 v1.6 adapter 上继续训练；LoRA rank 16、alpha 32、dropout 0.05、target `all`
- 监督方式：自回归 token cross-entropy，`train_on_prompt=false`，只监督 assistant target
- 模板：`qwen3_5_nothink`，`enable_thinking=false`；cutoff 4,096；不 packing
- 训练：1 epoch，LR `5e-6`，cosine，warmup 10，micro batch 2，gradient accumulation 4，有效 batch 8，BF16，gradient checkpointing，seed 7703
- 优化器：AdamW Torch，beta `(0.9, 0.999)`，epsilon `1e-8`，weight decay 0，max grad norm 1.0，label smoothing 0
- 训练结果：train loss 0.070454；validation loss 0.043721；token accuracy 0.989516
- 最低 validation loss：step 184 的 0.043601；最终 step 185 为 0.043721
- 训练耗时：1,417 秒；峰值显存 76,588 MiB；平均显存 59,284.845 MiB；平均 GPU 利用率 63.48%
- Adapter SHA-256：`6d2428abf3686be600509c5dff8fae34bb43076f391d86c90eab9b1971797eb1`
- 合并模型 SHA-256（文件清单聚合）：`070320668fc72f8979a0797135435fc7448c9cd673d4b42169f835f09c035e97`
- 结论：训练 loss 不是上线标准；必须以 raw 与 runtime_state 两条生成式 Gate 共同判定

### Grounded Tutor 9B v1.0 LoRA

- 基础模型：本地 Qwen3.5-9B，Apache-2.0；revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`；模型参数 9,453,092,080
- 本轮是 BF16 LoRA，不是 QLoRA；未进行 4-bit 反向传播训练
- LoRA：rank 16、alpha 32、dropout 0.05、target `all`
- 可训练参数：43,278,336，占 0.4578%
- 监督方式：自回归 token cross-entropy，assistant-only loss
- 模板：`qwen3_5_nothink`；cutoff 4,096；不 packing
- 训练：1 epoch，LR `8e-5`，cosine，warmup 6，micro batch 1，gradient accumulation 8，有效 batch 8，BF16，gradient checkpointing，seed 6209
- 优化器：AdamW Torch，beta `(0.9, 0.999)`，epsilon `1e-8`，weight decay 0，max grad norm 1.0，label smoothing 0
- 训练结果：train loss 0.221934；validation loss 0.186394；token accuracy 0.945196
- 训练耗时：2,469 秒；峰值显存 50,544 MiB；平均显存 43,229.319 MiB；平均 GPU 利用率 61.579%
- Adapter SHA-256：`d5f1b1cca2386cfa62b8f010c9b9c9cdc0055eb7c9c08e8672ec818eaef46c1a`
- 合并模型 SHA-256（文件清单聚合）：`da7b7887487d8799c019a65f59db20f7d41c64336b5ba0f90660cfaba1d5d7a5`

生成式结果：

| 形态 | 验证严格通过 | 峰值显存 | 生成吞吐 | Gate |
|---|---:|---:|---:|---|
| Base BF16 | 4/120（3.33%） | 21,232.6 MiB | 152.46 token/s | 失败 |
| LoRA BF16 | 120/120（100%） | 21,399 MiB | 86.49 token/s | 通过 |
| Merged BF16 | 120/120（100%） | 21,232.6 MiB | 139.98 token/s | 通过 |
| Merged NF4 | 116/120（96.67%） | 10,800.9 MiB | 80.86 token/s | 失败 |

一次性封存集：119/120（99.17%）。唯一失败样本在 768-token 解码上限处被截断，导致 JSON 未闭合；零容忍 `no_tool_actions=1.0` Gate 因此失败。封存结果不得用于继续调参或重训。

## 4. 发布边界

- Router 2B 只有开发诊断 raw 与 runtime_state 均通过后，才允许访问一次性封存集和运行 100 场景离线 Pilot。
- Grounded Tutor 9B 已通过独立验证集，但未通过一次性封存 Gate，因此不进入生产。
- NF4 显存约减半，但出现 4 条严格失败，不能以成本收益覆盖质量退化。
- 生产开关 `ai_agent_runtime_constraints_enabled` 及 provider 默认保持关闭。
- 任何 Shadow、灰度或正式发布都需要新增人工金标、并发/延迟压测、约束解码和明确回滚方案。

## 5. 可复现清单

- 代码分支：`research/agent-sft-completion`
- 基线提交：`aea9fa5f5e738588591f9a42c55619fc2f1c33be`
- 训练框架：LLaMA-Factory commit `7af909522a951e3ad9f022ea6f88b6755257eaa5`
- 环境：Python 3.12.13；PyTorch 2.4.1+cu121；CUDA 12.1；Transformers 5.6.0；PEFT 0.18.1；Datasets 4.0.0；Accelerate 1.11.0；LLaMA-Factory 0.9.5
- 硬件：NVIDIA H100 PCIe 80 GB；主机内存约 503 GiB
- 量化：隔离安装 bitsandbytes 0.50.0，不修改共享训练环境
- 2B 模型锁：config `ed1c1723241f...`、weight index `aca8afed9da7...`、tokenizer config `49e2b6e395f9...`
- 9B 模型锁：config `d0883072e018...`、weight index `26d3539b516b...`、tokenizer config `316230d6a809...`
- 离线约束：`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，并清除数据库和模型服务 endpoint 环境变量
- 数据、审计、adapter、合并模型和运行配置均有 SHA-256；训练配置、GPU 秒级采样、Git 状态和日志保存在忽略目录 `training_artifacts/`

## 6. 已知限制

- 当前所有训练标签均为教师审校 Silver，不是人工金标。
- Router v1.7 只完成单 seed 定向训练；此前 v1.1 做过三 seed，但不能替代 v1.7 的多 seed 稳定性验证。
- 训练遥测记录了 samples/s、显存、GPU 利用率、温度和功耗，但没有直接记录训练 token/s。
- 生成式评测依赖确定性贪心解码；尚未覆盖真实并发、服务排队、故障注入和长会话漂移。
- 2B 的最终开发 Gate、封存 Gate与 Pilot 状态以完成报告中的最终结果为准。
