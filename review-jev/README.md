<div align="center">

# StudyHub Review-Jev

**面向文字与图片投稿的内容审核组件**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#快速开始)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](#审核接口)
[![Qwen3Guard](https://img.shields.io/badge/Text-Qwen3Guard--0.6B-2563eb)](#模型分流)
[![OneJev](https://img.shields.io/badge/Multimodal-OneJev--4B-15803d)](#模型分流)
[![Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-22c55e)](LICENSE)

[功能概览](#功能概览) | [快速开始](#快速开始) | [模型分流](#模型分流) | [审核接口](#审核接口) | [测试与评测](#测试与评测)

</div>

StudyHub Review-Jev 基于 [OneJev](https://github.com/OmniJev/OneJev) 构建，将模型推理、投稿规则、版权辅助分析与结构化结果整合为一个审核流程，支持资料、经验、评论、求购和集市内容。

**纯文字交给轻量模型，图片与图文交给多模态模型。**

---

## 功能概览

| 能力 | 内容 |
| --- | --- |
| 投稿解析 | 标题、描述、正文、预览文本、图片与版权声明 |
| 合规筛查 | 色情、暴力、仇恨骚扰、违法危害与敏感个人信息 |
| 场景规则 | 广告与站外支付、学术作弊、审核操纵与可读性 |
| 版权辅助 | 原创或授权声明、署名、开放许可、NC / ND 条件 |
| 参考匹配 | 参考文本相似性、图片原文件 SHA-256 匹配 |
| 结果追踪 | 模型版本、规则哈希、内容哈希与逐项结果 |
| 使用方式 | FastAPI 服务、JSON 命令行、批量评测与演示模式 |

图文分支按十一项 StudyHub 规则推理，文字分支保留模型原生安全等级与类别。各字段的判定方式见 [审核结果说明](docs/REVIEW_SEMANTICS.md)。

---

## 快速开始

在 `review-jev/` 目录下执行，支持 **Python 3.10+**。

### 体验演示模式

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/review-jev serve --backend demo
```

默认地址：`http://127.0.0.1:8011`。打开 `http://127.0.0.1:8011/docs` 查看接口文档。

命令行也可直接处理示例：

```bash
.venv/bin/review-jev review examples/original-notes.json --backend demo
.venv/bin/review-jev policy
```

演示响应使用 `status=demo` 标识，便于体验接口与结果格式。

### 启用模型推理

```bash
.venv/bin/pip install -e ".[torch]" -c constraints-tested.txt
.venv/bin/review-jev serve
```

服务按请求内容自动选择模型，首次对应请求时加载权重。默认模型版本固定，权重保存在 Hugging Face 用户缓存中。

---

## 模型分流

```text
投稿内容 -> 解析与媒体校验 -> 自动选择模型 -> 规则与版权辅助检查 -> 审核结果
                              |
                              +-- 纯文字：Qwen3Guard-Gen-0.6B
                              |
                              +-- 图片 / 图文：OneJev-4B
```

| 内容类型 | 默认模型 | 默认设备 | 结果形式 |
| --- | --- | --- | --- |
| 纯文字 | [Qwen3Guard-Gen-0.6B](https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B) | CPU | 原生安全等级与类别 |
| 纯图片或图文 | [OneJev-4B](https://huggingface.co/OmniJev/OneJev-4B) | 优先 CUDA | 逐项规则风险概率 |

路由依据经过解码校验的图片确定；图文模型同时读取文字与全部图片。可通过 `--device` 和 `--text-device` 指定设备。

单独运行文字模型：

```bash
.venv/bin/pip install -e ".[guard]"
.venv/bin/review-jev review examples/original-notes.json --backend qwen3guard --device cpu
```

---

## 审核接口

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 进程健康检查 |
| `GET /ready` | 模型就绪检查 |
| `GET /v1/policy` | 获取审核规则 |
| `POST /v1/reviews` | 提交审核请求 |
| `GET /docs` | 查看交互式接口文档 |

### 请求示例

```json
{
  "request_id": "submission-001",
  "content": {
    "title": "高等数学复习笔记",
    "text": "这份笔记整理了我对极限与导数的理解。",
    "images": []
  },
  "context": {
    "kind": "material",
    "publication_intent": "FREE"
  },
  "rights": {
    "basis": "original",
    "copyrightOwner": "投稿作者",
    "attested": true
  },
  "references": []
}
```

```bash
curl --noproxy "*" -s http://127.0.0.1:8011/v1/reviews \
  -H "Content-Type: application/json" \
  --data-binary @examples/original-notes.json
```

图片使用 `{"id":"preview-1","data":"data:image/png;base64,..."}` 格式。支持 PNG、JPEG 和 WebP，最多四张；单张上限 4 MiB、1200 万像素，HTTP 请求上限 24 MiB。输入细节见 [请求与结果说明](docs/REVIEW_SEMANTICS.md)。

### 主要输出

| 字段 | 内容 |
| --- | --- |
| `decision` | `approve`、`manual_review` 或 `reject` |
| `status` | 完成、部分完成、降级或演示状态 |
| `findings` | 逐项规则结果、风险信号与作用范围 |
| `model_assessment` | 文字模型的原生安全等级与类别 |
| `copyright` | 声明、许可条件与参考匹配分析 |
| `model` / `backend` / `model_revision` | 实际模型、推理后端与权重版本 |
| 内容及规则哈希 | 用于结果追踪与评测复现 |

---

## 推理后端

默认 `auto` 在审核进程内完成模型分流，也支持单模型与独立推理服务。

| 后端 | 使用方式 |
| --- | --- |
| `auto` | 默认自动分流 |
| `qwen3guard` | 固定使用文字模型 |
| `torch` | 固定使用 OneJev 多模态模型 |
| `onejev-http` | 调用 OneJev HTTP 推理服务 |
| `demo` | 体验接口和模拟结果 |

### 独立 OneJev 服务

```bash
.venv/bin/qev serve --model OmniJev/OneJev-4B --host 127.0.0.1 --port 8000
```

另一个终端启动审核服务：

```bash
.venv/bin/review-jev serve --backend onejev-http --onejev-url http://127.0.0.1:8000
```

自动分流也可使用 `--image-backend onejev-http` 指定图片推理服务。GGUF 后端、设备选择与完整环境变量见 [配置说明](docs/CONFIGURATION.md)。

---

## 测试与评测

### 单元测试

```bash
.venv/bin/pytest -q
.venv/bin/ruff check review_jev tests/test_review*.py
```

### 批量评测

```bash
.venv/bin/review-jev evaluate examples/evaluation.jsonl --backend demo
```

使用 `--output artifacts/report.json` 可保存聚合评测报告。评测支持规则判定统计、原生类别统计与概率指标。

### 模型冒烟测试

```bash
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -m review_jev.smoke --http --output artifacts/smoke.json
```

覆盖中文文字、隐私风险、图文、纯图片、多图片与本机 HTTP 分流。测试环境和结果见 [验证记录](VALIDATION.md)。

---

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [请求与结果说明](docs/REVIEW_SEMANTICS.md) | 输入格式、判定语义与版权辅助检查 |
| [配置说明](docs/CONFIGURATION.md) | 后端、环境变量与部署设置 |
| [验证记录](VALIDATION.md) | 模型版本、测试结果与评测说明 |
| [来源与许可](UPSTREAM.md) | OneJev 来源、改造内容与许可证 |

代码采用 [Apache-2.0](LICENSE) 许可，上游说明保留在 [OneJev 原文](README.onejev.md)。
