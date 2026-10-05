# Review-Jev 请求与结果说明

本文说明输入格式、模型输出、判定语义与版权辅助分析。

---

## 投稿输入

| 部分 | 字段与用途 |
| --- | --- |
| 内容 | `title`、`description`、`text`、`customPreviewText`、`images` |
| 场景 | `context.kind`、发布方式、学校、课程与标签 |
| 版权声明 | 原创或授权依据、版权持有者、来源、许可、署名与修改情况 |
| 参考内容 | 调用方提供的文本或图片 SHA-256 参考集合 |

`context.kind` 支持 `material`、`experience`、`comment`、`request` 和 `marketplace`。输入按公开投稿处理。

`rights.basis` 支持 `original`、`authorized`、`open_license`、`public_domain` 和 `unknown`。

### 图片格式

图片使用 `{"id":"preview-1","data":"data:image/png;base64,..."}`。

| 项目 | 要求 |
| --- | --- |
| 格式 | PNG、JPEG、WebP 的 base64 data URI |
| 张数 | 最多四张，图片 ID 唯一 |
| 单张大小 | 原文件不超过 4 MiB、1200 万像素 |
| 请求大小 | HTTP 请求不超过 24 MiB |
| 解码处理 | 移除元数据、应用方向信息、透明像素合成到白底 |

图片输入不接受 URL、服务器路径、SVG 或动图。正文中的路由指令不影响模型选择；图片推理失败时不会改用文字模型声称已完成图片审核。

### 参考内容

最多五项参考，每项包含 `id`，以及 `text` 或 `image_sha256`。文本采用规范化包含检查和字符 shingle 重叠；图片使用原文件字节的 SHA-256 匹配。短引文不会直接触发参考匹配。

---

## 模型与规则

| 分支 | 输出 | 规则方式 |
| --- | --- | --- |
| Qwen3Guard-Gen-0.6B | `Safe`、`Controversial`、`Unsafe` 与原生类别 | 原生类别映射到部分 StudyHub 风险项 |
| OneJev-4B | 各项规则的风险概率 | 按十一项 StudyHub 规则进行图文推理 |

文字分支不执行自定义规则提示，不生成逐项概率。未支持的规则使用 `outcome=unavailable`，整体状态为 `partial`；`model_assessment` 保留原生判断。图文概率由 OneJev 实际提供，尚未完成 StudyHub 场景校准。

Qwen3Guard 的 0.6B 与 4B 均为文字模型，图片分支使用多模态 OneJev-4B。

---

## 结果解释

| 字段 | 语义 |
| --- | --- |
| `decision` | `approve`、`manual_review`、`reject`，表示审核建议 |
| `status` | `completed` 为完成，`partial` 为部分完成，`degraded` 为降级，`demo` 为演示 |
| `findings` | 独立规则结果及作用范围 `scope`，文字或整个投稿 |
| `risk_probability` | 后端提供的真实概率；没有概率时为 `null` |
| `model_assessment` | 文字分支的原生等级、类别与适用范围 |
| `model` / `backend` / `model_revision` | 实际推理模型、后端与版本 |
| `copyright.status` | `no_obvious_risk`、`needs_review` 或 `undetermined` |
| `calibrated_for_studyhub` | 当前为 `false`，表示尚未完成场景校准 |

`findings.reason` 是判定说明，不是投稿内容的证据摘录。内容、原图片与规则 SHA-256 用于追踪结果和复现评测。

---

## 版权辅助分析

检查包括声明完整性、署名、授权说明、开放许可、付费与 NC 条件冲突、修改与 ND 条件冲突，以及有限参考内容的相似性或哈希匹配。

输出属于风险筛查：声明、标识、水印或参考相似性不能单独证明权利归属或侵权；版权疑点进入复核，不由该模块自动拒绝。参考检查不打开来源链接，也不执行全网搜索或授权文书核验。

本模块处理文字和图片，不解析 PDF、Office 或压缩包；附件恶意软件扫描属于其他处理流程。

---

## 门禁与评测

自动通过、自动拒绝默认关闭。部分覆盖、推理失败、非法概率、演示结果和版权疑点不能作为自动通过依据；开启自动建议门禁时仍保留这些约束。

评测报告将两类输出分别统计：

- `per_rule`：完整真实推理结果的概率指标，包括 Brier 与 ECE。
- `per_rule_labels`：文字模型原生类别的分类指标，排除未支持规则及含图片的文字后端结果。

人工标注的校园投稿样本用于衡量误杀、漏检、概率校准和人工复核比例。演示数据与冒烟样例用于链路验证，测试记录见 [VALIDATION.md](../VALIDATION.md)。
