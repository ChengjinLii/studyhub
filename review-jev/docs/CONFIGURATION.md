# Review-Jev 配置说明

默认架构为按内容分流的双 Guard，组件版本为 `0.4.0`。

---

## 推理后端

| 后端 | 说明 |
| --- | --- |
| `auto` | 按正文、图片及 OCR 结果选择所需分支 |
| `qwen3guard` | 仅使用文字模型，其他必需模态标为未覆盖 |
| `shieldgemma2` | 仅使用图片模型，不将正文当作图片政策 |
| `demo` | 模拟结果，便于验证接口 |

`onejev-http`、旧 `torch` 后端及 9B 级联参数已从审核入口移除。安装依赖的 `.[torch]` 名称仍表示 PyTorch 推理依赖，不表示 OneJev 后端。

默认模型在 `review_jev/config.py` 固定权重版本。自定义模型目录或标识不会继承默认模型的 revision；应自行指定对应版本。ShieldGemma 是受限访问模型，需先在 Hugging Face 获批并在本机配置访问凭据。

---

## 环境变量

| 变量 | 默认值或含义 |
| --- | --- |
| `REVIEW_JEV_BACKEND` | `auto` |
| `REVIEW_JEV_MODEL` | `google/shieldgemma-2-4b-it`；固定文字后端默认使用 Qwen Guard |
| `REVIEW_JEV_MODEL_REVISION` | 默认模型的固定版本 |
| `REVIEW_JEV_TEXT_MODEL` | `Qwen/Qwen3Guard-Gen-0.6B` |
| `REVIEW_JEV_TEXT_MODEL_REVISION` | 默认文字模型的固定版本 |
| `REVIEW_JEV_DEVICE` | `auto`，选择空闲显存最多的 CUDA 设备，否则 CPU |
| `REVIEW_JEV_TEXT_DEVICE` | `cpu` |
| `REVIEW_JEV_TEXT_CONFIDENCE_THRESHOLD` | `0.85`，文字分支候选分布门槛 |
| `REVIEW_JEV_IMAGE_CONFIDENCE_THRESHOLD` | `0.85`，每张图片各政策均须满足的门槛 |
| `REVIEW_JEV_TEXT_TEMPERATURE` | `1`，未校准的文字评分温度 |
| `REVIEW_JEV_IMAGE_TEMPERATURE` | `1`，未校准的图像评分温度 |
| `REVIEW_JEV_CALIBRATION_PATH` | 可选的校准工件 JSON 文件 |
| `REVIEW_JEV_OCR_BACKEND` | `tesseract`，也支持显式 `disabled` |
| `REVIEW_JEV_OCR_LANGUAGES` | `chi_sim+eng` |
| `REVIEW_JEV_OCR_TIMEOUT_SECONDS` | `15` 秒，单张 OCR 子进程超时 |
| `REVIEW_JEV_OCR_MIN_CONFIDENCE` | `0.6`，按最低识别词分数检查 |
| `REVIEW_JEV_MAX_OCR_CHARACTERS` | `20000`，单张 OCR 字符上限 |
| `REVIEW_JEV_MAX_INPUT_TOKENS` | `8192`，超限转人工，不静默截断 |
| `REVIEW_JEV_TIMEOUT` | `120` 秒，文字生成的软时间限制 |
| `REVIEW_JEV_POLICY` | 可选的本地投稿规则文件 |
| `REVIEW_JEV_API_KEY` | 可选的 Bearer API 密钥 |
| `REVIEW_JEV_ALLOW_AUTO_APPROVE` | `false` |
| `REVIEW_JEV_ALLOW_AUTO_REJECT` | `false` |
| `REVIEW_JEV_CONCURRENCY` | `2`，超出容量返回 503 |

应用不自动读取 `.env`；需要在终端显式导出。旧级联环境变量不再参与路由，旧 CLI 参数会被拒绝。

---

## OCR 依赖

Tesseract 通过系统可执行文件运行，不属于新增的安全模型。安装 `tesseract-ocr` 及 `chi_sim`、`eng` 语言数据后，可用以下命令检查：

```bash
tesseract --version
tesseract --list-langs
```

服务只向 OCR 子进程的标准输入传入已解码校验、统一为可见 RGB 的图片，不使用投稿提供的 URL 或文件路径。可执行文件缺失、语言包缺失、超时、异常 TSV 和字符超限均为 `unavailable`，不能解释为未检出文字。

`--ocr-backend disabled` 可用于专项图像实验，但响应会明确记录 OCR 未覆盖，不能自动通过。

---

## 校准工件

以下是格式示例，不是已经拟合的校准参数：

```json
{
  "version": 1,
  "entries": [{
    "model": "Qwen/Qwen3Guard-Gen-0.6B",
    "model_revision": "fada3b2f655b89601929198343c94cd2f64d93cc",
    "policy_id": "text_safety",
    "calibration_id": "示例工件标识",
    "dataset_id": "独立标注校准集标识",
    "temperature": 1.2
  }]
}
```

图像工件按 `sexual`、`dangerous`、`violence` 分别配置。模型、revision 和政策必须同时匹配才应用；校准后的分布写入 `calibrated_probabilities`，原始 `probabilities` 与 `log_scores` 保留。仅修改评分温度不会将 `calibrated` 标为真。

当前支持加载外部拟合工件，不自动拟合温度，也不附带声称已经完成 StudyHub 校准的参数。

---

## 就绪与服务

`/health` 检查进程存活；`/ready` 返回文字与图片模型各自的加载状态。自动模式两个分支都加载后整体就绪，但纯文字请求仍可在图片分支尚未加载时独立执行。

默认监听 `127.0.0.1:8011`。CLI 绑定非回环地址前要求配置 API 密钥。模型版本、规则、门槛和自动决策开关均为服务端配置，投稿请求不能覆盖。

本地模型加载和前向计算不受 `REVIEW_JEV_TIMEOUT` 硬中断；需由进程隔离、任务队列和外部超时承担部署层控制。
