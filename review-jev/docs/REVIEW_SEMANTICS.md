# Review-Jev 请求与结果说明

本文件说明双 Guard 的输入、概率语义、规则融合与评测边界。

---

## 输入与内容路由

文字字段为 `title`、`description`、`text`、`customPreviewText`，图片为经过解码校验的 PNG、JPEG 或 WebP 数据 URI。正文与 OCR 文字均作为不可信投稿内容，不能覆盖模型政策。

| 内容 | 实际调用 |
| --- | --- |
| 只有文字 | Qwen3Guard |
| 图片且 OCR 成功、未检出文字 | ShieldGemma |
| 文字配图 | 文字和图片分别审核 |
| 图片检测到文字 | OCR 文字加入文字分支，图片仍进入图片分支 |

OCR 在本地运行；识别出的正文不回显到审核响应。响应仅保留图片 ID、字符数、识别状态与分数。失败、禁用、低识别分数与“成功但为空”是不同状态。

当前 API 不直接接收 PDF。扫描件可转成页面图片提交；独立知识库的 PDF 解析入口见 [知识服务配置](../../studyhub-agent/docs/KNOWLEDGE.md)。

---

## Guard-as-Jev 评分

### 文字安全等级

保持 Qwen 官方审核模板，并在 `Safety:` 后分别对三个完整候选标签及换行结束符计算序列条件对数概率。多 Token 标签逐 Token 累加，不只读取首 Token，也不把长度平均伪装成序列概率。

候选集合内通过 Softmax 归一化，返回三分类分布。该分布是相对候选偏好；模型原生 `Categories` 通过同一 Backbone 的生成接口保留，不从三个安全等级推导各风险类别的概率。

候选最大值与官方生成等级不一致时输出 `native_label_disagreement`；高概率 `Controversial` 也进入人工复核。

### 图像政策

固定使用官方 `sexual`、`dangerous`、`violence` 三项政策。每张图、每条政策产生独立的 Yes/No 分布，`Yes` 表示违反该政策。

实际分类器 Logits 顺序是 `[Yes, No]`。不使用上游说明中写反列号的示例，不将三条政策的 Yes 分数再一起归一化。每张图片单独组成三个政策样本，避免多图批次的归属错位。

自定义校园政策不会被拼进 ShieldGemma 提示中。文字侧的版权类别也仅是原生风险标签，不等于投稿权属已经被验证。

---

## 标准概率接口

每项 `guard_scores` 包含：

| 字段 | 语义 |
| --- | --- |
| `model` / `model_revision` | 实际权重身份 |
| `modality` / `input_id` | 文字汇总或具体图片 |
| `policy_id` | 文字安全等级，或某条图像政策 |
| `task_type` | `multiclass` 或 `binary` |
| `scoring_method` | 完整候选续写评分或原生 Yes/No |
| `log_scores` | 模型实际对数概率或原生候选 Logits |
| `probabilities` | 当前评分温度下的未校准候选分布 |
| `calibrated_probabilities` | 匹配校准工件后得到的分布，可为空 |
| `calibration_id` / `calibrated` | 校准工件身份与应用状态 |

三分类概率和每项二分类概率均单独验证键集合、有限数值、归一化及模型身份。缺失政策、重复结果、图片 ID 错配、分数与 Logits 不一致时，整个相应分支无效。

---

## 规则融合与人工复核

两个分支不会互相替代，也不对跨模态风险求平均。

- 文字分支使用候选最大值检查不确定性；图片分支要求每张图的每项政策都满足分支置信度门槛。
- 安全等级 `Unsafe` 和图像违规概率分别形成风险信号；默认复核门槛为 `0.35`，拒绝信号门槛为 `0.95`。
- 低置信度、原生等级分歧、`Controversial`、必需模态未覆盖或模型异常均转人工，不尝试 4B / 9B 升级。
- 自动通过和自动拒绝仍由独立开关控制。未覆盖的自定义规则阻止自动通过。
- 已完成分支的证据在另一支失败时仍保留，整体标为降级，不能用另一支的安全输出替代。
- 版权独有风险不因文字 `Unsafe` 等级被升级为自动拒绝。

这些门槛是开发配置，不表示经过验证的真实违规概率或统一模型正确率。修改规则文件不会改变 Guard 原生训练政策；未支持的自定义检查明确返回 `unavailable`。

---

## 审核响应

`model_attempts` 记录实际执行的文字或图像分支，不再表示按参数规模升级的轨迹。`coverage` 区分 `completed`、`unavailable` 和 `not_requested`。

只有一个模型分支时，顶层 `confidence` 为该分支候选分布的置信度代理；双分支时为 `null`，应读取各分支与各政策分数。用量汇总实际模型调用，文字候选评分的前向计算也计入输入用量。

`status` 为 `completed`、`partial`、`degraded` 或 `demo`。`decision` 为 `approve`、`manual_review` 或 `reject`。原生安全政策完成但仍有自定义规则未覆盖时，可返回 `partial`。

---

## 版权辅助与参考匹配

保留原创、授权、公共领域及开放许可声明检查；包含署名、NC / ND 条件、授权信息和来源要求。对调用方提供的参考文本进行规范化、长文本包含及 Shingle 比较，对图片原文件进行 SHA-256 比较。

声明不是已核实证据；参考匹配与原生版权标签是人工核验线索，不是版权归属或侵权判定。接口不执行外部权利库检索。

---

## 评测格式

历史 `expected_risks` 用于独立规则分类器；原生 Guard 分布使用 `expected_guards`：

```json
{
  "request": {"content": {"text": "合成学习笔记"}},
  "expected_guards": [{
    "modality": "text",
    "input_id": "submission",
    "policy_id": "text_safety",
    "label": "Safe"
  }]
}
```

图像标签为对应图片 ID、政策 ID 和 `Yes / No`。原生分布按任务分别统计准确率、NLL、Brier；未返回的目标单独记录。演示与降级样本不冒充有效模型测量。校准集和测试集应按来源文档隔离，避免同一文档的页面分散造成泄漏。
