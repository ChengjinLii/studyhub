# StudyHub Agent 离线 Pilot 与运行时约束报告

日期：2026-08-08  
分支：`agent/offline-pilot-runtime-guards`  
权威代码：`4da95fba643db9ffb50f6782c7a07b56cb64087a`

## 1. 结论

- 线上隔离成立：没有加载生产环境文件，没有连接生产数据库、API、OSS 或远程模型，也没有部署、迁移生产库或重启服务。
- 离线框架通过：确定性 Fixture 的 100 场景 Gate 完整通过，说明 Snapshot、AgentKernel、Skill、轨迹、重放、引用与 Gate 本身可工作。
- v1.3 adapter 未通过模型 Gate：严格质量完成 `52/100`，引用有效 `72/100`，但安全项为 `0` ACL 违规、`100/100` 可重放、`100/100` 内核安全终止。
- 运行时约束有效但不能替代训练：相对 raw 运行，质量完成由 `15` 提升到 `52`，无效引用由 `82` 降到 `28`；仍有 `49` 场依赖 JSON 恢复。
- **v1.4 决策：GO，仅进入针对性数据构建和单 seed SFT 消融；NO-GO for RL、三 seed 扩展、最终留出集和线上切换。**

## 2. 隔离边界

执行目录固定为 `/data/chengjin/studyhub-offline-pilot`。启动器实施以下 fail-closed 检查：

- Git worktree 必须干净，每个场景明文记录当前 commit SHA。
- provider 仅允许 `fixture-snapshot*` 或 `local-qwen*`。
- 拒绝 `production` 环境、任何数据库 URL、远程模型 Base URL 和生产 `.env`。
- trajectory 与 output 必须位于 Git 忽略的 `artifacts/agentic_platform/offline-pilot/`。
- Hugging Face 强制 `local_files_only`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`。
- 数据为全合成免费资料快照；受限资料 `9901` 仅是 ACL 拒绝 fixture，不含真实付费内容。

MySQL 验证使用一次性 Ubuntu 容器内的官方 MySQL `8.4.11`，仅监听
`127.0.0.1:33307`。从空库执行 `0001` 到 `0008_material_submission_idempotency`
成功后，容器、端口和下载包均已删除。下载只使用 `127.0.0.1:7892`。

## 3. 实现内容

- 100 场景矩阵：discovery 20、evidence 20、compare 10、question pages 10、answer pages 10、force-final 10、injection 10、restricted 10。
- 使用真实 `AgentKernel`、冻结 Snapshot Skill、`DurableTransitionSink` 和二次 action replay，不使用仅返回预设分数的假 runner。
- 本地模型为 `Qwen3.5-2B`，adapter 为 `qwen35_2b_lora_v1_3_state_ablation_from_7703`。
- 线上 Agent 增加默认关闭的 `STUDYHUB_AI_AGENT_RUNTIME_CONSTRAINTS_ENABLED`。
- 开关启用时才加入确定性 `routing_state`，并只恢复明确声明 `mode=tools`、`actions` 和允许工具名的首个只读动作。
- malformed final 不会被误转为工具调用；未知工具、`<think>` 输出、未观察 ID 和越权 ID 均 fail closed。
- 开关关闭时保留原解析路径，因此本分支不会自动改变线上行为。

## 4. Gate 结果

### 4.1 框架基线

`fixture-authoritative-4da95fb`：

| 指标 | 结果 |
|---|---:|
| Gate | PASS |
| 完成 | 100/100 |
| 引用有效 | 100/100 |
| Replay 一致 | 100/100 |
| Manifest 校验 | 100/100 |
| Token / role span | 430/430 |
| ACL 违规 | 0 |

Pilot hash：`026d4e7cfe862b8c6b3ec65af0f1206700269ef672040ab841f5a5c3d4d597da`  
Gate hash：`9de047fe76c1c686fa50ca79db2a0406260b90b65ed980c144d1ad9a9b3d241d`

### 4.2 本地模型权威 Gate

`qwen-guarded-100-v1.3-4da95fb`：

| 指标 | 结果 |
|---|---:|
| Gate | FAIL |
| 严格质量完成 | 52/100 |
| 内核安全终止 | 100/100 |
| 引用有效 | 72/100 |
| Replay 一致 | 100/100 |
| ACL 违规 | 0 |
| JSON 运行时恢复 | 49/100 |
| 只读 Skill 调用 | 64 |
| 超过 60 秒 queue | 9 |
| 最大 queue | 126.49 秒 |

Pilot hash：`2a1ea7c9721e8502cc6629a0879430ec3b5472616100a95b4fb11437b2775a59`  
Gate hash：`5a5e029069aa51421c783d737831f32acacdcc13c14a608aeaffbeb0e30b97a2`

按场景家族：

| 家族 | 通过 | 失败 |
|---|---:|---:|
| discovery | 20 | 0 |
| evidence | 0 | 20 |
| compare | 0 | 10 |
| question_pages | 3 | 7 |
| answer_pages | 9 | 1 |
| force_final | 10 | 0 |
| injection | 0 | 10 |
| restricted | 10 | 0 |

主要违规为：工具调用不足 `48`、缺少 PDF 证据 `28`、引用契约失败 `28`。
常见模式是没有候选时直接请求 PDF、把真实候选 ID 改写为 `1`、比较任务提前
final，以及注入场景错误选择 memory 或直接收束。运行时会拒绝这些动作，但不会
替模型编造搜索步骤或资料 ID。

对照结果：

| 运行 | 质量完成 | 无效引用 | ACL 违规 | Replay |
|---|---:|---:|---:|---:|
| raw v1.3 | 15 | 82 | 0 | 100 |
| guarded v1 | 45 | 34 | 0 | 100 |
| guarded authoritative | 52 | 28 | 0 | 100 |

## 5. v1.4 SFT 决策

建议构建约 `1,800` 条全新、与当前 100 场景不重叠的数据：

| 数据类型 | 建议数量 |
|---|---:|
| 严格单 JSON、完整 final/tools 契约 | 300 |
| 无候选先搜索、已有候选再 inspect/read 的配对样本 | 250 |
| Material ID、页码逐字保真 | 200 |
| 注入后继续只读任务 / 必须拒绝 / 必须 final 对照 | 150 |
| evidence、compare 的继续与停止条件 | 100 |
| direct answer、force-final 保留 | 100 |
| 经审计的旧能力 replay | 700 |

训练约束：

1. 从已知 v1.1 seed 7703 路径重新构建消融，不从失败的 v1.3 adapter 继续续训。
2. 当前 100 场景全部保持 `internal_eval_only`，不得复制到训练集。
3. 先做一个 seed；达到严格 JSON `>=99%`、运行时恢复 `<=5%`、ID 保真
   `>=98%`、注入继续/权限拒绝 `100%` 后，才允许三 seed 扩展。
4. 重新运行同一 100 场景时要求质量完成、引用和 replay 均为 `100/100`，ACL
   违规为 `0`。
5. 最终留出集继续密封；SFT 稳定前不做 RL。RL 不能修复丢失 ID、损坏 JSON
   或错误工具前置条件，反而可能放大提前 final 偏置。

queue 超时应作为独立运行时性能任务处理：缩短工具轮输出上限、按生成预算分组
micro-batch，并为后续轮次增加公平调度。不得通过提高正式 Gate 阈值掩盖。

## 6. 验证与产物

- Backend Ruff：通过。
- Backend 完整 pytest、Agentic smoke、执行 E2E、轨迹完整性：通过。
- Frontend typecheck、lint、strict typecheck、47 个单测：通过。
- Playwright 开发和生产模式：各 9 passed / 4 skipped；均使用本地临时服务。
- MySQL 8.4.11 空库迁移：通过；未触碰生产数据库。
- GitHub 分支已推送；仓库工作流仅在 `main` push 或 PR 上运行，没有部署 job。

权威模型文件：

- Adapter SHA-256：`458256e929f2ee3560712912bffc4eb97d69df6fbd6ec4d3272e673616ec8ee6`
- Base config SHA-256：`ed1c1723241f23f7f4e23430759cbd7dcfb4103cbdfe052bfe7626b57c2615b4`

轨迹、模型输出和 Gate JSON 位于 Git 忽略目录：

```text
artifacts/agentic_platform/offline-pilot/fixture-authoritative-4da95fb/
artifacts/agentic_platform/offline-pilot/qwen-guarded-100-v1.3-4da95fb/
```
