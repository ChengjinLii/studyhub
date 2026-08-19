# StudyHub Agent 研究数据发布清单

更新日期：2026-08-12

本清单说明 `research/router-rl-readiness-v1` 分支中随代码提交的 SFT / RL 研究数据，以及不进入 Git 的模型类产物。所有路径均相对于仓库根目录。

## 本次提交

### SFT 数据

- `training_artifacts/studyhub_agent_sft/spec_validation_v0/`
- `training_artifacts/studyhub_agent_sft/router_2b_targeted_v1_1/`
- `training_artifacts/studyhub_agent_sft/router_2b_targeted_v1_2/`
- `training_artifacts/studyhub_agent_sft/router_2b_v1_2_replay/`
- `training_artifacts/studyhub_agent_sft/router_2b_v1_3_state/`
- `training_artifacts/studyhub_agent_sft/router_2b_v1_4_runtime_aligned/`
- `training_artifacts/studyhub_agent_sft/router_2b_v1_5_contract_aligned/`
- `training_artifacts/studyhub_agent_sft/router_2b_v1_6_targeted_remediation/`
- `training_artifacts/studyhub_agent_sft/router_2b_v1_7_state_transitions/`
- `training_artifacts/studyhub_agent_sft/grounded_tutor_9b_v1_0/`
- `training_artifacts/studyhub_agent_sft/run_telemetry/`

这些目录包含数据规范、生成样本、Train / Validation 划分、人工复核记录、LLaMA-Factory 数据配置、训练日志和指标摘要。

### RL 数据

- `training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1/` 中的 JSON、JSONL、CSV、Markdown、YAML、文本日志与哈希文件
- `training_artifacts/studyhub_agent_rl/router_rl_maturity_v2/` 中已冻结的 Train / Validation、数据清单、审计结果、动作空间审计、reference cache、Judge 校准集、reward-hacking 测试集，以及已结束实验的指标和轨迹日志
- `evaluation_artifacts/studyhub_agent/` 中已经完成的 SFT、Pilot、DPO、GRPO 与约束评测结果

### 代码与文档

- `backend/app/services/agent_router_constraint_service.py` 及相关测试
- `ml/agentic_platform/sft/` 中的失败分类、Gate 与 Router 评测改动
- `ml/agentic_platform/rl/` 下的 Pilot、maturity v2、配置和验收代码
- `scripts/research/` 下的离线构建、训练、评测、冻结与报告脚本
- `reports/recagent/agentic-platform/` 下的协议、阶段报告和完整 SFT 报告

## 后续补交

以下数据在当前提交时仍受评测协议约束或仍在写入，待对应阶段完成后以追加提交发布：

- `router_rl_maturity_v2/test.jsonl`：候选冻结后的单次 Test 使用
- `router_rl_maturity_v2/sealed.jsonl`：Test 通过后的单次 Sealed 使用
- `grpo_stability_sweep/` 的在运行 trial、正式五随机种子训练数据、鲁棒性结果和最终 Gate 证据

## 不进入 Git

下列文件属于模型或运行时产物，继续保留在本机：

- 基座模型与合并模型权重：`*.safetensors`、`pytorch_model*`、`model-*.bin`
- LoRA / DPO / GRPO adapter 权重及其 `adapter/` 目录
- checkpoint、`optimizer.pt`、scheduler、随机数状态与训练参数二进制
- 重复的 tokenizer / processor 模型包
- 量化环境、虚拟环境、Python 缓存和 GPU 临时文件

代码中的模型路径是本机训练入口，不代表 Git 仓库包含对应权重。复现实验时需单独准备基座模型与训练生成的 adapter。
