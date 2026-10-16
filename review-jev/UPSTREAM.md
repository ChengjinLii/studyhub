# Review-Jev 来源与许可

本文记录上游快照、StudyHub 改造内容和许可证关系。

---

## 上游来源

| 项目 | 信息 |
| --- | --- |
| 来源 | [OmniJev / OneJev](https://github.com/OmniJev/OneJev) |
| 复制版本 | `81ce62f1597c91e46767d4d02d6ac2e18534fe94` |
| 上游提交日期 | 2026-10-01 |
| 复制日期 | 2026-10-05 |
| 代码许可 | Apache-2.0，保留在 [LICENSE](LICENSE) |

快照通过 `git archive` 复制，不包含嵌套 Git 仓库或模型权重。原有 `qev/`、`train/`、基准、样例、素材与测试保留为推理实现和参考资料，上游 README 保存在 `README.onejev.md`。

---

## StudyHub 改造

新增内容包括：

- `review_jev/` 审核流程与规则实现。
- `tests/test_review*.py` 自动化测试。
- 投稿与评测样例、中文文档。
- 面向审核组件的打包配置与忽略规则。

早期版本采用 Qwen3Guard 与 OneJev 级联。自 `0.4.0` 起，审核运行链路替换为按内容路由的双 Guard：Qwen3Guard-Gen-0.6B 使用完整候选续写评分，ShieldGemma 2-4B 使用原生政策 Yes/No Logits。OneJev 4B / 9B 不再参与审核推理；保留上游 SDK 与原文用于历史来源及许可追踪。

---

## 当前参考实现

| 组件 | 官方来源 |
| --- | --- |
| 文字模型、输入模板及风险类别 | [Qwen3Guard 模型说明](https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B) |
| 图像模型与三项政策 | [ShieldGemma 2 模型说明](https://ai.google.dev/gemma/docs/shieldgemma/model_card_2) |
| 图像处理与 Yes/No 列顺序 | [Transformers ShieldGemma 2](https://github.com/huggingface/transformers/tree/main/src/transformers/models/shieldgemma2) |

Guard-as-Jev 表示候选概率评分适配方式，不表示修改了原始权重或增加了新的模型分类能力。模型权重不随代码分发，其使用条件以各模型发布方的许可为准。

本目录是 StudyHub 改造版本，新增代码采用 Apache-2.0 许可，不属于 OmniJev 或 TypeSafe 的官方发行版。

---

## 许可关系

`qev/answers.py` 保留 TypeSafe 适配器置信度公式的原始声明：MIT License，Copyright (c) 2026 TypeSafe AI。

底层模型、数据集和媒体素材的许可与代码许可分别适用。Apache-2.0 代码许可不授予用户投稿资料或上游训练媒体的再分发权。

模型使用与验证情况见 [VALIDATION.md](VALIDATION.md)，原始上游说明见 [README.onejev.md](README.onejev.md)。
