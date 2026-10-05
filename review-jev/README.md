# StudyHub Review-Jev

基于 [OneJev](https://github.com/OmniJev/OneJev) 的独立图片与文字投稿审核组件。
目录位于 StudyHub 项目根目录的 `review-jev/`，不导入主站代码，不连接业务 API、数据库、对象存储或支付系统。

这是**独立审核软件与规则层的开发版本**，不是新训练的 StudyHub 模型。默认自动分流：纯文字使用 [Qwen3Guard-Gen-0.6B](https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B)，含图片（含纯图片）使用 [OneJev-4B](https://huggingface.co/OmniJev/OneJev-4B)。没有宣称已经获得 StudyHub 场景的审核准确率或概率校准结果。

## 已实现

- 输入：标题、描述、正文、自定义预览、最多四张图片，以及投稿场景和版权声明。
- 独立风险判定：色情、暴力、仇恨骚扰、违法危害、敏感个人信息、广告与站外支付、学术作弊、审核操纵、第三方复制、版权限制、可读性。
- 版权辅助检查：声明完整性、署名、授权说明、开放许可、付费与 NC 条件冲突、修改与 ND 条件冲突，以及参考文本相似性和图片原文件 SHA-256 匹配。
- 结构化输出：实际模型与后端、权重版本、风险概率或原生分类、建议、规则与内容哈希、版权风险状态、局限说明。
- 独立 FastAPI 服务、JSON CLI、批量评测工具、无需权重的演示模式和自动化测试。

所有版权结论都是**风险筛查**。自称原创、填写版权持有者、提供链接或授权说明，都不等于平台已经验证权利。相似、出现出版社标识或水印，也不等于已经认定侵权。版权疑点只能要求复核，不能由该模块自动拒绝。

## 快速启动

在 `review-jev/` 下执行，Python 3.10+：

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/review-jev serve --backend demo
```

服务默认监听 `127.0.0.1:8011`，接口文档位于 `http://127.0.0.1:8011/docs`。
`demo` 只返回模拟概率，响应明确标记 `status=demo`，无论怎样配置都不会自动通过或拒绝真实内容。

```bash
.venv/bin/review-jev review examples/original-notes.json --backend demo
.venv/bin/review-jev policy
curl --noproxy '*' -s http://127.0.0.1:8011/v1/reviews \
  -H 'Content-Type: application/json' \
  --data-binary @examples/original-notes.json
```

## 默认自动分流

安装真实推理依赖后，不需要另启 OneJev 服务，不需要网站或数据库：

```bash
.venv/bin/pip install -e '.[torch]' -c constraints-tested.txt
.venv/bin/review-jev serve
```

- `content.images` 为空：Qwen3Guard-Gen-0.6B，默认 CPU，按模型原生安全策略审核所有非空文字字段。
- 包含有效图片：OneJev-4B，默认优先 CUDA、无 CUDA 时 CPU；文字和全部图片共同参与 StudyHub 的 11 条规则推理。
- 根据解码验证后的图片分流，不能用正文中的“这是图片/纯文字”指令改变后端。图片模型失败时**不降级成文字审核**。
- 两个模型均按首次对应请求惰性加载；默认固定权重 revision，下载到 Hugging Face 用户缓存，不进 Git。
- `/ready` 在两个模型都成功加载前返回 503；`/health` 只表示进程存活。演示模式不需要权重。

OneJev 是已经微调的通用多模态决策模型，并非专门针对 StudyHub 内容审核训练；本模块用规则将它用于风险筛查。图文概率也不能当作已经在本平台校准的可靠度。

**Qwen3Guard 的 0.6B 和 4B 都是纯文字模型。** 文字分支不执行自定义规则提示、不输出逐项概率；`model_assessment` 保留原始安全等级和类别。类别与部分 StudyHub 规则的映射只是近似风险信号，未支持的规则明确返回 `unavailable`、整体 `status=partial`，即使启用自动门禁也只能人工复核。版权类别不能证明授权。强制文字后端收到图片时也不能宣称已审核图片。

只安装文字依赖或单独测试 0.6B：

```bash
.venv/bin/pip install -e '.[guard]'
.venv/bin/review-jev review examples/original-notes.json --backend qwen3guard --device cpu
```

## 可选 OneJev 后端

方案一：将审核 API 与 OneJev 推理进程分开，便于使用原有 PyTorch 或 GGUF 后端。

```bash
.venv/bin/pip install -e '.[torch]'
.venv/bin/qev serve --model OmniJev/OneJev-4B --host 127.0.0.1 --port 8000
```

另一个终端执行：

```bash
.venv/bin/review-jev serve --backend onejev-http --onejev-url http://127.0.0.1:8000
```

审核服务默认请求上游的 `jev-latest` 别名；如果推理服务使用自定义模型名，可以指定 `--served-model`。
GGUF 使用 `pip install -e '.[gguf]'` 和上游 `qev serve --gguf ...`，需要另外安装 `llama-server`；审核侧仍用 `onejev-http`。

方案二：在审核进程内直接加载 OneJev，第一次审核时加载权重。

```bash
.venv/bin/review-jev serve --backend torch --model OmniJev/OneJev-4B
```

也可传入本地模型目录。此模式在首次成功加载前 `/ready` 返回 503；`/health` 仅表示服务进程存活。
`--backend torch` 强制图文模型处理全部请求；`--backend onejev-http` 使用独立 OneJev HTTP 服务。自动分流也可通过 `--image-backend onejev-http` 将图片分支切换到本机推理服务。实际效果仍必须用目标投稿数据验证。

## 请求和响应

```json
{
  "request_id": "submission-001",
  "content": {
    "title": "Calculus revision notes",
    "text": "My original explanation of limits and derivatives.",
    "images": []
  },
  "context": {"kind": "material", "publication_intent": "FREE"},
  "rights": {
    "basis": "original",
    "copyrightOwner": "Author",
    "attested": true
  },
  "references": []
}
```

图片格式为 `{"id":"preview-1","data":"data:image/png;base64,..."}`。
只接受 PNG、JPEG、WebP 的 base64 data URI，不接受 URL、服务器文件路径、SVG 或动图。
每张原文件最大 4 MiB、1200 万像素，整个 HTTP 请求最大 24 MiB；解码后去除元数据并将透明像素合成到白底，不缩小图片来掩盖小字。
CLI 处理本地 JSON，图片也使用上述格式。

`context.kind` 支持 `material`、`experience`、`comment`、`request`、`marketplace`。
当前输入均视为公开投稿，不把主站私有结算通道的收款码豁免搬到公开内容中。
`rights.basis` 支持 `original`、`authorized`、`open_license`、`public_domain`、`unknown`。

`references` 是调用方提供的有限参考集合，每项包含 `id` 与 `text` 或 `image_sha256`。
图片匹配针对原文件字节，不识别重新压缩、裁剪或改色后的复制；文本采用规范化后的包含和字符 shingle 重叠，不是全网查重，也不是语义抄袭检测。短引文不会直接触发参考匹配。

主要输出：

- `decision`：`approve` / `manual_review` / `reject`，仅建议，不执行任何业务操作。
- `status`：`completed` / `partial` / `degraded` / `demo`，覆盖不全、失败和模拟结果不能被当作完整审核。
- `findings`：独立规则结果及作用范围 `scope`；概率仅在后端真实提供时填写，否则为 `null`。说明不是投稿证据摘录。
- `model_assessment`：文字分支原生 `Safe` / `Controversial` / `Unsafe` 与类别，注明没有读取图片、没有执行自定义 StudyHub 策略。
- `model` / `backend` / `model_revision`：实际分流后的模型、后端和本地权重 revision；路由器不会冒充实际推理后端。
- `copyright.status`：`no_obvious_risk` / `needs_review` / `undetermined`，没有“已确权”状态。
- `calibrated_for_studyhub=false`、规则 SHA-256、内容与原图片 SHA-256，用于将来追踪评测版本。

## 配置与边界

| 环境变量 | 默认值 / 说明 |
| --- | --- |
| `REVIEW_JEV_BACKEND` | `auto`；也支持 `qwen3guard`、`onejev-http`、`torch`、`demo` |
| `REVIEW_JEV_IMAGE_BACKEND` | `torch`；自动分流的图片分支也可选 `onejev-http` |
| `REVIEW_JEV_ONEJEV_URL` | `http://127.0.0.1:8000`，只能由服务端配置 |
| `REVIEW_JEV_MODEL` | `OmniJev/OneJev-4B` 或本地目录；强制 `qwen3guard` 时默认为 0.6B |
| `REVIEW_JEV_MODEL_REVISION` | 默认模型固定 revision；自定义模型默认不固定，可显式配置 |
| `REVIEW_JEV_TEXT_MODEL` | `Qwen/Qwen3Guard-Gen-0.6B`，自动分流的文字模型 |
| `REVIEW_JEV_TEXT_MODEL_REVISION` | 默认文字模型固定 revision |
| `REVIEW_JEV_SERVED_MODEL` | `jev-latest`，HTTP 上游模型名 |
| `REVIEW_JEV_DEVICE` | `auto`，选当前空闲显存最多的 CUDA，否则 CPU；可显式指定 |
| `REVIEW_JEV_TEXT_DEVICE` | `cpu`，自动分流的 0.6B 文字分支使用 |
| `REVIEW_JEV_MAX_INPUT_TOKENS` | `8192`，文字分支不静默截断；图文分支也限制推理输入 |
| `REVIEW_JEV_TIMEOUT` | `120` 秒，HTTP 超时和文字生成软时间限制，不是本地模型加载硬超时 |
| `REVIEW_JEV_POLICY` | 可选，本地规则 JSON 文件路径 |
| `REVIEW_JEV_API_KEY` | 可选，使用 `Authorization: Bearer ...` |
| `REVIEW_JEV_ALLOW_AUTO_APPROVE` | `false`，默认不自动通过 |
| `REVIEW_JEV_ALLOW_AUTO_REJECT` | `false`，默认不自动拒绝 |
| `REVIEW_JEV_CONCURRENCY` | `2`，超出并发容量返回 503 |

先用评测数据校准阈值，再考虑开启自动建议门禁。即使开启，版权风险、不可读内容、缺失声明和未覆盖规则仍进入复核；模型失败、非法概率、非法原生类别也不放行。请求方不能覆盖模型、规则、后端地址或门禁。
监听非本机地址时 CLI 要求设置 API key；生产部署还需 TLS、反向代理限流和请求体/连接超时。当前代码不持久化正文、图片和审核记录，不记录投稿内容；外部反向代理和上游日志需要另外配置。
本模块不替代 StudyHub 原有恶意软件扫描，不解析 PDF、Office、压缩包，不打开网盘或来源链接，不验证授权文书真伪，也不做全网版权检索。

## 测试和评测

```bash
.venv/bin/pytest -q
.venv/bin/ruff check review_jev tests/test_review*.py
.venv/bin/review-jev evaluate examples/evaluation.jsonl --backend demo
```

真实模型冒烟测试（会下载权重，使用自建样例；`--http` 只启动临时本机接口，结束后关闭）：

```bash
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 .venv/bin/python -m review_jev.smoke --http --output artifacts/smoke.json
```

测试包含中文纯文字、隐私风险文字、图文、纯图片、多图片及本机 HTTP 分流。只验证推理链路，不代表审核准确率达标。无真实模型依赖的单元测试和 wheel 打包检查由独立的 `Review-Jev` GitHub Actions 执行，不连接数据库、不部署网站。
本次已完成真实 CPU / GPU 推理、临时本机 HTTP 分流和独立 wheel 安装验证，环境、结果和已知漏检见 [VALIDATION.md](VALIDATION.md)。

演示评测和示例数据仅验证开发链路，不能证明模型效果。真实评测需要人工标注的中文资料截图、正常教材、医学插图、版权争议和隐私泄露样本，并报告误杀率、漏检率、概率校准和人工复核比例。
评测输出可以通过 `--output artifacts/report.json` 保存；默认只打印聚合指标，不保存投稿原文。概率指标只统计完整真实结果；原生类别另在 `per_rule_labels` 统计，排除未支持规则和含图片的文字后端结果，不伪造 Brier / ECE。

来源、许可证和改动边界见 [UPSTREAM.md](UPSTREAM.md)，原 OneJev 说明见 [README.onejev.md](README.onejev.md)。
