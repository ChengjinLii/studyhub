# 双卡 Agentic RL 如何控制显存和运行风险？

## 30 秒回答

4B GRPO 在 GPU0 放 AReaL actor/reference 的 FSDP 训练，在 GPU1 放 SGLang rollout；LoRA 只训练约 0.42% 参数，配合 BF16、gradient checkpointing 和 4096-token microbatch。启动前要求每卡至少 76,000 MiB 空闲，运行中超过 68,000 MiB 或发现外来 GPU 进程时，只终止本 trial 的 process group。

## 深入解释

4B 当前训练配方：

- actor：FSDP、BF16、gradient checkpointing；
- reference：与 actor colocate，不建 optimizer；
- rollout：SGLang，GPU1，LoRA hot load；
- trainable LoRA：rank/alpha 16，`o_proj/gate_proj/up_proj/down_proj`；
- actor microbatch：最多 4,096 tokens；
- rollout context：8,192，单次生成最多 1,536；
- 并发 rollout：8，group size：4。

Gate 中实际加载约 45.6 亿总参数，LoRA 可训练参数约 1,894 万。显存不能只按模型权重估算，还要包含 reference、optimizer、gradient、activation、FSDP buffer、SGLang KV cache 和 CUDA reserved memory。

## 安全机制

`guarded_gpu_launch.py` 在启动前拒绝占用中的 GPU，运行中每 5 秒采样显存与进程。它记录 PGID，只清理自己启动的 AReaL/SGLang/Hermes 子进程，不使用全局 kill。每个新模型规模或实质性配方变化必须重新从 Gate 开始。

当前运行使用 H100 PCIE 双卡。已完成的 4B Gate/Smoke 证明这套双卡配置可运行，不证明 9B、更多 GPU 或其他硬件上有相同吞吐和稳定性。

## 可能追问

- 为什么 actor 和 rollout 分卡？训练反向与自回归 KV cache 的资源模式不同，分离后更容易设独立预算并避免峰值叠加。
- 为什么 reference 与 actor colocate？4B 双卡资源下减少额外 GPU 需求；代价是 GPU0 峰值较高，必须由 Gate 实测。
- OOM 后为什么不能直接降低 batch 就继续宣称公平？batch、group 完整性和优化 token 数会改变实验；修复后需记录 recipe 版本并重跑可比 baseline。

## 代码与实验依据

- `scripts/train/guarded_gpu_launch.py`
- `configs/train/open-grpo-qwen35-4b.yaml`
- `configs/train/open-sft-qwen35-4b.yaml`
- `artifacts/areal/launcher_logs/<run>.gpu.csv`
- `artifacts/experiments/<trial>/system/`
