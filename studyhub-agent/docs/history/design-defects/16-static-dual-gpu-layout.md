# Static dual-GPU layout

- **Defect:** v2 permanently assigns one H100 to actor/ref update and one to rollout, causing phase-level idle time and uneven memory use.
- **Discovery:** 4B GPU evidence review.
- **Evidence:** v2 GRPO config uses separate single-GPU actor and SGLang roles; the 4B report records different peak memory footprints.
- **Scope:** 9B stability, throughput, cost and time-to-quality.
- **Why systemic:** scaling model size does not eliminate synchronous phase imbalance and can make one card the memory bottleneck.
- **Competing explanations:** 1+1 may remain fastest after accounting for FSDP/TP communication and offload overhead.
- **Minimal falsification:** equal-budget profile A: 1+1, B: FSDP2/TP2 colocated, and C only if async is supported and informative.
- **Root cause:** the pilot optimized wiring simplicity rather than shared-resource efficiency.
- **Fix:** select the layout using successful rollouts/hour, step time, idle fraction and time-to-quality, not raw utilization.
- **Regression:** every 9B run captures per-GPU memory/utilization and phase timing with framework/commit hashes.
- **Before/after:** static roles -> measured two-card resource pool.
- **Residual risk:** pinned AReaL Qwen3.5 LoRA hot-load may block layout B.
- **Interview 60s:** describe why the highest GPU utilization can still lose end-to-end.
- **Deep dive:** include FSDP/TP communication, KV cache and weight refresh costs.
