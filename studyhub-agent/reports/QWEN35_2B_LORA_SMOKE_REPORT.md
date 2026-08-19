# StudyHub Agent Qwen3.5-2B LoRA 冒烟报告

日期：2026-07-31
结论：**SFT 工程链路与路由学习假设验证通过；当前 adapter 不可直接上线。**

## 1. 范围与隔离

本轮只训练 StudyHub Agent 的路由、只读工具选择和结构化 JSON 输出，不训练
9B 题目讲解能力，不连接生产数据库，不读取付费资料或真实用户记忆，也不修改
网站后端。

- 基座：`Qwen/Qwen3.5-2B`
- 固定 revision：`15852e8c16360a2fea060d615a32b45270f8a8fc`
- 训练框架：`LLaMA-Factory v0.9.5`
- 数据：400 train / 50 validation / 50 test
- 方法：LoRA rank 16，1 epoch，BF16，单张 H100
- 输出：`training_artifacts/studyhub_agent_sft/qwen35_2b_lora_smoke/`

模型、数据、评测输出和 checkpoint 均已被 Git 忽略。可追溯的版本与哈希记录在：

```text
ml/agentic_platform/sft/model_locks/qwen35_2b_lora_smoke_run.json
```

## 2. 训练闸门

| 检查 | 结果 |
|---|---:|
| 2B 分层人工抽查 | 100 条 |
| 有效免费资料覆盖 | 133 / 133 |
| 占位资料排除 | 2 条 |
| 数据精确重复 | 0 |
| material 跨 split 泄漏 | 0 |
| tokenizer 超过 4096 | 0 / 500 |
| 最大序列长度 | 857 tokens |
| assistant target 非正长度 | 0 / 500 |
| LoRA 可训练参数 | 16,819,200 |

训练用时 234.5 秒，train loss 为 `0.2320`，validation token accuracy 为
`0.9925`。后者只反映 teacher-forcing 下的 token 拟合，不作为 Agent 业务验收。

## 3. Base 与 Adapter

评分定义：

- `裸 JSON`：不能有 Markdown 围栏、前后缀或 `<think>`。
- `契约有效`：必需字段、只读工具白名单、参数类型和边界全部通过。
- `Mode`：`tools` / `final` 与目标一致。
- `工具名`：首个工具选择与目标一致。
- `参数完全一致`：整个 arguments JSON 完全一致，是最保守指标。

### Validation（50 条）

| 指标 | Base | Adapter | 变化 |
|---|---:|---:|---:|
| 裸 JSON | 66% | 100% | +34 pp |
| 契约有效 | 0% | 100% | +100 pp |
| Mode | 8% | 100% | +92 pp |
| 工具名 | 8% | 100% | +92 pp |
| 参数完全一致 | 8% | 60% | +52 pp |

### Test（50 条，训练期间未使用）

| 指标 | Base | Adapter | 变化 |
|---|---:|---:|---:|
| 裸 JSON | 66% | 100% | +34 pp |
| 契约有效 | 0% | 100% | +100 pp |
| Mode | 6% | 100% | +94 pp |
| 工具名 | 6% | 100% | +94 pp |
| 参数完全一致 | 6% | 50% | +44 pp |
| 越权请求拒绝（短语检查） | 2/2 | 2/2 | 持平 |

Test 上 adapter 的参数完全一致率按任务拆分：

| 任务 | 完全一致 |
|---|---:|
| 候选详情核验 | 7/7 |
| 合成记忆读取 | 4/4 |
| 课程上下文整合 | 6/6 |
| 初次检索 | 2/16 |
| 页级证据读取 | 2/9 |
| 检索词改写 | 0/4 |

多数检索差异是 `limit=6/7/8`、学校过滤开关或同义词顺序，仍满足只读工具
契约；但页级读取漏掉 `page_numbers` 是真实缺口，下一版数据应重点修正。

## 4. 可以和不可以得出的结论

可以确认：

- 当前 Qwen3.5-2B、chat template、assistant-only loss、LoRA、加载和离线评测链路可用。
- 少量 SFT 能显著纠正基础模型“直接编答案、不调用 StudyHub 工具”的行为。
- adapter 在本轮 100 条 validation/test 上全部输出合法的只读工具契约。

不能确认：

- 不能把 100% 的 mode/tool 结果解释成生产准确率。三个 split 虽无材料泄漏，
  但共享同一套确定性任务模板。
- 参数完全一致的目标中含有任意性较强的 limit 和检索词顺序，既低估模型的可用
  输出，也暴露当前评测指标需要细化。
- 当前数据是 silver spec-validation，不是人工金标；adapter 不能直接上线或继续
  长周期训练。

## 5. 下一步

1. 建立 200–300 条人工改写、模板隔离的隐藏路由测试集，覆盖歧义请求和工具观察。
2. 将参数评分拆为“契约有效、material/page 精确、检索语义相关”，不再要求任意
   limit 和同义词顺序完全一致。
3. 增补显式页码、学校过滤、搜索失败改写等 hard cases，再扩到 1,500–3,000 条
   经抽查的 2B SFT 数据。
4. 用 3 个随机种子复训并比较均值与方差；达到隐藏集门槛后才讨论部署。
5. 现阶段不做 RL。先解决数据独立性和参数标注问题，收益与风险都更确定。

## 6. 复现

```bash
cd /data/chengjin/studyhub

python3 -m ml.agentic_platform.sft.build_validation_dataset
python3 -m ml.agentic_platform.sft.validate_dataset
python3 -m ml.agentic_platform.sft.export_llamafactory

PYTHONPATH=/data/chengjin/studyhub \
  /data/chengjin/LLaMA-Factory/.venv/bin/python \
  -m ml.agentic_platform.sft.inspect_tokenization

CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /data/chengjin/LLaMA-Factory/.venv/bin/llamafactory-cli train \
  ml/agentic_platform/sft/configs/qwen35_2b_lora_smoke.yaml

python3 -m ml.agentic_platform.sft.compare_router_evaluations
```
