# Review-Jev 配置说明

本文记录推理后端、环境变量与服务配置。

---

## 后端选择

| 后端 | 配置 |
| --- | --- |
| 自动分流 | `--backend auto`，文字与图文分别使用对应模型 |
| 文字模型 | `--backend qwen3guard` |
| 本地 OneJev | `--backend torch --model OmniJev/OneJev-4B` |
| OneJev HTTP | `--backend onejev-http --onejev-url http://127.0.0.1:8000` |
| 演示模式 | `--backend demo` |

`--model` 支持模型标识或本地目录。自动模式使用 `--image-backend onejev-http` 时，图片分支交由本机 OneJev 服务处理。

### GGUF 推理

安装 `.[gguf]` 并配置 `llama-server` 后，使用上游 `qev serve --gguf ...` 启动推理，审核侧仍使用 `onejev-http`。

HTTP 后端默认请求 `jev-latest` 别名，自定义服务模型名通过 `--served-model` 指定。

---

## 环境变量

| 变量 | 默认值或说明 |
| --- | --- |
| `REVIEW_JEV_BACKEND` | `auto` |
| `REVIEW_JEV_IMAGE_BACKEND` | `torch`，也支持 `onejev-http` |
| `REVIEW_JEV_ONEJEV_URL` | `http://127.0.0.1:8000` |
| `REVIEW_JEV_MODEL` | `OmniJev/OneJev-4B` 或本地目录；固定文字后端默认为 0.6B |
| `REVIEW_JEV_MODEL_REVISION` | 默认模型版本固定；自定义模型可显式配置 |
| `REVIEW_JEV_TEXT_MODEL` | `Qwen/Qwen3Guard-Gen-0.6B` |
| `REVIEW_JEV_TEXT_MODEL_REVISION` | 默认文字模型版本固定 |
| `REVIEW_JEV_SERVED_MODEL` | `jev-latest` |
| `REVIEW_JEV_DEVICE` | `auto`，优先使用空闲显存最多的 CUDA 设备，否则 CPU |
| `REVIEW_JEV_TEXT_DEVICE` | `cpu` |
| `REVIEW_JEV_MAX_INPUT_TOKENS` | `8192`，文字输入超限报错，不静默截断 |
| `REVIEW_JEV_TIMEOUT` | `120` 秒，HTTP 超时与文字生成软时间限制 |
| `REVIEW_JEV_POLICY` | 本地规则 JSON 文件路径 |
| `REVIEW_JEV_API_KEY` | 可选，通过 `Authorization: Bearer ...` 使用 |
| `REVIEW_JEV_ALLOW_AUTO_APPROVE` | `false` |
| `REVIEW_JEV_ALLOW_AUTO_REJECT` | `false` |
| `REVIEW_JEV_CONCURRENCY` | `2`，超过处理容量返回 503 |

权重版本默认固定在 `review_jev/config.py`。`REVIEW_JEV_TIMEOUT` 不是本地模型加载的硬超时；图文分支也对输入进行长度限制。

---

## 模型加载与就绪

模型在首次对应请求时加载。默认自动模式中，两个分支都完成加载后 `/ready` 返回 200，此前返回 503；`/health` 用于进程存活检查。

CUDA 设备可通过 `--device cuda:1` 明确指定；文字设备通过 `--text-device` 指定。

---

## 服务配置

服务默认监听 `127.0.0.1:8011`。通过 CLI 监听非本机地址时，需要设置 API key；正式部署还应配置 TLS、反向代理限流与连接、请求体超时。

模型、规则、后端地址和自动建议门禁由服务端配置，投稿请求不能覆盖。自动门禁的结果解释见 [审核结果说明](REVIEW_SEMANTICS.md#门禁与评测)。

当前实现不持久化投稿正文、图片和审核记录；外部反向代理和推理服务日志按部署环境单独配置。独立运行验证见 [验证记录](../VALIDATION.md)。
