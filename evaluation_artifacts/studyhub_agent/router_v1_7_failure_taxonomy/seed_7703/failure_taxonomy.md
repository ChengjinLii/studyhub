# Router 2B 失败分类报告

范围：300 条教师隐藏开发诊断；不是最终封存集，不允许导出训练。

## 总览

| 路径 | 样本数 | 至少一项失败 | 失败率 |
|---|---:|---:|---:|
| normalized | 300 | 169 | 56.33% |
| raw | 300 | 174 | 58.00% |

## 类别计数

| 类别 | normalized | raw |
|---|---:|---:|
| `arguments.filters` | 9 | 12 |
| `arguments.focus` | 22 | 25 |
| `arguments.limit` | 6 | 4 |
| `arguments.max_pages` | 19 | 18 |
| `arguments.other` | 25 | 25 |
| `arguments.page_numbers` | 27 | 19 |
| `arguments.query` | 74 | 76 |
| `contract.invalid` | 16 | 16 |
| `decode.delimiter_or_unescaped_quote` | 9 | 11 |
| `decode.empty_array_item` | 2 | 3 |
| `decode.invalid_json` | 11 | 14 |
| `routing.expected_final_got_tools` | 1 | 1 |
| `routing.expected_tools_got_final` | 19 | 16 |
| `routing.mode_other` | 1 | 3 |
| `routing.tool_mismatch` | 5 | 3 |
| `routing.unparseable` | 14 | 17 |

## 主失败层

每条失败记录只计入最先命中的主失败层，用于避免重叠计数误导。

| 主失败层 | normalized | raw |
|---|---:|---:|
| `bounded_tool_arguments` | 28 | 27 |
| `deterministic_runtime_boundary` | 17 | 16 |
| `output_contract` | 16 | 16 |
| `output_syntax` | 11 | 14 |
| `routing_policy` | 1 | 0 |
| `semantic_tool_arguments` | 69 | 82 |
| `trusted_reference_arguments` | 27 | 19 |

## 修复归属

- `runtime_constraint`：语法、schema、预算、安全边界、可信 ID/页码与有界参数。
- `policy_learning`：语义路由、检索词、memory focus、synthesis 参数和停止策略。
- 同一记录可以同时属于两类；RL 不应学习运行时本可确定保证的字段。

## 解释

- `decode.*`：输出不是严格 JSON，先由受约束输出层处理。
- `contract.*`：JSON 可解析但不满足 Router schema。
- `routing.*`：mode 或只读工具选择错误，属于策略问题。
- `arguments.*`：工具正确但确定性字段发生漂移。
- `policy.*` / `safety.*`：权限拒绝或安全边界失败。

计数允许重叠；同一条输出可同时属于解码、契约和路由失败。
