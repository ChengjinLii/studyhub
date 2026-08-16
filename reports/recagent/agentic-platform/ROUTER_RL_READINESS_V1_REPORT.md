# StudyHub Router 2B：RL Readiness v1

日期：2026-08-12  
分支：`research/router-rl-readiness-v1`  
基线提交：`aa04b87cf987a5d7eb47c5e23df2b83592957a46`

## 结论

- **离线 RL Pilot：GO。** 双路径开发 Gate 已通过，readiness blockers 为 0。
- **生产上线：NO。** 尚未运行独立 RL 评测和最终封存集，也没有打开生产功能开关。
- 本轮只读取冻结的 300 条开发诊断集和本地模型；未调用生产 API、数据库、OSS 或付费资料。
- `ai_agent_runtime_constraints_enabled` 与动态 Agent 默认仍为关闭，不改变当前网站默认行为。

## 失败分类

诊断集共 300 条，不是“300 条都失败”。约束前 raw 有 174 条至少一个精确项失败，normalized 有 169 条。

| 主失败层 | raw | normalized | 主要归属 |
|---|---:|---:|---|
| `semantic_tool_arguments` | 82 | 69 | 策略学习 |
| `bounded_tool_arguments` | 27 | 28 | 运行时约束 |
| `trusted_reference_arguments` | 19 | 27 | 运行时约束 |
| `deterministic_runtime_boundary` | 16 | 17 | 运行时约束 |
| `output_contract` | 16 | 16 | 运行时约束 |
| `output_syntax` | 14 | 11 | 运行时约束 |
| `routing_policy` | 0 | 1 | 策略学习 |

`semantic_tool_arguments` 包括 query、memory focus、synthesis 参数等语义偏差；`trusted_reference_arguments` 包括候选 ID 和用户明确页码。一个样本可同时涉及运行时和策略问题，明细 artifact 中保留重叠类别、样本 ID、原始/normalized 差异和输入信号，但不导出 prompt 或生成文本。

Taxonomy artifact：`evaluation_artifacts/studyhub_agent/router_v1_7_failure_taxonomy/seed_7703/`

## 约束实现

实现采用**类型化后解码约束投影**，不是声称使用 token-level JSON grammar。模型仍以 greedy decoding 生成原始提案；投影层再产生唯一、可执行、严格 JSON 的只读动作，同时保留 `raw_generated`、`raw_parsed` 和修正原因用于归因。

运行时保证：

- 输出只允许 `tools` 或 `final` 合法 schema，每轮最多发射一个规范化动作。
- 工具只允许五个 StudyHub 只读工具；未知工具、敏感链接和提取码不会进入发射结果。
- `force_final`、轮次/工具/检索预算由程序硬约束，不交给 RL 学习。
- `material_ids` 只能来自可信工具观察；明确页码只能来自当前用户请求。
- limit、filters、max_pages、页码范围和各字符串/list 长度统一收敛到生产 contract。
- observation 含 `untrusted_*` 字段时忽略其指令，并选择可执行的只读续步。
- 讨论“何时搜索”、否定命令和一般性问题不会被关键词规则误触发。

主后端只在已有的 `ai_agent_runtime_constraints_enabled=True` 分支调用该实现；默认值仍为 `False`。离线评测新增两个显式开关：

```bash
STUDYHUB_ROUTER_CONSTRAINED_DECODING=1
STUDYHUB_ROUTER_DETERMINISTIC_ARGUMENTS=1
```

## 开发 Gate

模型：`Qwen3.5-2B` + Router LoRA v1.7，BF16，greedy，`max_new_tokens=1800`。适配器 SHA-256 为 `6d2428abf3686be600509c5dff8fae34bb43076f391d86c90eab9b1971797eb1`；开发集 SHA-256 为 `f122d47057bcb0f9239947ed02bde4cbd5bd73180cd98cf00c03fcb75b1a6009`。

| Gate 指标 | raw 约束前 | raw 约束后 | normalized 约束前 | normalized 约束后 | 阈值 |
|---|---:|---:|---:|---:|---:|
| JSON valid | 95.33% | 100% | 96.33% | 100% | 99% |
| Contract valid | 90.00% | 100% | 91.00% | 100% | 98% |
| Tool-required mode | 88.70% | 100% | 88.26% | 100% | 97% |
| Tool-required name | 87.39% | 95.65% | 86.09% | 95.65% | 95% |
| Force-final | 50.00% | 100% | 65.00% | 100% | 95% |
| Explicit page | 45.71% | 100% | 22.86% | 100% | 95% |
| Material IDs | 73.64% | 100% | 75.45% | 100% | 98% |
| Direct no-tool | 95.00% | 100% | 95.00% | 100% | 95% |
| Synthesis contract | 100% | 100% | 100% | 100% | 90% |
| Permission refusal | 100% | 100% | 100% | 100% | 100% |
| Injection-safe readonly | 0% | 100% | 0% | 100% | 100% |

unsupported-tool 和 sensitive-output 计数在两条路径均为 0。工具名 95.65% 的剩余差异来自 20 条注入诊断标签交替要求 `inspect_materials` / `read_pdf_evidence`，而输入状态没有对应区分信号；约束层统一选择更保守的候选详情核验。它满足安全 Gate，但不能解释为原始模型工具选择达到 100%。

正式 artifact：`evaluation_artifacts/studyhub_agent/router_v1_7_rl_readiness_v1_1800/seed_7703/`

- `gate.json`：raw/normalized 均 `passed=true`。
- `rl_readiness.json`：`ready_for_offline_rl_pilot=true`，blockers 为空。
- `run_manifest.json`：记录模型、适配器、数据和实现文件哈希，以及未访问生产/封存集声明。
- raw 原始生成中 286/300 可严格解析，9 条经恢复、5 条回退；normalized 分别为 289、7、4。

## RL 边界

RL 不奖励 strict JSON、schema、工具白名单、权限拒绝、预算、可信 ID、明确页码和参数范围。这些由运行时保证，否则策略会浪费容量学习格式，且可能通过投机方式获得奖励。

首个离线 RL Pilot 只优化：语义工具选择、空结果 query rewrite、证据获取顺序、继续/停止决策、最终回答的 groundedness 和 utility。奖励应同时记录**模型原始提案分**和**约束后可执行分**，防止约束层掩盖策略退化。

这 300 条开发诊断已用于选规则和 Gate，必须继续保持 `training_export_allowed=false`，不能转成 RL rollout 或偏好训练样本。下一步应从冻结的免费公开语料另建 RL rollout 场景与独立 validation；只有策略、奖励和超参数冻结后，才允许一次性读取最终封存集。

## 复现

```bash
PYTHONPATH=backend:. backend/.venv/bin/python \
  -m ml.agentic_platform.sft.router_failure_taxonomy \
  --raw evaluation_artifacts/studyhub_agent/router_v1_7_contract_exact_1800_diagnostic/seed_7703/raw/adapter_predictions.jsonl \
  --normalized evaluation_artifacts/studyhub_agent/router_v1_7_contract_exact_1800_diagnostic/seed_7703/normalized/adapter_predictions.jsonl \
  --dataset evaluation_artifacts/studyhub_agent/router_teacher_hidden_v1/router_hidden_300.jsonl \
  --output-dir evaluation_artifacts/studyhub_agent/router_v1_7_failure_taxonomy/seed_7703

STUDYHUB_SFT_GPU=1 \
STUDYHUB_ROUTER_CONSTRAINED_DECODING=1 \
STUDYHUB_ROUTER_DETERMINISTIC_ARGUMENTS=1 \
scripts/research/evaluate-router-production-contract.sh \
  training_artifacts/studyhub_agent_sft/qwen35_2b_lora_v1_7_state_transitions_from_v1_6_seed_7703 \
  evaluation_artifacts/studyhub_agent/router_v1_7_rl_readiness_v1_1800/seed_7703 \
  both bf16

PYTHONPATH=backend:. backend/.venv/bin/python \
  -m ml.agentic_platform.sft.gate_router_rl_readiness \
  --root evaluation_artifacts/studyhub_agent/router_v1_7_rl_readiness_v1_1800/seed_7703 \
  --fail-on-not-ready
```
