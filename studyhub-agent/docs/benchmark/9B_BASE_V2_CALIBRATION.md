# Qwen3.5-9B Base v2 Calibration Gate

## Scope

The post-freeze run used one public representative for each of the 30 capability families. It used only `regression`, `development`, and `calibration_challenge`; no Sealed-A or Sealed-B task or grader entered the rollout context. The model was `Qwen/Qwen3.5-9B` at revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, with the pinned Hermes loop and no optimizer step.

## Result

| Item | Value |
| --- | ---: |
| Episodes | 30 / 30 scored |
| Infrastructure exclusions | 0 |
| Strict success | 5 / 30 (16.67%) |
| Mean diagnostic score | 0.3082 |
| Mean tool calls | 3.0 |
| Mean / p95 episode latency | 7.92 s / 18.09 s |
| Prompt-cardinality audit | 126 / 126 valid requests |
| GPU peak | 59,291 MiB / 59,240 MiB |

Strict successes occurred in direct-answer relevance, factual passage retrieval, irrelevant-memory abstention, state function calling, and multi-step state postcondition. Hard gates included eight invalid citations and three attempts to read a source that had not been discovered. Trace inspection attributed these to policy behavior such as citation placeholders, citing search-only results, and guessed or truncated source IDs; no runtime or evaluator exception was observed.

## Interpretation

This run proves that the frozen v2 manifest, dual-SGLang runtime, Hermes tool loop, replay environments, evaluator, prompt-cardinality audit, and evidence capture execute end to end. It is not the full 98-task result and does not measure Sealed-A/B performance. One task per capability is insufficient for stable empirical difficulty, so all tasks remain `UNSCORED`.

The machine-readable record is `docs/benchmark/evidence/qwen35-9b-base-gate-20260827.json`. Raw episodes and GPU telemetry remain under ignored `artifacts/benchmark-v2/` and are bound by SHA256 in that record.
