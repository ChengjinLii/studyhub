# StudyHub Agent V2 GPU 训练方案（评审版）

> **历史 v2 方案。** 本文保留用于版本追溯，不再作为当前训练入口。现行方案见
> `StudyHub_9B_Agentic_Post_Training_Program_v3.html`，其主线为 Benchmark v2
> → 9B Base → runtime-native 9B SFT → path-agnostic 9B GRPO。

## 1. 方案基线

本文以以下版本为唯一基线：

| 组件 | 固定版本 |
| --- | --- |
| StudyHub | `acdb2f7c948809f5ef87504bc67cf30e2e3aa338` / `agent-v2-training-ready-v1` |
| Hermes | `5c1a304ce890276a4334d8ced3f29ffeedbbbf93` |
| AReaL | `cbff54d645d2cd8ee1f1c358a82f3f473588433d` |
| Tool Schema | `v1` |
| Trajectory | `studyhub.trajectory.v1` |
| Reward result | `RewardResult v1` 数据结构 |
| Agent smoke benchmark | `StudyHub-AgentBench v1` |

目标是训练一个 4B 的 StudyHub Agent，先完成可复现的 SFT 和 GRPO，再在同一个 SFT checkpoint 上比较 OPD 与 KDRL，最后只把胜出的方案扩展到 9B。

本方案只使用离线资料快照、冻结网页快照和沙箱记忆，不让训练进程连接生产数据库，也不把模型权重、原始资料或训练产物提交到 Git。

## 2. 当前状态

### 2.1 已经具备的部分

- Hermes 是唯一 Agent Harness，StudyHub 通过公开工具注册接口接入 Hermes。
- `TaskSpec`、Tool Schema、Trajectory、RewardResult 和 100 条 AgentBench smoke case 已经冻结。
- 现有 100 条 case 覆盖 `rag_only`、`web_only`、`memory_only`、`rag_memory`、`rag_web`、`rag_web_memory`、`direct_answer`、`insufficient_evidence`、`permission_denied`、`long_horizon` 十类任务。
- 本机有 2 张 NVIDIA H100 PCIe 80GB；本地 `Qwen3.5-2B` 和 `Qwen3.5-9B` 权重分片完整。
- OSS 备份包含 171 条资料元数据，其中 135 条标记为免费；对象备份包含 514 个对象，约 513MB。

### 2.2 还不具备的部分

- `training/areal/` 目前是 StudyHub 自定义 schema、YAML 模板和 fake runner 测试，并不是 AReaL 原生训练入口；当前依赖中也没有 AReaL、SGLang 或 PyTorch 训练栈。
- 当前 OPD 和 KDRL 模板的起点错误，且参数名不是 AReaL 的真实配置语义。
- 备份摘要中的 `materialsWithFile` 为 0。资料对象虽然已经下载，但缺少可靠的 `material_id -> object key -> access level -> checksum` 映射，暂时不能直接作为训练 RAG 语料。
- 100 条 AgentBench case 是规则和接口 smoke test，内容高度模板化，不能用于模型质量结论，也不能作为 RL 训练集。
- 当前 Reward v1 的任务成功主要依赖 `expected_contains`，引用只检查 source ID 是否存在，容易被关键词复制和无效引用钻空子。数据结构可以继续保持 v1，但正式 RL 前必须实现经过校准的 Reward v2 逻辑。
- 本地尚无 `Qwen3.5-4B`；现有 2B 只用于接线测试，不能替代 4B 主实验。
- `studyhub-agent/training_artifacts/` 下保留了约 63GB 的旧版 Router/Tutor 训练产物。这些产物不属于当前 Agent V2 基线，不能混入新实验或当作 V2 对照结果。

因此，当前准确状态是“Contract ready”，不是“Trainer ready”。

## 3. 对原方案的修正

### 3.1 三种后训练方法必须从同一点分叉

```text
Qwen3.5-4B
    |
    v
SFT-4B-v1
    |
    +----------------+----------------+
    |                |                |
    v                v                v
  GRPO              OPD             KDRL
```

`GRPO -> OPD -> KDRL` 的串行训练不能用于算法对比。OPD、KDRL 和 GRPO 必须共享同一个 SFT checkpoint、任务池、环境快照、上下文长度、LoRA 容量和评测集。

### 3.2 Hermes 与 AReaL 的连接方式

AReaL 官方的 Agent 训练路径通过 OpenAI-compatible proxy 记录 token ID、log probability 和 reward。StudyHub 不应只把 Hermes 的 JSONL 轨迹交给 AReaL，因为普通 JSONL 不包含可用于策略梯度的行为策略 logprob。

第一版采用 `subproc` 模式，而不是 `online` 模式：

```text
AReaL PPOTrainer
    |
    | 同一个 TaskSpec，n_samples=4
    v
GroupedRolloutWorkflow
    |
    +--> Hermes subprocess #0 --> AReaL proxy --> SGLang
    +--> Hermes subprocess #1 --> AReaL proxy --> SGLang
    +--> Hermes subprocess #2 --> AReaL proxy --> SGLang
    +--> Hermes subprocess #3 --> AReaL proxy --> SGLang
                  |
                  v
        StudyHub frozen tools/environment
                  |
                  v
             Reward v2
```

选择 `subproc` 的原因是 Hermes 当前使用进程级全局工具注册表。把四条 rollout 放在同一 Python 进程中并发执行，会有工具覆盖、上下文串线和卸载顺序冲突的风险。子进程隔离不要求修改 Hermes 核心，同时仍由 AReaL 管理同组样本、token 轨迹和权重更新。

`online` 模式保留给后续真人反馈或外部 CLI 采样。它当前是实验接口，而且 dataloader 内容不会自动传给外部 Agent；若直接并发驱动，很容易把不同 TaskSpec 的会话错误地归入同一 GRPO group。

### 3.3 OPD 不能使用普通外部 Teacher API 兜底

OPD/KDRL 需要教师对学生已经采样出的每一个 action token 给出精确 logprob。普通 OpenAI/Anthropic chat API 通常不能对指定完整轨迹返回逐 token 教师分数，因此“显存不足就改用外部 Teacher API”不是等价替代。

第一版固定使用本地 `Qwen3.5-9B` Teacher。若双卡共置失败，优先降低并发、KV cache 和上下文，再尝试 teacher offload 或顺序评分；仍无法稳定运行时，应增加第三张 GPU，而不是改变 OPD 定义。

### 3.4 Reward v1 只保留为接口回归

正式 RL 使用 Reward v2，返回值仍兼容 `RewardResult`：

| 分量 | 建议权重 | 计算原则 |
| --- | ---: | --- |
| Task success | 0.40 | exact/regex/结构化 verifier，不使用单一关键词命中代替正确性 |
| Groundedness | 0.25 | claim 必须能映射到本轮实际 observation 中的证据 |
| Citation | 0.15 | 同时检查 source ID、引用范围和 claim-support 关系 |
| Tool quality | 0.10 | schema、参数、顺序、重复调用与必要工具覆盖 |
| Memory correctness | 0.05 | 只奖励与当前用户和时间有效的记忆，惩罚 stale/cross-user memory |
| Efficiency | 0.05 | 仅作轻量正则，不允许压过任务正确性 |

以下情况直接 hard gate 为 `-1`，不能靠其他分量抵消：

- 访问付费但未授权资料；
- 用户身份或个人记忆串线；
- 隐私数据泄漏；
- 伪造、越权或不存在的 source ID；
- 修改只读环境；
- 明确违反任务预算或工具 allowlist。

正式训练前，需要用至少 200 条人工复核样本校准 Reward v2，检查其与人工排序的一致性，并专门构造关键词复制、伪引用、重复搜索和拒答投机样本。

## 4. 训练数据的数据结构

数据不能直接从任意开源对话转成最终 Agent 轨迹。建议保留五层数据：

```text
raw_source_record
    |
    v
normalized_seed
    |
    v
TaskSpec + frozen environment
    |
    v
studyhub.trajectory.v1
    |
    +--> SFT compiler --> input_ids + loss_mask
    |
    +--> RL runtime ----> token IDs + behavior logprobs + rewards
```

### 4.1 SFT loss mask

SFT 采用 causal cross-entropy，但只训练模型自己应该生成的 token：

- `system`、`user`、tool result、retrieved evidence 和 memory observation 的 loss mask 为 0；
- assistant reasoning/action、合法 tool call 和 final answer 的 loss mask 为 1；
- 超过 8K 的轨迹按完整 action/observation 边界切分，不从 JSON tool call 或引用中间截断；
- 每条样本必须能在冻结环境中 replay，不能让教师模型编造 tool observation。

AReaL SFT 的通用本地数据路径要求先保存 Hugging Face Dataset，至少包含 `input_ids` 和 `loss_mask`。现有 `studyhub.trajectory.v1` 不能直接作为 AReaL SFT dataset。

### 4.2 数据去重与切分

- 按 `source_dataset + source_id` 做精确去重；按规范化问题和证据做 MinHash/embedding 近重复检查。
- StudyHub 数据按 material、course 和 task template 分组切分，不能按 trajectory 行随机切分。
- 同一开源问题的改写、翻译和多条教师轨迹必须位于同一 split。
- AgentBench v1、sealed holdout、MCP-Atlas、TeachArena 和 LongMemEval-v2 的题目不得进入训练教师上下文。
- 每条数据记录 `license`、`revision`、`source_url`、`sha256`、`transform_version` 和 attribution。

## 5. 开源数据选择

### 5.1 第一批允许进入训练候选池

| 数据集 | 用途 | 许可证与注意事项 | 第一批用量 |
| --- | --- | --- | ---: |
| [Team-ACE/ToolACE](https://huggingface.co/datasets/Team-ACE/ToolACE) | 中英多轮工具调用、并行 function call | Apache-2.0；11,300 条，先做 schema 和质量过滤 | 1,000-1,500 |
| [NousResearch/hermes-function-calling-v1](https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1) | Hermes tool-call 序列化与 JSON mode | Apache-2.0；只选与当前 Hermes 模板兼容的子集 | 500-1,000 |
| [2WikiMultihopQA](https://github.com/Alab-NII/2wikimultihop) | 多跳检索、query reformulation、证据组合 | Apache-2.0；转换后必须在本地冻结 corpus 中真实检索 | 2,000-4,000 task seeds |
| [MIRACL](https://huggingface.co/datasets/miracl/miracl) | 中文 query/qrels、检索评测与 hard negative | Apache-2.0；主要训练/评测 Retriever 和 query rewrite，不直接当 Agent 对话 | 中文 2,000-3,000 query |
| [allenai/QASPER](https://huggingface.co/datasets/allenai/qasper) | 长文读取、证据定位、引用与证据不足 | CC BY 4.0；保留 attribution | 800-1,500 task seeds |
| [ParticleMedia/RAGTruth](https://github.com/ParticleMedia/RAGTruth) | 幻觉和 groundedness verifier 校准 | MIT；约 17,790 个 RAG response，主要用于 Reward/Eval，不直接模仿低质回答 | 2,000-4,000 校准样本 |
| [BAAI/COIG](https://huggingface.co/datasets/BAAI/COIG) 的 exam 子集 | 中文教育问答、讲解格式 | 顶层标记 Apache-2.0，但内部来源混合；只使用来源明确且通过 allowlist 的 exam 数据 | 1,000-2,000 |

开源数据主要解决通用工具格式、检索推理和中文教学表达，不能取代 StudyHub 原生任务。最终 Agent SFT 中，通用开源数据占比不应超过 30%。

### 5.2 默认只用于外部评测

| 数据集 | 评测能力 | 处理方式 |
| --- | --- | --- |
| [ScaleAI/MCP-Atlas](https://huggingface.co/datasets/ScaleAI/MCP-Atlas) | 500 个真实 MCP 多工具任务，通常 3-6 次调用 | 保留为工具规划外部评测，不训练 |
| [CinderD/TeachArena](https://huggingface.co/datasets/CinderD/TeachArena) | 354 个 tutoring、教学判断和 LMS 工作流任务 | 保留为教学 Agent 外部评测，不训练；保留其 canary |
| [xiaowu0162/longmemeval-v2](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2) | 跨会话记忆、更新、时间与干扰信息 | 保留为记忆外部评测，不训练 |
| [mteb/LongMemEval](https://huggingface.co/datasets/mteb/LongMemEval) | 大规模 memory retrieval | 只评估记忆 Retriever，不作为 Agent SFT 对话 |

若未来决定把其中任一数据用于训练，必须建立新的、来源不重叠的外部评测集，并在报告中标记 benchmark contamination。

### 5.3 暂不进入首轮训练

| 数据集 | 原因 |
| --- | --- |
| [OpenCSG Fineweb-Edu-Chinese V2.2](https://huggingface.co/datasets/opencsg/Fineweb-Edu-Chinese-V2.2) | 数据卡同时出现 Apache-2.0 与 OpenCSG Community License；商业使用要求额外许可，先完成法务确认 |
| [HotpotQA](https://huggingface.co/datasets/hotpotqa/hotpot_qa) | CC BY-SA 4.0；可用于研究对照，但首个产品候选优先使用 Apache-2.0 的 2WikiMultihopQA |
| [Natural Questions](https://ai.google.com/research/NaturalQuestions/download) | 数据为 CC BY-SA 3.0，代码仓库许可证与数据许可证不同；首轮不混入产品候选 |
| [Eedi Question-Anchored Tutoring Dialogues](https://huggingface.co/datasets/Eedi/Question-Anchored-Tutoring-Dialogues-2k) | 非商业许可证，排除产品训练 |
| [Salesforce xLAM function-calling-60k](https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k) | CC BY 4.0 且需要接受访问条件；ToolACE 与 Hermes FC 已足够覆盖第一轮 |

## 6. StudyHub 原生数据构造

### 6.1 先建立可审计语料快照

必须生成 `approved_material_manifest_v1.jsonl`，每行至少包含：

```json
{
  "material_id": "128",
  "object_key": "files/...pdf",
  "sha256": "...",
  "free": true,
  "access_policy": "public_free",
  "title": "...",
  "course": "...",
  "tags": ["..."],
  "mime_type": "application/pdf",
  "snapshot_version": "studyhub-corpus-v1"
}
```

只把 `free=true` 且授权状态明确的资料放入训练/评测语料。重复 object 按 hash 去重，付费资料只保留用于 ACL 负例的虚拟元数据，不把正文放进训练环境。

### 6.2 构建 TaskSpec，而不是只生成问答对

第一版建立 2,400 个可执行 RL TaskSpec：

| Family | 数量 |
| --- | ---: |
| `rag_only` | 600 |
| `rag_memory` | 300 |
| `rag_web` | 300 |
| `rag_web_memory` | 240 |
| `web_only` | 120 |
| `memory_only` | 120 |
| `insufficient_evidence` | 240 |
| `permission_denied` | 240 |
| `long_horizon` | 120 |
| `direct_answer` | 120 |
| 合计 | 2,400 |

每个 TaskSpec 固定：

- environment seed；
- RAG corpus fingerprint 和 index fingerprint；
- Web fixture snapshot；
- personal/collective memory snapshot；
- allowed tools、max steps 和 max tool calls；
- 可执行 verifier；
- gold evidence/source IDs；
- access-policy canary。

### 6.3 教师轨迹

每个 SFT task 生成 2-4 条候选轨迹。教师必须通过 Hermes 和真实沙箱工具执行，不允许直接生成伪造 observation。候选只有满足以下条件才能进入 SFT：

- replay 成功；
- tool schema 与 allowlist 全部合法；
- task success 通过；
- 引用来自本轮真实 observation；
- 无付费资料、隐私和跨用户泄漏；
- Reward v2 达到预设门槛；
- 与已有训练样本不过度近似。

## 7. 数据规模

### 7.1 SFT pilot

先生成 3,000 条 accepted trajectory：

| 数据类型 | 比例 | 数量 |
| --- | ---: | ---: |
| StudyHub 原生 RAG/Agent | 55% | 1,650 |
| 多跳检索与引用转换 | 15% | 450 |
| Tool-call 协议 | 10% | 300 |
| StudyHub 学习记忆任务 | 10% | 300 |
| 教学讲解、拒答与证据不足 | 10% | 300 |

Pilot 通过后扩展到 8,000-12,000 条高质量 accepted trajectory。优先增加 StudyHub 原生覆盖，不按比例无限扩张通用 function-calling 数据。

### 7.2 数据切分

- SFT development：按 material/course/template 分组后的 10%。
- SFT internal test：5%，只在 recipe 冻结后运行。
- RL train/dev：2,000/400 个 TaskSpec；dev 不参与参数更新。
- AgentBench v1：100 条，仅作 contract smoke。
- 新建 sealed holdout：400 条，建议 ID 160、OOD 120、Hard 120。
- 外部评测：MCP-Atlas、TeachArena、LongMemEval-v2，保持零训练污染。

## 8. 模型与实验顺序

### 8.1 模型角色

| 角色 | 模型 | 用途 |
| --- | --- | --- |
| 接线模型 | 本地 `Qwen3.5-2B` | tokenizer、Hermes、AReaL、SGLang、forward/backward 和 checkpoint smoke |
| 主 Student | `Qwen/Qwen3.5-4B` | 4B SFT 与 RL controlled study |
| OPD/KDRL Teacher | 本地 `Qwen3.5-9B` | 逐 token teacher logprob，只做 inference |
| Scale-up Student | `Qwen3.5-9B` | 只复现最终胜出的 recipe |
| 兼容 fallback | 本地 `Qwen3-4B` | Qwen3.5 在固定 AReaL commit 上出现阻塞性问题时使用 |

`Qwen3.5-4B` 与 `Qwen3.5-9B` 的官方权重均采用 Apache-2.0。模型下载后记录 Hugging Face revision 和所有分片 hash。

### 8.2 Compatibility Gate

依次验证：

1. tokenizer 与 chat template；
2. Hermes 单轮 tool call；
3. AReaL 原生 config load；
4. SGLang rollout；
5. 一次完整的四样本 grouped Hermes rollout；
6. action-token loss mask；
7. 一次 forward/backward/optimizer step；
8. LoRA 权重同步到 rollout engine；
9. checkpoint save/reload；
10. reload 后再次完成 tool call；
11. 四条 rollout 的 TaskSpec、environment 和 memory snapshot 完全相同，仅 rollout seed 不同。

2B Gate 全部通过后才下载和启动 4B 主实验。

## 9. SFT 实验

### 9.1 主配置

```text
dtype                  BF16
max sequence length    8192
LoRA rank              16
LoRA alpha             16
target modules         all-linear（先通过 Qwen3.5 compatibility test）
micro batch            1
gradient checkpoint    on
optimizer              AdamW
learning rate          2e-5
weight decay           0.05
warmup                  3%
epochs                  1-2
gradient clipping      1.0
```

首轮实验矩阵：

| ID | 数据 | LoRA | LR | Epoch | 目的 |
| --- | --- | --- | ---: | ---: | --- |
| B0 | 无训练 | - | - | - | Base 4B 基线 |
| S1 | 3K StudyHub-native only | r16/a16 | 2e-5 | 1 | 原生数据基线 |
| S2 | 3K mixed pilot | r16/a16 | 2e-5 | 1 | 检查开源数据增益 |
| S3 | 3K mixed pilot | r16/a16 | 5e-5 | 1 | 学习率对照 |
| S4 | 3K mixed pilot | r32/a32 | S2/S3 最佳 LR | 1 | 容量对照 |
| S5 | 8K-12K v1 | 最佳配置 | 最佳 LR | 1-2 | 正式 SFT candidate |

只对最终两组 recipe 做 3 个 seed，不对明显失败的配置重复消耗 GPU。

### 9.2 SFT 评测

除 train/dev loss 外，必须比较：

- Task success、groundedness、citation accuracy；
- valid tool-call rate、required-tool coverage、duplicate calls；
- insufficient-evidence precision/recall；
- paid-material ACL violation 和 cross-user memory leakage；
- long-horizon success、平均步骤、tokens/success；
- 各 task family 的 bootstrap 95% confidence interval。

进入 RL 的最低条件：

- 相对 Base 4B 的总体 task success 有明确提升，建议至少 +5 个百分点；
- tool validity 不低于 99%；
- sealed safety/permission case 为 0 泄漏；
- groundedness 和 citation 不退化；
- 至少两次重复运行方向一致。

## 10. GRPO、OPD 与 KDRL

### 10.1 GRPO

先在 200 个任务上做 pilot，每个 TaskSpec 采样 4 条轨迹：

```text
n_samples                 4
temperature               0.8
top_p                     0.95
max_new_tokens            2048
max total tokens          8192
LoRA                      与 SFT 相同
actor learning rate       2e-6 / 5e-6 pilot
reward normalization      group
drop incomplete group     true
max head offpolicyness    0（复现 Gate），稳定后最多 1
```

当前自定义 YAML 的 `kl_coefficient` 不能直接视为 AReaL 的 `actor.kl_ctl`。正式配置必须使用 AReaL 原生字段，并记录 reference policy、KL、entropy、clip fraction、group reward std 和有效 action token 数。

只有以下条件满足后才扩展到 1,000-2,000 个任务：

- 大多数 batch 的 group reward 有非零方差；
- 无 NaN、OOM、stale rollout 和 TaskSpec 串组；
- reward 提升能同步转化为独立 evaluator 的 task success；
- reward hacking rate 没有上升；
- 200-task dev 至少出现稳定正向趋势。

### 10.2 OPD

从同一个 `SFT-4B-v1` 开始：

```yaml
teacher:
  engine_type: rollout
  path: /data/chengjin/studyhub/models/P1/Qwen3.5-9B
  rl_loss_weight: 0.0
  distill_loss_weight: 0.005
```

纯 OPD 不使用任务 reward 更新，但仍使用同一 TaskSpec 池和学生 on-policy 轨迹。为公平比较，按实际 sampled action tokens、optimizer updates 和 wall-clock 同时报告，不只比较 epoch。

### 10.3 KDRL

同样从 `SFT-4B-v1` 开始：

```yaml
teacher:
  engine_type: rollout
  path: /data/chengjin/studyhub/models/P1/Qwen3.5-9B
  rl_loss_weight: 1.0
  distill_loss_weight: 0.005
```

只对 `distill_loss_weight` 做小范围对照：`0.001 / 0.005 / 0.01`。GRPO、OPD 与 KDRL 必须共享任务顺序、SFT 起点、工具和环境版本；三种方法至少对最终配置跑 3 个 seed。

## 11. 双 H100 资源布局

### 11.1 2B 与 SFT

- 2B compatibility smoke：单卡。
- 4B LoRA SFT：先单卡 FSDP d1；第二张卡用于独立评测或教师数据生成。数据量不大时，d2 带来的复杂度通常高于收益。

### 11.2 GRPO

```text
GPU 0: 4B actor + colocated/offloaded reference
GPU 1: 4B SGLang rollout
CPU  : 4 个 Hermes subprocess + frozen tools/environment
```

### 11.3 OPD/KDRL

```text
GPU 0: 4B actor + reference
GPU 1: 4B student rollout + 9B teacher rollout（两个独立 inference process）
```

GPU 1 的共置必须先做 20-task memory Gate：

- student 和 teacher 各自从 `mem_fraction_static=0.28-0.32` 起测；
- context length 固定 8192；
- 并发从 1、2、4 逐级增加；
- 开启 `teacher.offload` 做对照；
- 记录权重、KV cache、峰值显存、吞吐和 offload 时间。

若共置不稳定，先改为顺序 teacher scoring；再不稳定才增加 GPU。不能把普通远程 chat API 当成逐 token teacher scorer。

### 11.4 当前机器注意事项

2026-08-24 检查时，两张 H100 各有约 22GB 被其他用户进程占用。正式 compatibility 或训练 Gate 前必须确认 GPU 空闲，不能终止不属于本项目的进程。

## 12. 评测与统计

### 12.1 固定报告项

- 每个 task family 的 success、groundedness、citation、tool validity；
- safety/ACL/privacy hard violation 数量；
- mean/std、bootstrap 95% CI；
- 与共同起点的 paired case difference；
- sampled tokens、train tokens、GPU-hours、wall-clock、峰值显存；
- loss、KL、entropy、clip fraction、reward distribution；
- checkpoint、dataset、corpus、prompt、tool schema 和代码 fingerprint。

### 12.2 选择规则

1. 先满足 safety hard gate；
2. 再比较 sealed holdout task success；
3. success 接近时，比较 groundedness 和 citation；
4. 质量接近时，比较 tokens/success 和 latency；
5. 只有跨 3 个 seed 方向一致的提升才进入 9B scale-up。

不使用训练 reward 的单一最高点选择 checkpoint，防止 reward hacking。

## 13. 实施 Gate

| Gate | 工作 | 通过条件 |
| --- | --- | --- |
| G0 | 版本、环境、语料与许可清单 | 所有 revision/hash 可复现；训练无生产连接 |
| G1 | 2B AReaL + Hermes compatibility | 4-rollout、token mask、一步更新、保存重载全通过 |
| G2 | approved corpus、RAG 与 Reward v2 | 资料映射完整；RAG 指标冻结；Reward 通过人工校准 |
| G3 | Base 4B 与 SFT pilot | SFT 相对 Base 有明确增益且 safety 不退化 |
| G4 | 200-task GRPO pilot | reward 有方差，独立指标同步提升，无串组/泄漏 |
| G5 | GRPO/OPD/KDRL controlled study | 同起点、同任务、3 seeds、统计报告完整 |
| G6 | 9B scale-up | 最佳 recipe 在 9B 上复现，不重新搜索大量超参 |

## 14. 预计周期

以下按 GPU 空闲、资料快照可用估算：

| 阶段 | 预计时间 |
| --- | --- |
| 语料映射、许可台账、holdout 和 Reward v2 | 3-7 天 |
| 真实 AReaL/Hermes 接线与 2B Gate | 1-3 天 |
| 3K SFT pilot 数据生成与过滤 | 2-5 天，主要取决于教师吞吐 |
| 4B SFT 实验矩阵 | 1-2 天 GPU 时间 |
| 200-task GRPO pilot | 6-12 小时 |
| 4B GRPO full | 1-3 天 |
| OPD/KDRL controlled runs | 每组约为 GRPO 的 1.3-2.0 倍，取决于 teacher scoring |
| 9B scale-up | 1-3 天 |

这些是 Gate 预算，不是一次性连续启动所有任务。任一 Gate 失败时先修数据、奖励或接线，不通过增加训练步数掩盖问题。

## 15. 目录与产物

建议使用：

```text
studyhub-agent/
  data_registry/                 # 可提交：来源、许可证、revision、hash、split manifest
  datasets/                      # gitignored：原始和处理后的数据
  snapshots/                     # gitignored：RAG/Web/Memory 冻结快照
  training/areal/                # 可提交：真实 AReaL wrapper、compiler、原生 YAML
  eval/                          # 可提交：评测代码和不含敏感内容的 case contract
  artifacts/                     # gitignored：checkpoint、trajectory、日志和图表
  docs/                          # 可提交：实验方案和结果报告
```

每次实验最少保存：

```text
manifest.json
resolved_config.yaml
metrics.json
per_case.jsonl
trainer_log.jsonl
environment.txt
git_state.txt
dataset_fingerprints.json
checkpoint/
```

## 16. 下一步执行顺序

1. 为现有大体积 `training_artifacts/` 和 `evaluation_artifacts/` 建立明确的忽略与归档策略，避免误提交旧模型。
2. 从现有 OSS 备份生成只包含免费资料的 `approved_material_manifest_v1`，补齐 object key 与 material ID 映射。
3. 建立 `data_registry`，固定首批开源数据 revision、许可证、hash 和用途；先下载小样本做 schema audit，不直接全量下载。
4. 实现 Reward v2 与 400 条 sealed holdout。
5. 把自定义 AReaL 模板替换为 AReaL 原生 SFT/PPO config，并实现可被 AReaL 调用的 Hermes subprocess wrapper。
6. 使用本地 2B 跑通 G1；通过后再下载 `Qwen3.5-4B`。
7. 生成 3K SFT pilot，完成 B0/S1-S4 对照。
8. 冻结最佳 SFT checkpoint 后，先跑 200-task GRPO pilot。
9. GRPO 信号有效后，再从同一 SFT checkpoint 启动 OPD/KDRL。
10. 完成三种方法的 3-seed controlled study 后，决定是否扩展到 9B。

## 17. 主要参考

- [AReaL 官方仓库](https://github.com/inclusionAI/AReaL)
- [AReaL Agentic RL](https://github.com/inclusionAI/AReaL/blob/main/docs/en/tutorial/agentic_rl.md)
- [AReaL Online Proxy](https://github.com/inclusionAI/AReaL/blob/main/docs/en/tutorial/online_proxy.md)
- [AReaL On-Policy Distillation](https://github.com/inclusionAI/AReaL/blob/main/docs/en/algorithms/distillation.md)
- [AReaL LoRA](https://github.com/inclusionAI/AReaL/blob/main/docs/en/reference/lora.md)
- [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)
- [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Search-R1](https://github.com/PeterGriffinJin/Search-R1)
