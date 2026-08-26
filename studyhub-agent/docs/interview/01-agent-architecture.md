# StudyHub Agent 的训练架构是什么？

## 30 秒回答

StudyHub 没有重写 Agent loop。Hermes 负责多轮推理和工具调用，SGLang 提供当前策略的推理服务，冻结环境执行每个任务允许的工具，Reward v2 根据隐藏 verifier 打分，AReaL 再完成 GRPO 的采样、优势计算和 LoRA 更新。网站前后端不参与这条训练链路。

## 深入解释

一次轨迹的主链路是：

```text
AReaL task
  -> StudyHubHermesWorkflow
  -> Hermes AIAgent
  -> AReaL OpenAI-compatible gateway
  -> SGLang + Qwen3.5 policy
  -> task-scoped tool call
  -> FrozenTaskEnvironment
  -> observation 回到 Hermes
  -> final answer
  -> hidden verifier + Reward v2
  -> AReaL GRPO update
```

职责边界如下：

| 组件 | 负责 | 不负责 |
| --- | --- | --- |
| Hermes | 对话状态、工具循环、停止条件、工具 guardrail | 权重更新、生产数据库访问 |
| StudyHub workflow | 注入训练 prompt、注册任务级工具、隔离运行时、落 Reward 证据 | 重写 Hermes 核心 |
| Frozen Environment | 固定工具结果、冻结语料、Search→Read 约束、预算 | 网络、文件系统、生产服务 |
| SGLang | 高吞吐 rollout 推理、LoRA 加载 | Reward 和 optimizer |
| AReaL | group rollout、logprob、advantage、PPO/GRPO 更新、checkpoint | 业务工具实现 |

## StudyHub 的实现与取舍

训练环境显式禁用网络、文件系统、shell、凭证和生产 StudyHub 服务。每个任务只注册自己的少量工具，并在任务结束后注销。Hermes 仍是原始 loop，仅做了训练边界内的最小配置：固定 system prompt、关闭交互宿主能力、跳过 memory、启用重复失败与无进展停止。

这套隔离使网站 `backend/`、`frontend/`、数据库、支付和 OSS 不会被 RL rollout 触达。它训练的是通用的工具使用、检索和证据归纳策略，不是在线执行生产动作。

## 可能追问

- 为什么不直接在 AReaL workflow 中手写循环？保留 Hermes 可以复用成熟的消息、工具、停止和 guardrail 语义，减少两套 Agent runtime 漂移。
- 为什么训练时关闭 Hermes memory？当前对照实验要先隔离 search/tool policy；memory 应作为独立能力与消融变量接入。
- Search-R1 在哪里？当前 RL 思路借鉴了“模型自主搜索—观察—继续推理”，但 rollout harness 使用 Hermes，训练器使用 AReaL，并非宣称原样运行 Search-R1。

## 代码与实验依据

- `training/rl/hermes_workflow.py`
- `training/rl/frozen_environment.py`
- `training/rl/open_agent_driver.py`
- `configs/train/open-grpo-qwen35-4b.yaml`
- `docs/interview/incidents/2026-08-26-duplicate-training-system-prompt.md`
- `artifacts/experiments/direct-smoke-seed-6209-20260826_120243/`
