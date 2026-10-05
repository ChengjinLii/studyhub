# Qwen3.5-4B 推理服务说明

本文记录当前机器上使用 SGLang 启动 Qwen3.5-4B 的配置，以及基础层冒烟任务的运行方式。

[历史运行样例](../../docs/evidence/foundation-smoke-2026-09-25.jsonl) 包含三条任务轨迹；模板一致性通过本地 Transformers tokenizer 验收。

---

## 环境配置

| 项目 | 配置 |
| --- | --- |
| 推理环境 | `/data/chengjin/studyhub/studyhub-agent/.venv-train` |
| 版本 | Python 3.12.13、SGLang 0.5.10.post1、PyTorch 2.9.1+cu129 |
| 模型目录 | `/data/chengjin/studyhub/models/P1/Qwen3.5-4B` |
| 模型结构 | BF16，混合 Gated-DeltaNet / Mamba 与注意力层 |
| 服务地址 | `http://127.0.0.1:30411` |
| 兼容补丁 | 本目录的 `sitecustomize.py` |

此模型的 `config.json.text_config.num_experts` 已为 `None`，无需旧版 `num_experts=1` 覆盖配置。

当前机器只有 pip 安装的 CUDA 运行库，没有 `nvcc`。SGLang 的 `deep_gemm` 导入检查需要通过环境变量启用本目录的兼容补丁；将本目录加入 `PYTHONPATH`，Python 启动时会自动加载。

---

## GPU 资源检查

两张 GPU 为共享资源，启动前检查当前占用：

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv
```

选择空闲显存较多的 GPU，按实际资源设置参数；只停止自己启动的进程，运行结束后确认显存释放。

SGLang 的显存池根据模型加载前后的空闲显存计算：

```text
rest_memory = post_load_avail - pre_load_avail * (1 - mem_fraction_static)
```

共享 GPU 上的 `--mem-fraction-static` 不能简单理解为总显存的使用比例。每次启动前后都应重新检查显存。

---

## 启动服务

将 `GPU` 设置为已检查的可用设备编号：

```bash
V=/data/chengjin/studyhub/studyhub-agent/.venv-train
REPO=/data/chengjin/studyhub/studyhub-agent
GPU=1
CUDA_RUNTIME_LIB="$V/lib/python3.12/site-packages/nvidia/cuda_runtime/lib"

mkdir -p /tmp/studyhub-agent-smoke

CUDA_VISIBLE_DEVICES="$GPU" \
STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC=1 \
STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC=1 \
PYTHONPATH="${REPO}/scripts/serving" \
LD_LIBRARY_PATH="${CUDA_RUNTIME_LIB}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
setsid nohup "$V/bin/python" -m sglang.launch_server \
  --model-path /data/chengjin/studyhub/models/P1/Qwen3.5-4B \
  --host 127.0.0.1 --port 30411 \
  --mem-fraction-static 0.40 \
  --context-length 8192 --max-total-tokens 8192 \
  --max-running-requests 1 --max-mamba-cache-size 8 \
  --disable-cuda-graph \
  > /tmp/studyhub-agent-smoke/sglang.log 2>&1 &
echo $! > /tmp/studyhub-agent-smoke/sglang.pid
```

### 参数说明

| 参数 | 用途 |
| --- | --- |
| `--mem-fraction-static 0.40` | 历史运行在约 28 GB 空闲显存下验证的配置，按实时空闲量调整 |
| `--max-mamba-cache-size 8` | 为混合模型提供固定请求状态缓存，保留 KV token 池空间 |
| `--max-running-requests 1` | 冒烟任务使用单请求并发 |
| `--disable-cuda-graph` | 避开此版本单请求配置的空捕获批大小问题 |
| `--context-length 8192` | 覆盖示例短任务，长任务按预算与显存扩展 |
| `setsid` | 创建独立进程组，便于完整停止本次服务 |

历史运行中，`0.28` 的显存比例产生了负的 token 池预算；`0.40` 通过资源检查。Mamba / GDN 缓存独立于上下文长度，过大的默认缓存可能占满静态预算；开启 radix cache 时，其缓存大小与并发数还受内部比例约束。

示例的 8192 上下文长度并不覆盖所有任务默认的 16384 token 预算，长任务需同时调整服务参数与任务预算。

---

## 检查服务

```bash
until [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:30411/health)" = "200" ]; do
  kill -0 "$(cat /tmp/studyhub-agent-smoke/sglang.pid)" || { echo "服务进程退出，请查看 sglang.log"; break; }
  sleep 5
done
```

历史运行在操作系统热缓存下，权重加载和显存池初始化约需 30–35 秒。可通过 `/tmp/studyhub-agent-smoke/sglang.log` 排查：

| 日志 | 检查项 |
| --- | --- |
| `RuntimeError: Not enough memory` | 空闲显存和显存比例 |
| `deep_gemm` 断言 | `PYTHONPATH` 与兼容补丁环境变量 |
| `capture_bs` 断言 | CUDA graph 配置 |

---

## 运行示例任务

在 Agent 目录中，使用已安装项目依赖的 Python 环境执行：

```bash
cd "$REPO"
.venv/bin/python scripts/smoke_episodes.py \
  --model-dir /data/chengjin/studyhub/models/P1/Qwen3.5-4B \
  --sglang-url http://127.0.0.1:30411 \
  --snapshot tests/fixtures/replay_snapshot.json \
  --tasks tests/fixtures/smoke_tasks.jsonl \
  --architecture react_verify \
  --model-id Qwen/Qwen3.5-4B \
  --out /tmp/studyhub-agent-smoke/episodes.jsonl
```

`--architecture` 支持 `react`、`react_verify`、`plan_execute`、`react_context` 与 `cascade`。级联通过 `--large-model-dir` 和 `--large-sglang-url` 指定第二个服务，完整示例见 [Agent README](../../README.md#双模型级联)。

---

## 停止服务

以下命令只针对上面记录的本次服务 PID；`setsid` 使 PID 与进程组 ID 一致：

```bash
PID=$(cat /tmp/studyhub-agent-smoke/sglang.pid)
kill -TERM -- -"$PID"
sleep 5
kill -0 "$PID" 2>/dev/null && kill -KILL -- -"$PID"
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv
```

确认本次服务退出、占用显存释放后结束运行。

---

## 历史记录说明

历史样例使用文件大小生成 tokenizer 版本标识，如 `Qwen3.5-4B@12807982`；当前实现使用内容 SHA-256，如 `Qwen3.5-4B@sha256:5f9e4d4901a9`，并纳入契约哈希。架构与预算字段的扩展也会改变新运行的哈希，重新采样得到的文本、工具调用与终止结果可能不同。

旧样例中的 `completion_token_ids` 对应当时的数据结构。当前回合分别记录模型实际采样的 `sampled_token_ids` 与标准化文本编码后的 `canonical_token_ids`。
