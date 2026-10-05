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

文字分支使用 Qwen 的 Qwen3Guard-Gen-0.6B，含图片的投稿使用 OneJev-4B；默认模型版本固定在 `review_jev/config.py`。结构化结果同时保留原生类别、规则结果与实际推理后端。

本目录是 StudyHub 改造版本，新增代码采用 Apache-2.0 许可，不属于 OmniJev 或 TypeSafe 的官方发行版。

---

## 许可关系

`qev/answers.py` 保留 TypeSafe 适配器置信度公式的原始声明：MIT License，Copyright (c) 2026 TypeSafe AI。

底层模型、数据集和媒体素材的许可与代码许可分别适用。Apache-2.0 代码许可不授予用户投稿资料或上游训练媒体的再分发权。

模型使用与验证情况见 [VALIDATION.md](VALIDATION.md)，原始上游说明见 [README.onejev.md](README.onejev.md)。
