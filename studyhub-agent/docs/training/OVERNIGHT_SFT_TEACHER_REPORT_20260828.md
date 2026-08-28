# StudyHub 9B Overnight SFT and Teacher Data Correction

Date: 2026-08-28

## Result

The bounded 9B SFT baseline completed all 2,100 authorized optimizer updates. The training and recovery infrastructure worked, but the frozen 51-task Development comparison did not show an Agent capability improvement. Strict success moved from 6/51 to 4/51, with 2 paired wins, 4 paired losses, and 45 ties. The paired confidence interval crossed zero and the observed direction was negative.

The Teacher-to-Hermes pipeline also ran against public training tasks. Twenty Spark rollouts and six failed authorized-endpoint probes produced 26 raw runs. Two rows passed the objective verifier; Codex self-review excluded one factual false positive, leaving one teacher row eligible for the v3.1 candidate. This is far below the 500-row minimum useful target, so v3.1 remains candidate-only.

No RL, Reward v3 main training, Sealed split, external benchmark model evaluation, Benchmark modification, or general Hermes refactor was performed.

## Frozen Inputs

| Item | Value |
| --- | --- |
| Training commit | `9cc7b0421f50a9ffd4c2ecb363cff56c5c77eaf0` |
| Base model | `Qwen/Qwen3.5-9B` |
| Model revision | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` |
| Dataset | `studyhub-runtime-sft-v3-qwen35-9b` |
| v3.0 selected SHA-256 | `a115d220841a0e56c8893a01e486c8399c24cb591143f221c78a926deee42783` |
| Benchmark | `StudyHub AgentBench v2.0.0` |
| Benchmark SHA-256 | `da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b` |
| AReaL commit | `cbff54d645d2cd8ee1f1c358a82f3f473588433d` |
| Hermes commit | `5c1a304ce890276a4334d8ced3f29ffeedbbbf93` |

Benchmark v2 remained frozen. Development was used; Sealed-A and Sealed-B were not read or executed.

## Engineering Profile

| Recipe | Status | Mean step | Total tok/s | Assistant tok/s | GPU peaks |
| --- | --- | ---: | ---: | ---: | --- |
| r16 / alpha16 | PASS | 9.438 s | 1,032.31 | 148.73 | 62,469 / 45,943 MiB |
| r32 / alpha32 | PASS | 9.257 s | 1,052.49 | 151.63 | 62,783 / 46,257 MiB |

Both five-update profiles were stable. r16 remained the pre-authorized lower-capacity engineering baseline. The profile did not evaluate downstream quality, and the five-step loss was not used to rank LoRA recipes.

## SFT Run

Run ID: `overnight-r16-v30-seed-20260827-attempt-20260828_020420`

| Metric | Value |
| --- | ---: |
| Wall interval | 02:04:26 to 07:39:28 CST |
| Trainer elapsed | 19,995.15 s |
| Optimizer updates | 2,100 |
| Sequences | 16,800 |
| Total tokens | 21,318,410 |
| Assistant-loss tokens | 3,138,019 |
| Assistant fraction | 14.72% |
| Total token throughput | 1,117.24 tok/s |
| Assistant-loss throughput | 164.45 tok/s |
| Dual-GPU hours / 1M assistant tokens | 3.38 |
| Recovery checkpoints | 10 |
| GPU 0 peak | 62,693 MiB |
| GPU 1 peak | 46,171 MiB |

Loss moved from 0.51857 on the first batch to 0.21011 on the final batch; the 2,100-update mean was 0.12411. Gradient norm had mean 0.25601 and maximum 1.5729. Every update reported success. These are optimization diagnostics, not Agent quality evidence.

The initial LoRA SHA-256 was `42e4a35fad189ac42637e1ee693e3342a4ba8145ed2919ed0ff1ac45372e4569`; the final SHA-256 was `f216c5552b6ad886fe860f5fcb419205144624f7069bc5e2f4f3595d28c943a3`. Parameter updates were observed, and the completion/evidence contract reported no missing artifacts.

## Development Comparison

| Metric | Base | SFT | Delta |
| --- | ---: | ---: | ---: |
| Strict success | 11.76% (6/51) | 7.84% (4/51) | -3.92 pp |
| Mean diagnostic | 0.28376 | 0.24935 | -0.03441 |
| Mean tool calls | 2.882 | 2.275 | -0.608 |

Paired strict outcomes were 2 wins, 4 losses, and 45 ties. The strict delta 95% bootstrap interval was `[-13.73 pp, +5.88 pp]`; the diagnostic delta interval was `[-0.13235, +0.05784]`. Both crossed zero. With an approximate 17.865 percentage-point MDE, the correct conclusion is:

`NO_RELIABLE_IMPROVEMENT_DETECTED_DIRECTION_NEGATIVE`

The checkpoint made fewer invalid citations (11 to 7), fewer `source_not_discovered` errors (6 to 4), and slightly improved aggregate tool validity. These gains did not compensate for losses in strict task completion. Factual passage retrieval fell from 3/16 to 1/16, and the single state multistep success was lost; one stop-cost-control task changed from failure to success. Per-capability counts are too small for broad claims.

## Teacher Data

Spark became available through the supported Codex CLI after 06:34 CST. The bounded smoke used ten public training tasks and two candidates per task. Hermes validated actions and dispatched real frozen-environment tools; hidden Benchmark and Sealed content were unavailable.

| Metric | Value |
| --- | ---: |
| Spark tasks | 10 |
| Spark rollouts | 20 |
| All raw runs | 26 |
| Objective accepted | 2 |
| Objective rejected | 24 |
| Overall objective acceptance | 7.69% |
| Codex self-review approved | 1 |
| Reported input tokens | 394,706 |
| Reported output tokens | 102,465 |
| Estimated cost | NOT_AVAILABLE |

The dominant failures were incomplete Search/Read/Fetch sequences, citations not grounded in an observed Read/Fetch result, provider execution failures, and invalid state-tool calls. Six authorized Xiaomi endpoint probes failed authentication, six Spark runs reported `codex_exec_failed`, and one Spark run attempted a prohibited isolation tool event; all were rejected.

The objective verifier initially passed two answers to the same direct task. Codex self-review found one factual mismatch that lexical overlap had missed and excluded it. All 24 objective rejections were upheld. This review covered every available row but could not meet the requested 50 accepted / 50 rejected sample because the population was only 2 / 24. It is explicitly self-review, not human review.

## v3.1 Candidate

The rebuilt candidate remains 48,500 rows and preserves v3.0. It contains one self-review-approved teacher row, limits action-only rows to 2,425 (5%), has zero train/validation/holdout group overlap, zero public Benchmark prompt overlap, and did not read Sealed task files.

Status: `PASS_CANDIDATE_ONLY_INSUFFICIENT_TEACHER`

Candidate SHA-256: `e97058c1f26a403855ca0eccf388d472e9dbe507eb34b5ba444f1333cc804d81`

This is not a formal v3.1 release. The next data iteration should first fix tool-using teacher trajectory quality and citation grounding; it should not scale the current 5% self-review-approved Spark yield.

## Artifacts

- Completion marker: `artifacts/areal/checkpoints/chengjin/studyhub-runtime-sft-v3-9b/overnight-r16-v30-seed-20260827/OVERNIGHT_SFT_BASELINE_COMPLETE.json`
- Training evidence: `artifacts/experiments/overnight-r16-v30-seed-20260827-attempt-20260828_020420/`
- Merged model: `/data/chengjin/studyhub/models/P1/Qwen3.5-9B-runtime-sft-v3-overnight-r16`
- SFT Development run: `artifacts/benchmark-v2/runs/qwen35-9b-overnight-sft-v2-development-seed-20260827-20260828_074542/`
- Paired comparison: `artifacts/benchmark-v2/comparisons/base-vs-overnight-sft-v3-development.json`
- Teacher raw/audit data: `datasets/interim/studyhub_teacher_v1/`
- Machine-readable tracked summary: `docs/training/evidence/overnight-sft-teacher-20260828.json`

Raw checkpoints, trajectories, logs, model shards, and GPU telemetry remain Git-ignored. Tracked evidence contains hashes, aggregate metrics, limitations, and no credentials.

## Explicitly Not Run

- GRPO, PPO, DAPO, OPD, KDRL, and other RL: `NOT_RUN`
- Reward v3 main training: `NOT_RUN`
- Sealed-A / Sealed-B: `NOT_RUN`
- External benchmark model evaluation: `NOT_RUN`
- Local best-of-N teacher: `NOT_RUN_GPU_RESERVED`
- Development variance rerun: `NOT_RUN_TIME_BUDGET`
