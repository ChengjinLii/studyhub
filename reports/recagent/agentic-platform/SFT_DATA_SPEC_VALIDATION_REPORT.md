# StudyHub Agent SFT 数据规范验证报告

生成日期：2026-07-31
规范版本：`studyhub.agent.sft.spec.v0`
结论：**结构与安全规范验证通过；样本仍为 silver，不是最终训练金标。**

## 1. 本轮完成内容

本轮生成并验证了：

| 数据集 | 样本数 | Train | Validation | Test |
|---|---:|---:|---:|---:|
| `router_tool_2b` | 500 | 400 | 50 | 50 |
| `grounded_tutor_9b` | 300 | 240 | 30 | 30 |
| 合计 | 800 | 640 | 80 | 80 |

数据生成物位于：

```text
/data/chengjin/studyhub/training_artifacts/studyhub_agent_sft/spec_validation_v0/
```

该目录已加入 `.gitignore`，不会把资料文本、训练样本或后续 checkpoint
提交到 Git。

主要文件：

```text
router_tool_2b.jsonl
grounded_tutor_9b.jsonl
manifest.json
validation_report.json
validation_report.recheck.json
preview_samples.json
```

## 2. 样本构成

### 2B 路由与工具策略

| 任务 | 数量 |
|---|---:|
| 初次检索 | 160 |
| 候选详情核验 | 70 |
| PDF 页级证据读取 | 90 |
| 合成个人记忆读取 | 40 |
| 课程上下文整合 | 60 |
| 检索词改写 | 40 |
| 无需工具的通用回答 | 20 |
| 越权与写操作拒绝 | 20 |

### 9B 证据化讲解

| 任务 | 数量 |
|---|---:|
| 页级解释 | 100 |
| 页级摘要 | 50 |
| 资料推荐 | 50 |
| 资料比较 | 30 |
| 学习计划 | 30 |
| 证据不足回答 | 30 |
| 无依据断言纠正 | 10 |

## 3. 验证结果

独立重验结果：

```text
总样本数                 800
精确重复                 0
结构错误                 0
材料跨 split 泄漏        0
覆盖有效免费资料         133 / 133
排除占位资料             2
覆盖唯一 chunk           293
metadata 引用            720
preview OCR 引用         270
网盘链接或提取码泄漏     0
不允许的工具             0
付费资料引用             0
最终结果                 PASS
```

数据集 SHA-256：

```text
router_tool_2b.jsonl
39cea2d16d375959c2b1ac9516f8df31bdb92c24508107a6916bfebf9ece2128

grounded_tutor_9b.jsonl
0bbfdc64e048848a15bedff6fc1956e2a7bbd69a675b5c1e00b08ef62a320836
```

公开快照原有 135 条免费资料，其中 `material_id=191`（`sample`）和
`material_id=211`（`Another Sample`）属于站点占位数据，人工抽查后已从生成池排除。

校验器会拒绝：

- 不符合 `mode=tools/final` 的输出。
- 不存在或越界的工具参数。
- 付费资料和非冻结快照中的材料。
- 百度网盘 URL、提取码、邮箱和手机号。
- 隐藏思维链标记。
- 同一 `material_id` 跨 train/validation/test。
- Assistant target 与训练消息不一致。

## 4. 教师模型口径

用户指定的教师名称记录为 `gpt-5.6-thinking`。本轮实际方式为：

```text
teacher_runtime: current_codex_session
generation_method: teacher_authored_deterministic_spec_validation
runtime_model_verified: false
```

也就是说，本轮由当前 Codex 会话设计任务分布、策略、答案模板和质量规则，
再基于冻结语料确定性扩展到 800 条。运行环境没有提供可独立验证的精确模型
标识，因此数据卡没有伪造该字段。

本轮没有保存隐藏思维链，只保存用户输入、工具动作、可审计的最终回答和证据引用。

## 5. 当前局限

结构与安全验证已经通过，但不能立即把全部 800 条当作最终训练集：

1. 2B 数据已完成按 8 个任务族分层的 100 条人工抽查，适合做 chat template、
   loss mask、LoRA 和工具 JSON 的冒烟实验；仍不是正式发布所需的人工金标。
2. 9B 页级样本来自公开预览 OCR。虽然已经清除常见水印并加入证据不足回答，
   部分公式、英文和思维导图仍存在 OCR 错字。
3. 9B 样本当前主要验证“引用与克制回答”规范，不代表已经具备高质量题目讲解金标。
4. 所有真实资料引用都来自免费资料；个人上下文是合成的，因此 760 条记录标记为
   `public_synthetic`，40 条纯通用或安全场景标记为 `synthetic`。

## 6. 是否可以进入训练

可以进入的下一步：

- 使用 2B 数据做一次不超过 1 epoch 的 LoRA 管线冒烟测试。
- 验证 Qwen3.5 chat template、assistant-only loss mask 和工具 JSON 解码。
- 比较基础模型与冒烟 checkpoint 的格式有效率。

暂时不应进行：

- 用当前 9B OCR 样本直接做正式长周期 SFT。
- 把本轮 validation/test 当作人工金标发布模型指标。
- 连接生产数据库、真实用户记忆或付费资料生成更多样本。

9B 正式训练前，需要从清晰页面或原始文档重新生成讲解答案，并建立至少
300–500 条人工确认的隐藏评测集。

## 7. 复现命令

```bash
cd /data/chengjin/studyhub

python3 -m ml.agentic_platform.sft.build_validation_dataset
python3 -m ml.agentic_platform.sft.validate_dataset

backend/.venv/bin/ruff check \
  ml/agentic_platform/sft \
  backend/tests/agentic_platform/test_sft_spec_validation.py

backend/.venv/bin/pytest -q \
  backend/tests/agentic_platform/test_sft_spec_validation.py
```
