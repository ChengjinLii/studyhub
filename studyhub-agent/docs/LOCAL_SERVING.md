# 本地 Qwen3.5-9B 模型服务

独立部署 Agent 的推理底座：本地权重 → vLLM → OpenAI 兼容接口 → RAG / Agent。

[配置文件](../configs/serving/qwen35-9b.toml) · [启动代码](../src/studyhub_agent/serving/) · [历史 SGLang 配置](../scripts/serving/README.md)

---

## 设计与默认配置

启动参数参考 [千问官方模型卡](https://huggingface.co/Qwen/Qwen3.5-9B) 与 [vLLM Qwen3.5 使用指南](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html)，结合现有 Agent 的工具协议与窗口预算调整。

| 项目 | 默认值与作用 |
| --- | --- |
| 模型 | 本地 `models/P1/Qwen3.5-9B`，BF16，单卡 TP=1 |
| 引擎 | `vllm==0.32.0`，独立 `.venv-vllm`，不修改训练环境 |
| 接口 | `http://127.0.0.1:30411`，模型标识 `Qwen/Qwen3.5-9B` |
| 工具解析 | `qwen3_coder`，启用自动工具选择 |
| 推理解析 | `qwen3`；默认关闭 thinking，请求可通过现有客户端显式控制 |
| 文本模式 | `--language-model-only`，跳过 Agent 当前不使用的视觉编码器 |
| 上下文 | 输入与输出合计 16384 Token，与 Agent 默认预算一致 |
| 调度 | 最多 4 个请求，2048 Token 的分块预填充预算 |
| 显存 | 使用比例 0.5，另保留至少 4096 MiB，默认拒绝已有 GPU 作业的设备 |
| CUDA Graph | 捕获批大小上限与并发上限一致；可配置 eager 模式排查兼容问题 |
| 前缀缓存 | 默认关闭；`prefix_caching=true` 显式启用 Mamba align 模式 |
| 运行记录 | 独立进程组、就绪检查、轮转日志、原子运行清单、限定重启次数 |

服务不加载网站代码或数据。模型运行环境与 Agent 的轻量 Python 环境分离，普通检索和 CPU 测试不依赖 PyTorch / vLLM。引擎子进程清除继承的 `PYTHONPATH` 与历史 SGLang 补丁变量，避免旧兼容代码意外进入新环境。

### 配置优化的依据

纯文本加载减少视觉模块的资源开销；16K 窗口避免直接照搬官方长上下文示例的资源配置。分块预填充和受限并发用于控制单批工作量，小规模 CUDA Graph 限制捕获范围。

这些属于部署配置，不代表已经测得延迟或吞吐提升。Qwen3.5 是混合注意力 / Gated-DeltaNet 架构，前缀缓存的 Mamba align 模式仍需按官方说明专项验证；默认也不启用 MTP。可先保持相同任务与采样参数，逐项比较首 Token 延迟、生成速度、P95 延迟、峰值显存和任务完成率。

---

## 安装

以下命令在 `studyhub-agent/` 目录执行，使用 Python 3.12：

```bash
# Agent 控制环境：不安装大型推理依赖。
python3.12 -m venv .venv
.venv/bin/pip install -e ".[tokenizers]"

# vLLM 引擎环境：依赖由固定版本的官方发行包解析。
python3.12 -m venv .venv-vllm
.venv-vllm/bin/pip install -r scripts/serving/requirements-vllm.txt
```

已有 Agent 环境只需重新执行可编辑安装以注册 `studyhub-model`。不要把 vLLM 安装进 `.venv-train`，也不要对旧环境单独覆盖 Torch / CUDA 库。

### 驱动与 GPU

vLLM 的二进制发行包、Torch 和 CUDA 必须兼容，安装成功不等于引擎能启动。[官方 GPU 安装说明](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/) 包含支持的构建与容器方案。

CUDA 13 原生兼容通常需要 R580 及以上驱动；CUDA 12 的最低驱动要求不同。旧驱动机器可评估匹配的构建，或官方容器的 CUDA forward-compatibility 路线，不应直接升级宿主机驱动或替换共享训练环境。具体限制见 [NVIDIA 兼容性说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)。容器兼容模式仍需实际验证，不能仅靠设置一个环境变量认定兼容。

```bash
nvidia-smi --query-gpu=index,name,driver_version,memory.free,memory.total,utilization.gpu --format=csv
```

GPU 使用物理编号或完整 UUID，配置中的设备数必须与 TP 一致。预检会检查进程、利用率、空闲显存，以及权重文件大小是否已超过配置预算；后者只是最低估计，不包含 KV / Mamba 状态、激活或图捕获开销。

`allow_shared_gpu=true` 仅供明确知道资源边界的实验使用，不是显存隔离。默认不会自动选择 GPU、抢占训练作业或修改已有服务。

---

## 预览与启动

```bash
CFG=configs/serving/qwen35-9b.toml

# 仅读配置、模型元数据与分片清单，不启动引擎、不访问 GPU。
.venv/bin/studyhub-model plan --config "$CFG"

# 检查权重、固定模板、端口、GPU、引擎版本与 CLI 参数。
.venv/bin/studyhub-model check --config "$CFG"

# 前台启动；通过 /health 和 /v1/models 确认就绪。
.venv/bin/studyhub-model run --config "$CFG"
```

路径均相对 TOML 所在目录解析，不依赖调用时的工作目录。`runtime_python` 保留虚拟环境解释器路径，不把符号链接解析成系统 Python。

退出时按 `Ctrl+C`，先向本次子进程组发送 TERM，超时后再发送 KILL。不会读取历史 PID 杀进程，也不会使用 `pkill`。同一状态目录内的端口与物理 GPU 锁阻止重复启动；锁不覆盖其他工具启动的程序，因此运行期间还会检查显存余量和新出现的其他 GPU 进程，发现冲突时停止自己的服务。

### 本地访问与密钥

配置只接受 loopback 地址，不直接监听公网。可按需通过 `STUDYHUB_KNOWLEDGE_MODEL_API_KEY` 环境变量设置密钥；启动器映射到 vLLM 的 `VLLM_API_KEY`，不把密钥放进参数或运行清单，日志也会替换该密钥。

vLLM 的 API key 不覆盖所有管理端点，因此即使设置密钥，也不能把整个服务端口直接暴露出去。其他机器使用 SSH 隧道访问即可：

```bash
ssh -N -L 30411:127.0.0.1:30411 user@server
```

---

## 工具协议验收

服务就绪后，在另一个终端运行：

```bash
.venv/bin/studyhub-model probe --config configs/serving/qwen35-9b.toml
```

探针会依次检查：

1. 健康状态、模型标识，以及服务返回的上下文长度。
2. `/tokenize` 的输入 Token ID 与 Agent 本地固定模板、真实 tokenizer 完全相同。
3. 模型调用 `studyhub_probe_add(a=17, b=26)`，且工具名称、参数和解析结果正确。
4. 程序返回工具结果与运行时反馈后，再次校验输入 Token ID，模型只回答 `43`。
5. 记录两次模型调用的耗时，并检查 `/metrics` 是否可用。

探针不读取文档或数据库。它会真实调用模型，但只是协议冒烟测试，不是性能基准；Token ID 校验也不等于返回了模型实际采样 Token 或训练所需 logprob。

HTTP 消息转换保留真实 `tool_call_id`；相邻运行时反馈按千问模板放入同一工具响应块，避免严格服务端拒绝虚构 ID，也避免 HTTP 与本地渲染产生额外的消息边界。

---

## 使用现有 Agent

```bash
.venv/bin/studyhub-knowledge \
  --corpus /tmp/studyhub-knowledge/corpus.json --kb demo \
  ask "对比资料中最小二乘与正交投影的关系" \
  --mode agent \
  --model-url http://127.0.0.1:30411 \
  --model Qwen/Qwen3.5-9B \
  --model-dir ../models/P1/Qwen3.5-9B
```

语料导入见 [Agent README](../README.md#快速开始)。`--model-url` 使用根地址，不附加 `/v1`。Wiki 抽取等直接接收完整 endpoint 的功能则使用 `/v1/chat/completions`。

更改服务窗口时，同时检查任务的输入加输出预算；需要更高并发或更长上下文时，先调整 GPU 资源，再修改配置并重新运行 `check` 与 `probe`。

---

## 运行与运维

每次启动在 `artifacts/serving/<UTC时间>-<随机标识>/` 下保存：

| 文件 | 内容 |
| --- | --- |
| `run.json` | 脱敏配置、命令、预检结果、元数据 SHA-256、分片大小、就绪事件与退出状态 |
| `server.log` | 引擎输出，单文件最多 8 MiB，另保留 3 个轮转备份 |
| `cache/` | 位于状态目录根部，供后续运行复用 vLLM / Triton 等缓存 |

元数据与 tokenizer 计算内容哈希；聊天模板必须匹配 Agent 的固定哈希。启动预检只检查大型权重分片存在且非空，不重新计算所有权重的 SHA-256，因此清单中明确记录 `weight_hash_verified=false`。

引擎关闭请求和输出正文日志；运行清单只保存部署信息，不保存探针正文或文档。缓存与日志均独立于模型权重目录。

### 用户级 systemd

[服务单元](../scripts/serving/studyhub-qwen35-9b.service) 使用本机项目路径。安装前确认其中的工作目录与解释器位置，换机器时修改这两个路径。单元会整体管理启动器和子进程，失败后最多在 300 秒内尝试 3 次启动。

```bash
mkdir -p ~/.config/systemd/user
cp scripts/serving/studyhub-qwen35-9b.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user start studyhub-qwen35-9b
systemctl --user status studyhub-qwen35-9b
journalctl --user -u studyhub-qwen35-9b -f

# 停止时释放整个服务控制组。
systemctl --user stop studyhub-qwen35-9b
```

可选环境文件为 `~/.config/studyhub-model.env`，权限设置为 `600`，仅在其中配置所需环境变量；不要提交密钥。默认不启用开机启动。

### 常见检查结果

| 代码 | 处理 |
| --- | --- |
| `gpu_busy` / `gpu_memory` | 等待资源空闲或指定其他已确认可用的 GPU，不停止他人进程 |
| `runtime_unavailable` | 安装独立 vLLM 环境，核对 `runtime_python` |
| `runtime_version` / `runtime_flags` | 核对固定版本及参数支持；不要直接删除检查以绕过错误 |
| `port_busy` | 检查端口已有服务；为新实例选择不同端口和 GPU |
| `startup_timeout` | 查看本次 `server.log`，核对驱动、内核编译与模型资源配置 |
| `server_tokenizer_or_template_mismatch` | 检查 tokenizer、模板、消息序列化与服务端处理，不继续采样训练数据 |

---

## 验证边界

CPU 测试覆盖配置与预检、工具协议模拟、真实子进程组的退出清理和日志脱敏；它们不加载模型权重。

2026-10-22 对本次部署提交的独立快照验证：轻量环境全量测试 457 项通过、20 项 tokenizer 验收跳过，代码覆盖率 96.76%；另使用本地 4B / 9B tokenizer 和 Transformers 5.18.0 完成 20 项验收，包含 HTTP 消息转换后的 Token ID 一致性。Wheel 安装后的 `studyhub-model --help`、`plan` 与无大型模型依赖导入检查通过。systemd 单元作为部署模板提供，尚未启动服务。

真实 tokenizer 验收可在安装 `.[dev,acceptance]` 的独立测试环境复现：

```bash
STUDYHUB_AGENT_MODEL_DIR=../models/P1/Qwen3.5-4B \
STUDYHUB_AGENT_LARGE_MODEL_DIR=../models/P1/Qwen3.5-9B \
python -m pytest tests/acceptance/test_template_matches_transformers.py
```

2026-10-22 在本机执行了真实权重目录的 `plan` 与 `check`：固定模板匹配，分片齐全；预检报告 GPU 占用、显存余量不足，以及尚未创建的 `.venv-vllm`。因此本次没有启动真实 9B vLLM 引擎，也没有报告延迟或吞吐收益。后续实际运行以 `check` 通过、`probe` 完成和真实任务结果为准。
