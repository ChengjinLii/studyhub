<div align="center">

# StudyHub Review-Jev

**按内容分流的文本与图像安全概率决策组件**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#快速开始)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](#审核接口)
[![Qwen3Guard](https://img.shields.io/badge/Text-Qwen3Guard--0.6B-2563eb)](#模型分流)
[![ShieldGemma](https://img.shields.io/badge/Image-ShieldGemma_2--4B-15803d)](#模型分流)
[![Guard-as-Jev](https://img.shields.io/badge/Decision-Guard--as--Jev-c2410c)](#概率决策)
[![Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-22c55e)](LICENSE)

[功能概览](#功能概览) | [快速开始](#快速开始) | [模型分流](#模型分流) | [概率决策](#概率决策) | [审核接口](#审核接口)

</div>

StudyHub Review-Jev 是独立运行的内容审核组件，采用 **Qwen3Guard-Gen-0.6B + ShieldGemma 2-4B** 双 Guard 架构。通过 Guard-as-Jev 候选概率评分，将文字安全等级、图像政策风险和规则检查汇总为可追踪的审核结果。

**按需调用模型，分别保留证据，再进行规则融合。**

---

## 功能概览

| 能力 | 内容 |
| --- | --- |
| 内容路由 | 根据实际正文、图片和 OCR 结果选择审核分支 |
| 文字安全 | 三种安全等级的候选概率，以及模型原生风险类别 |
| 图像安全 | 色情、危险、暴力三项政策的独立 Yes/No 概率 |
| OCR 适配 | 本地 Tesseract 提取图片文字，按需触发文字审核 |
| 规则融合 | 合并安全信号、版权声明、开放许可条件与参考匹配 |
| 人工复核 | 低置信度、判断分歧、覆盖缺失及异常的明确处理 |
| 结果追踪 | 原始分数、模型版本、校准标识、分支轨迹及来源范围 |
| 使用方式 | FastAPI、JSON 命令行、批量评测及演示模式 |

---

## 快速开始

在 `review-jev/` 目录执行，支持 Python 3.10+。

### 演示接口

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/review-jev serve --backend demo
```

默认地址为 `http://127.0.0.1:8011`，交互式接口文档位于 `/docs`。

```bash
.venv/bin/review-jev review examples/original-notes.json --backend demo
```

### 启用模型

```bash
.venv/bin/pip install -e ".[torch]" -c constraints-tested.txt
.venv/bin/review-jev serve
```

模型按需加载。首次使用图像模型前，需要通过 Hugging Face 获得 [ShieldGemma 权重访问权限](https://huggingface.co/google/shieldgemma-2-4b-it)。OCR 的系统依赖与语言包配置见 [配置说明](docs/CONFIGURATION.md)。

仅运行文字审核：

```bash
.venv/bin/review-jev review examples/original-notes.json \
  --backend qwen3guard --device cpu
```

---

## 模型分流

| 投稿内容 | 调用方式 |
| --- | --- |
| 纯文字 | 只调用 Qwen3Guard-Gen-0.6B |
| 图片，OCR 未检出文字 | 只调用 ShieldGemma 2-4B |
| 图片及投稿正文 | 正文走 Qwen，图片走 ShieldGemma |
| 聊天截图、文字海报、扫描页面 | OCR 文字走 Qwen，画面走 ShieldGemma |

```text
正文 --------------------------> Qwen3Guard-Gen-0.6B
图片 --> OCR --检出文字---------> Qwen3Guard-Gen-0.6B
  |
  +----------------------------> ShieldGemma 2-4B
                                       |
                 原生分数 + 校准 + 规则融合
                                       |
                           通过 / 人工复核 / 拒绝
```

两个模型不重复审核相同输入。图片分支只接收图片与原生政策，投稿正文和 OCR 结果不会作为安全政策注入图片模型。当前审核 API 接收文字与页面图片；PDF 文件解析由独立知识库提供。

---

## 概率决策

| 分支 | 评分机制 | 返回内容 |
| --- | --- | --- |
| Qwen3Guard-as-Jev | 对完整候选标签续写逐 Token 计算条件对数概率，再在候选集合内归一化 | `Safe / Controversial / Unsafe` |
| ShieldGemma-as-Jev | 读取原生 `Yes / No` Logits，逐政策归一化 | 各项图像政策的违规概率 |

文字分支同时保留官方格式生成的风险类别。图像各政策互相独立，不将三项违规概率归一化为总和为一的分布。

`guard_scores` 保留原始对数分数、概率、评分方式及模型版本。校准工件按模型、版本和政策独立匹配；文字等级和图像政策不进行简单概率平均。完整判定语义见 [请求与结果说明](docs/REVIEW_SEMANTICS.md)。

---

## 审核接口

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 进程健康检查 |
| `GET /ready` | 两个模型分支的就绪情况 |
| `GET /v1/policy` | 规则、路由和决策配置 |
| `POST /v1/reviews` | 提交独立审核请求 |
| `GET /docs` | 交互式接口文档 |

```json
{
  "content": {
    "title": "高等数学复习笔记",
    "text": "整理极限与导数的基本概念。",
    "images": []
  },
  "rights": {
    "basis": "original",
    "copyrightOwner": "投稿作者",
    "attested": true
  }
}
```

图片采用 `{"id":"preview","data":"data:image/png;base64,..."}`，支持 PNG、JPEG 和 WebP，最多四张。单张上限为 4 MiB、1200 万像素，HTTP 请求上限为 24 MiB。

| 主要字段 | 内容 |
| --- | --- |
| `decision` / `decision_reasons` | 审核建议与触发原因 |
| `guard_scores` | 按模型、模态、输入和政策组织的概率 |
| `model_assessment` | 文字原生安全等级和风险类别 |
| `model_attempts` | 实际调用的分支、门槛、耗时及结果 |
| `coverage` / `ocr_attempts` | 覆盖范围与 OCR 状态 |
| `findings` / `copyright` | 安全信号、声明与参考匹配分析 |

---

## 测试与评测

```bash
.venv/bin/pytest -q
.venv/bin/ruff check review_jev tests/test_review*.py
.venv/bin/review-jev evaluate examples/evaluation.jsonl --backend demo
```

文字实模及临时本机 HTTP 冒烟测试：

```bash
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -m review_jev.smoke --text-only --http \
  --output artifacts/dual-guard-text-smoke.json
```

去掉 `--text-only` 可验证全部分支，需要准备图像模型权重和 OCR 依赖。原生分布评测样例见 `examples/guard-evaluation.jsonl`，支持准确率、NLL 和 Brier 指标。

---

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [请求与结果说明](docs/REVIEW_SEMANTICS.md) | 路由、概率语义、融合规则和覆盖状态 |
| [配置说明](docs/CONFIGURATION.md) | 模型、设备、OCR、校准工件和环境变量 |
| [验证记录](VALIDATION.md) | 自动化测试与实模验证边界 |
| [来源与许可](UPSTREAM.md) | 历史来源、参考实现与许可证 |

代码采用 [Apache-2.0](LICENSE) 许可。历史 OneJev 工具与原文保留用于来源追踪，不参与当前双 Guard 审核运行链路。
