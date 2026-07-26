# Agentic Platform 外部学习笔记

本文件记录 PR 0 固定版本后的阅读结论。外部源码仅存在于被忽略的 `.local-research/vendor/`；不得复制、提交或作为产品运行时依赖。

## Search-R1

- Commit：`598e61bd1d36895726d28a8d06b3a15bed19f5d3`
- License：Apache-2.0（根目录 License 文件由同步脚本校验）
- 已读文件：`README.md`、`docs/retriever.md`、`docs/experiment_log.md`、`scripts/data_process/nq_search.py`、`search_r1/search/retrieval_server.py`、`search_r1/search/retrieval_request.py`、`infer.py`、`train_ppo.sh`。旧方案中的 `retriever_server.py` 在该 SHA 已更名为 `retrieval_server.py`。
- StudyHub 采用：推理与检索交错；独立 Retriever HTTP Adapter；返回 candidate ID、文档内容与可选分数；训练样本的 `data_source/prompt/ability/reward_model/extra_info` 形状；Tool Observation 进入后续上下文但不参与策略梯度。
- 明确不采用：旧训练依赖、Wikipedia 路径、字符串标签状态和产品后端内训练。
- 版本风险：该仓库仅作为历史行为基线；训练基础设施以新版 veRL Adapter 为准。

## veRL

- Commit：`983cb0f24443f87b3d161fad318445130a620b07`
- License：Apache-2.0（根目录 License 文件由同步脚本校验）
- 已读文件：`docs/start/agentic_rl.rst`、`docs/advance/fully_async.md`、`verl/experimental/agent_loop/agent_loop.py`、`verl/experimental/agent_loop/tool_agent_loop.py`。
- StudyHub 采用：异步 Rollout/Environment 边界、可中断多轮 Agent Loop、轨迹落盘 Adapter，以及原始 token ID 与 rollout logprob 必须随轨迹保存的原则。
- 明确不采用：将训练进程或 Ray runtime 嵌入 FastAPI。
- 版本风险：训练 API 演进较快；产品只依赖稳定的导出契约。

## VerlTool

- Commit：`383d4b1539ba387f94c3a117d3edc06b467c09d1`
- License：MIT（根目录 License 文件由同步脚本校验）
- 已读文件：`README.md`、`verl_tool/agent_loop/verltool_agent_loop.py`、`verl_tool/trainer/ppo/ray_trainer.py`、`benchmarks/README.md`。
- StudyHub 采用：Tool-as-environment、每条轨迹独立环境状态、Step Record、异步工具调用、Fixture/Snapshot Executor 与 token role 边界；工具失败作为结构化 Observation，而非静默丢弃轨迹。
- 明确不采用：把 VerlTool 作为线上产品运行时。
- 版本风险：训练侧 API 与 veRL 联动，保持 Adapter 隔离。

## DeepResearcher

- Commit：`82c6dc2d7508e1c271aa0b4344832bcaf5bf6cde`
- License：Apache-2.0（根目录 License 文件由同步脚本校验）
- 已读文件：`README.md`、`scrl/handler/handler.py`、`scrl/handler/server_handler.py`、`signal/*.json`、`evaluate/cacluate_metrics.py`、`train_grpo.sh`。
- StudyHub 采用：真实 Web 环境故障建模、规划/交叉验证/诚实终止，以及将 Search Handler 与训练进程分离。
- 明确不采用：其训练脚本和运行时耦合。
- 版本风险：外部 Web 环境不可复现，必须通过 Snapshot/Fixture 固化观察。

## DR Tulu

- Commit：`9d7b0371c085e9311ddec483ed39768c0bd9fe99`
- License：Apache-2.0（根目录 License 文件由同步脚本校验）
- 已读文件：`README.md`、`agent/README.md`、`sft/llama-factory/README.md`、`rl/open-instruct/README.md`。
- StudyHub 采用：MCP-style Tool Backend、高并发异步请求、长篇 Research Report、SFT 轨迹与 RL/Rubric 数据分离。
- 明确不采用：固定使用其 GRPO 或将其训练代码纳入产品。
- 版本风险：论文/仓库版本存在快速演进，保持协议而非实现依赖。

## CaRR

- Commit：`c97e7e892b4dbd0f7ba4b5f2fb052b9af0f3a592`
- License：MIT（根目录 License 文件由同步脚本校验）
- 已读文件：`README.md`、`deepsearch_rm_with_rubrics/README.md`、`tool_server/web_search.py`、`scripts/training/training_run_4b-C-GRPO-rubric0.3.sh`、`scripts/eval/evaluation_run_4b.sh`。
- StudyHub 采用：Atomic Rubric、实体识别、Claim–Citation、Citation Verifier 与 Reward Facts 的事实记录；运行时只记录支撑事实，不固化 rubric reward 权重。
- 明确不采用：把 Reward Model Server 接入产品在线请求。
- 版本风险：Citation Reward 定义将在训练阶段单独版本化。
