# 如何证明一次 Agent RL 实验真的发生且可以复核？

## 30 秒回答

每次运行都固定并保存代码 commit、模型 revision、数据与环境 hash、完整 resolved config、seed、启动命令、GPU 时间线、轨迹索引、Reward components、训练指标和 checkpoint hash。完成条件不是进程退出 0，而是证据包通过完整性检查，并能证明 LoRA 在训练时改变、在评测时不改变。

## 深入解释

证据链分四层：

1. 输入：Git commit、dirty state、模型 revision、dataset/environment/verifier manifest。
2. 运行：resolved Hydra config、包版本、GPU/进程采样、日志、session metadata。
3. 行为：task/group/rollout ID、工具轨迹、Reward 分项、错误码、token 统计。
4. 输出：checkpoint、LoRA 前后 SHA、评测 summary、完整性状态。

原始答案不直接复制到公共 Reward 日志，日志保存长度与 SHA；需要诊断时从受控轨迹产物回溯。API key 使用每次运行随机临时值，证据整理后清除或脱敏。

## StudyHub 的完成判定

- Gate/Smoke/Pilot 的 task、rollout 数符合协议；
- 每个 GRPO group 完整，Eval 每题恰好 4 条；
- system prompt marker 每次交互恰好出现一次；
- GPU 峰值未越过保护阈值，未出现 foreign process；
- 训练 run 的 LoRA hash 改变；eval run 的 LoRA hash 不变；
- evidence bundle 标记为 `COMPLETE`；
- 结论引用 artifact 路径，而不是手抄终端数字。

## 可能追问

- 固定 seed 为什么仍可能不完全一致？并发推理、CUDA kernel、请求调度和采样后端都可能引入非确定性，所以 Dev Eval 同时开启 deterministic sampling 与 deterministic SGLang。
- 为什么记录 hash 而不是只记文件名？文件名可覆盖，hash 绑定具体内容和 lineage。
- Git 忽略 artifacts 会不会丢证据？大型产物留在本地受控目录，代码、schema、报告和可重建脚本进 Git；最终重要结果另做带 manifest 的备份。

## 代码与实验依据

- `scripts/train/capture_run_metadata.py`
- `scripts/train/build_experiment_evidence.py`
- `scripts/train/verify_lora_checkpoint.py`
- `scripts/train/redact_trial_secret.py`
- `artifacts/experiments/<trial>/`
- `docs/interview/incidents/2026-08-26-duplicate-training-system-prompt.md`
