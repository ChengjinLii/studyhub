# StudyHub Agent 2B 教师隐藏集评测报告

日期：2026-07-31
结论：**LoRA 已证明有效，但隐藏集尚未达到上线门槛；应先做定向数据修复，不做 RL。**

## 1. 评测范围与隔离

本轮由当前 Codex 教师会话设计 300 条全新路由样本，对
`Qwen3.5-2B` 基座与上一轮 LoRA adapter 做离线贪心解码对照。记录中保留了
用户指定的 `gpt-5.6-thinking` 教师标签，但运行时模型身份无法在环境内独立验证，
因此本数据属于 **teacher-reviewed silver eval**，不是人工金标。

- 只使用冻结的公开免费资料快照，不读取付费资料、真实用户记忆或生产数据。
- 未连接生产数据库、StudyHub API 或网站后端。
- 300 条均为 `hidden_test`，`training_eligible=false`，所有消息
  `trainable=false`。
- 数据和预测位于
  `evaluation_artifacts/studyhub_agent/router_teacher_hidden_v1/`，已被 Git 忽略。
- 现有 LLaMA-Factory 导出器会拒绝这套隐藏集，防止误混入 SFT。

可追溯运行记录：

```text
ml/agentic_platform/sft/model_locks/qwen35_2b_teacher_hidden_eval.json
```

## 2. 数据审计

隐藏集覆盖初次检索、候选核验、显式页码、概念证据、学习记忆、课程上下文整合、
空检索恢复、直接回答、权限拒绝、预算耗尽收束和工具观察注入共 11 类任务。

| 检查 | 结果 |
|---|---:|
| 隐藏样本 | 300 |
| 独立免费资料 | 27 |
| 与 2B train 的 material 重叠 | 0 |
| 精确 query / payload / target 重叠 | 0 / 0 / 0 |
| query 相似度均值 / P95 / 最大值 | 0.306 / 0.603 / 0.803 |
| 超过 4096 tokens | 0 / 300 |
| 最大总长度 / target 长度 | 873 / 237 tokens |
| 审计错误 | 0 |

数据 SHA256：
`f122d47057bcb0f9239947ed02bde4cbd5bd73180cd98cf00c03fcb75b1a6009`。

## 3. Base 与 Adapter

| 整体指标 | Base | Adapter | 变化 |
|---|---:|---:|---:|
| 裸 JSON | 78.7% | 95.7% | +17.0 pp |
| 契约有效 | 0.0% | 80.0% | +80.0 pp |
| Mode 正确 | 20.3% | 88.0% | +67.7 pp |
| 工具名正确 | 19.3% | 81.0% | +61.7 pp |
| 参数完全一致 | 19.3% | 32.0% | +12.7 pp |

参数完全一致含有检索词措辞和 `limit` 等可接受变体，只作为保守参考。更有业务意义
的 adapter 分项如下：

| 分项 | Adapter |
|---|---:|
| 需要工具时选择 `tools` | 218 / 230（94.8%） |
| 需要工具时工具名正确 | 196 / 230（85.2%） |
| 需要工具时契约有效 | 186 / 230（80.9%） |
| 检索 `limit` / `filters` 保留 | 64 / 70（91.4%）/ 68 / 70（97.1%） |
| material IDs 精确保留 | 83 / 110（75.5%） |
| 显式页码路由正确 | 35 / 35（100%） |
| 显式 `page_numbers` 保留 | 5 / 35（14.3%） |
| 权限绕过拒绝合规 | 27 / 30（90.0%） |
| 工具观察注入后保持只读 | 20 / 20（100%） |
| 直接回答且不多调工具 | 15 / 20（75.0%） |
| 工具预算耗尽后正确收束 | 0 / 20（0.0%） |
| 课程上下文整合路由 / 完整契约 | 17 / 25（68.0%）/ 0 / 25（0.0%） |

adapter 未生成非白名单工具，未输出网盘链接、提取码或思维链；基座生成了 6 次
非白名单工具。注入组工具名仅有 9/20 与教师目标完全一致，但 20/20 均选择了合法
只读动作，因此安全指标按行为边界计为通过。

## 4. 结论与下一步

上一轮同模板 test 的 100% mode/tool 不能代表泛化能力；本轮隐藏集给出了更可信的
结论：SFT 显著修正了基座模型直接作答和协议失配，但 adapter 仍不可上线。

下一轮应新增 800–1,200 条定向 2B 样本，优先级如下：

1. 强制收束：当 `remaining_tool_calls=0` 时必须输出 `final`，禁止继续调用工具。
2. 页码保真：请求出现明确页码时必须写入 `page_numbers`，不能只塞进 query。
3. 综合上下文：固定 `synthesize_course_context` 的 `course_terms`、`constraints`
   和资料引用结构。
4. 概念证据与候选核验：完整保留用户已选 material IDs，不自行丢弃或替换。
5. 边界拒绝与直接回答：补足 JSON 长度、拒绝措辞和“不需要工具”的负样本。

扩充后用 3 个随机种子重训，并继续只在这套冻结隐藏集上验收。建议门槛为：
裸 JSON ≥99%、契约有效 ≥98%、工具模式 ≥97%、页码保留 ≥95%，权限拒绝与注入
只读均为 100%。达标前不接生产流量，也不启动 RL。

## 5. 复现

```bash
cd /data/chengjin/studyhub

python3 -m ml.agentic_platform.sft.build_teacher_hidden_eval

CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /data/chengjin/LLaMA-Factory/.venv/bin/python \
  -m ml.agentic_platform.sft.evaluate_router \
  --dataset evaluation_artifacts/studyhub_agent/router_teacher_hidden_v1/router_hidden_300.jsonl \
  --splits hidden_test \
  --output-dir evaluation_artifacts/studyhub_agent/router_teacher_hidden_v1/results

CUDA_VISIBLE_DEVICES=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /data/chengjin/LLaMA-Factory/.venv/bin/python \
  -m ml.agentic_platform.sft.evaluate_router \
  --adapter training_artifacts/studyhub_agent_sft/qwen35_2b_lora_smoke \
  --dataset evaluation_artifacts/studyhub_agent/router_teacher_hidden_v1/router_hidden_300.jsonl \
  --splits hidden_test \
  --output-dir evaluation_artifacts/studyhub_agent/router_teacher_hidden_v1/results

python3 -m ml.agentic_platform.sft.analyze_teacher_hidden_eval
```
