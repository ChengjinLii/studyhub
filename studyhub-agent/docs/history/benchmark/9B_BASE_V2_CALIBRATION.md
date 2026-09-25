# Qwen3.5-9B Base v2 Calibration

## Scope

The post-freeze run used one public representative for each of the 30 capability families. It used only `regression`, `development`, and `calibration_challenge`; no Sealed-A or Sealed-B task or grader entered the rollout context. The model was `Qwen/Qwen3.5-9B` at revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, with the pinned Hermes loop and no optimizer step.

## Stratified Gate

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

The machine-readable record is `docs/benchmark/evidence/qwen35-9b-base-gate-20260827.json`.

## Development Baseline

The frozen 51-task Development split was then evaluated once per task at temperature 0. The run produced 51/51 scored episodes, zero infrastructure exclusions, 6 strict successes (11.76%), a mean diagnostic score of 0.2838, and an approximate independent 80%-power MDE of 17.87 percentage points. Source-group, semantic-template, and environment-origin cluster-aware intervals are retained in the raw summary.

| Item | Value |
| --- | ---: |
| Episodes | 51 / 51 scored |
| Infrastructure exclusions | 0 |
| Strict success | 6 / 51 (11.76%) |
| Mean diagnostic score | 0.2838 |
| Mean tool calls | 2.88 |
| Mean / p95 episode latency | 9.03 s / 18.79 s |
| Prompt-cardinality audit | 206 / 206 valid requests |
| GPU peak | 59,603 MiB / 59,476 MiB |

## Variance Panel

The fixed variance panel contains 35 tasks with four stochastic rollouts each. All 140 episodes were scored and every group was complete. Task-level pass@4 was 20.00%, consistent@4 was 5.71%, and 14.29% of tasks had mixed strict outcomes. The panel therefore exposes some within-task policy variance, but most tasks still yield all-failed groups and will require learnability filtering before GRPO.

| Item | Value |
| --- | ---: |
| Groups | 35 / 35 complete |
| Episodes | 140 / 140 scored |
| Infrastructure exclusions | 0 |
| Rollout strict success | 12.14% |
| Pass@4 / Consistent@4 | 20.00% / 5.71% |
| Mixed-outcome tasks | 14.29% |
| Prompt-cardinality audit | 609 / 609 valid requests |
| GPU peak | 59,893 MiB / 60,574 MiB |

The variance run manifest records a dirty working tree because runtime-SFT data scripts were being prepared concurrently. The benchmark manifest, evaluator, runner, model revision, and artifact hashes remained pinned; this limitation is disclosed rather than hidden. A clean rerun is required before treating byte-for-byte variance reproduction as final confirmation.

The combined machine-readable record is `docs/benchmark/evidence/qwen35-9b-base-v2-development-variance-20260827.json`. Raw episodes, summaries, launcher logs, and GPU telemetry remain under ignored `artifacts/benchmark-v2/` and are bound by SHA256 in the committed records. Neither Sealed split nor an external official model evaluator was used.
