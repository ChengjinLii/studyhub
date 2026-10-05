# Review-Jev 验证记录

验证日期：2026-10-05。

本次验证使用自建样例，覆盖模型推理、自动分流、临时本机 HTTP 服务与独立安装。HTTP 服务使用随机本机端口，测试完成后关闭。

---

## 模型与运行环境

| 项目 | 配置 |
| --- | --- |
| 文字模型 | `Qwen/Qwen3Guard-Gen-0.6B` |
| 文字模型版本 | `fada3b2f655b89601929198343c94cd2f64d93cc` |
| 图文模型 | `OmniJev/OneJev-4B` |
| 图文模型版本 | `c88e18653ceb7a8770716287f55fdefc79d6b588` |
| Python | 3.12 |
| PyTorch / torchvision | 2.9.1+cu129 / 0.24.1+cu129 |
| Transformers / Accelerate | 5.18.0 / 1.15.0 |
| safetensors | 0.8.0 |
| FastAPI / Uvicorn / Pillow | 0.142.2 / 0.54.0 / 12.3.0 |
| 文字推理 | CPU，四线程 |
| 图片推理 | NVIDIA H100 PCIe，根据空闲显存自动选择 `cuda:1` |

OneJev 权重按官方 SHA-256 校验：

```text
c725978346bb87ff598b04b6ffe7ea89461368e9b20a0081a3c6a85d377c8f91
```

权重下载后使用 `HF_HUB_OFFLINE=1` 推理。模型权重和生成报告不纳入 Git。

---

## 自动化检查

| 检查 | 结果 |
| --- | --- |
| 源码环境单元测试 | **135 项通过，3 项跳过** |
| 非 editable wheel 环境 | **134 项通过，4 项跳过**，Python 3.13.5 |
| 代码与文件检查 | Ruff、空白检查、敏感文件检查通过 |
| 独立安装 | wheel 构建与安装通过 |

源码环境跳过的三项上游 SDK 测试需要运行中的 OneJev 服务。wheel 环境未安装模型推理依赖，另有一项测试因缺少可选 Transformers / Torch 而跳过。

---

## 模型与接口验证

五个真实模型样例通过：中文学习笔记、文字隐私风险、文字配图、纯图片和两张图片。三个含图样例均返回十一项有限范围的规则概率。

两个本机 HTTP 样例覆盖文字和图文分流。两个模型加载完成后，`/ready` 返回就绪；测试结束后未保留服务进程。自动通过与自动拒绝均使用默认关闭配置。

复现命令：

```bash
HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false \
  .venv/bin/python -m review_jev.smoke --http --output artifacts/smoke.json
```

首次下载模型时移除 `HF_HUB_OFFLINE=1`。

---

## 观察与适用范围

| 项目 | 观察 |
| --- | --- |
| 文字分类 | 正常笔记识别为 `Safe`，合成隐私样例识别为 `Unsafe / PII` |
| 操纵样例 | 另一条要求审核器忽略规则的样例未被识别，已记录为漏检 |
| 文字规则覆盖 | 返回 `partial`，原生类别与自定义规则的关系见 [结果说明](docs/REVIEW_SEMANTICS.md) |
| 图片推理耗时 | 热请求约 3–7 秒，首次加载和预热约 41 秒 |
| 推理内核 | 使用 PyTorch 参考内核，未启用 `causal_conv1d` 或 `flash-linear-attention` |

此次结果用于证明开发链路可运行。模型尚未针对 StudyHub 训练或校准；医学教学图、出版社扫描件和中文截图需在目标样本上单独评测。合成样例的耗时也不作为服务延迟承诺。

版权辅助检查的范围、原生类别与概率指标的统计方式见 [请求与结果说明](docs/REVIEW_SEMANTICS.md)。本次未使用真实投稿或访问生产系统。
