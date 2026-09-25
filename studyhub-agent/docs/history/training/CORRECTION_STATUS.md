# StudyHub 9B Agentic Training Correction Status

Generated on 2026-08-29 (Asia/Shanghai) from implementation HEAD `9b65cd1` on `main`. The status document itself is committed after that implementation HEAD; the final delivery message records the resulting repository HEAD.

## Decision

```text
BLOCKED_RECOVERY_CONTRACT
```

Open-Only v1.1 formal SFT has not started. The only next GPU action is the `cadence-210` recovery confirmation. Explicit training and recovery-gate authorization was received on 2026-08-29; execution remains pending until its recorded run begins.

## Commits reviewed

The causal audit covers `17b4bc6`, `1eefb5c`, `853fd42`, `cf610d8`, `b20f200`, `765f0cb`, `20f033c`, and every correction commit through `ebf72fe`. Existing failed recovery evidence was retained and not relabeled as success.

## Implemented corrections

- Recovery was split into R1 LR schedule, R2 snapshot integrity, R3 state continuity, and R4 final equivalence.
- Snapshot capture is non-destructive, staged, hash-bound, stability checked, and requires an actual AReaL restart load rather than metadata parsing alone.
- Per-rank Python, NumPy, Torch CPU/CUDA RNG state, dataloader state, and ordered sample/input/loss-mask batch fingerprints are captured and restored.
- R4 distinguishes `BITWISE_RESUME_PASS`, `BOUNDED_NUMERIC_RESUME_PASS`, and `FAIL`; historical exact failures remain visible.
- A fail-closed Mixed-v3.0 versus Open-Only v1.1 control audit verifies model, tokenizer, runtime, optimizer, scheduler, update budget, assistant-loss tokens, cadence, Benchmark hash, and provenance.
- Benchmark promotion now requires control, recovery, paired Development, capability/cost floors, variance, and official BFCL/tau2 evidence. `NOT_RUN` blocks promotion without being mislabeled as model failure.
- External setup/command discovery is separated from formal model orchestration and official scores. No aggregate AgentScore is produced.
- Open-Only data/Benchmark alignment is machine-audited. RAG/evidence is 74.0691% of training assistant-loss tokens versus 56.8627% of Development tasks; Memory, Web, Recovery/ACL, and long-horizon have no direct Open-Only training lane.
- Legacy Teacher reverse replay is frozen out of the mainline. The one-row v3.1 Teacher candidate remains candidate-only and below the 500-row re-entry minimum.
- AgentBench v2.1 has an independent design and public candidate builder. Its status is `DESIGN_READY_DATA_NOT_BUILT`; Sealed generation remains prohibited before final freeze.
- Benchmark manifest validation now defaults to public-only. Hidden integrity validation requires `--include-hidden` and `STUDYHUB_ALLOW_SEALED_VALIDATION=YES`.

## Recovery attribution

| Gate | Current status | Evidence boundary |
|---|---|---|
| R1 LR schedule | `READY_BUT_NOT_RUN_CADENCE_CONFIRMATION` | Historical LR mechanics passed, but the required post-warmup/cadence holdout has not run. |
| R2 snapshot integrity | `IMPLEMENTED_NOT_CONFIRMED_ON_GPU` | Non-destructive source/target hashes, stable inventory, DCP metadata and actual restart load are required. |
| R3 state continuity | `IMPLEMENTED_NOT_CONFIRMED_ON_GPU` | Exact RNG, optimizer, dataloader and batch-fingerprint continuity awaits the cadence run. |
| R4 final equivalence | `FAIL_HISTORICAL_CONFIRMATION_PENDING` | Prior exact comparisons failed; no post-contract cadence holdout has produced bitwise or bounded-numeric PASS. |

The old independent-prefix result remains `INDEPENDENT_PREFIX_REPRODUCIBILITY_FAIL / RECOVERY_CAUSALITY_NOT_ISOLATED`. Shared-prefix exact failures also remain failures. No threshold was widened after those results.

## Controlled SFT

The model-affecting control fields and provenance checks pass. Mixed and Open-Only both use 2,100 updates, 3,138,019 assistant-loss tokens, scheduler horizon 5,456, and 163 warmup steps. The disclosed data-condition difference remains 21,318,410 Mixed total context tokens versus 22,333,694 projected Open-Only tokens.

Formal Open-Only v1.1 training is `NOT_RUN`. Open-Only v1 remains `DIAGNOSTIC_ONLY` because its LR schedule contract failed; its checkpoint and Development result are not reused as v1.1 evidence.

## Local tests

| Command | Result |
|---|---:|
| `.venv-train/bin/pytest -q tests/unit/training` | 182/182 passed; deprecation warnings only |
| `.venv/bin/pytest -q tests/unit/benchmark_v2 tests/unit/external_benchmarks` | 28/28 passed |
| `.venv/bin/python scripts/benchmark/v2/validate_manifest.py --require-frozen` | PASS; 3 public assets, 0 hidden assets checked, 9 quality artifacts |
| Focused Ruff checks for newly changed Python files | PASS |

These are local results. No GitHub CI status is claimed.

## GPU jobs

No GPU job was started during this correction phase. `STUDYHUB_ALLOW_TRAINING`, `STUDYHUB_ALLOW_SFT_RECOVERY_GATE`, and `STUDYHUB_ALLOW_SEALED_VALIDATION` were absent.

The prepared next command is:

```bash
STUDYHUB_ALLOW_TRAINING=YES \
STUDYHUB_ALLOW_SFT_RECOVERY_GATE=YES \
STUDYHUB_RECOVERY_GATE_PROFILE=cadence-210 \
bash studyhub-agent/scripts/train/run_open_only_sft_v1_1_recovery_gate.sh
```

Do not run formal v1.1 SFT unless that gate yields R1 PASS, R2 PASS, R3 PASS, and an accepted R4 status under the already frozen contract.

## Benchmark status

| Evidence lane | Status |
|---|---|
| Base Development | 51/51 scored; strict 6/51 (11.76%); mean diagnostic 0.283758 |
| Mixed-v3.0 Development | 51/51 scored; strict 4/51 (7.84%); mean diagnostic 0.249346 |
| Open-Only v1.1 Development | `NOT_RUN` |
| Base variance | 35 tasks x 4 rollouts complete; pass@4 20%; consistent@4 5.71% |
| Mixed/Open-Only variance | `NOT_RUN` |
| BFCL V4 | setup/command discovery ready; formal model orchestration not verified; scores `NOT_RUN` |
| tau2 | setup/command discovery ready; formal model orchestration not verified; scores `NOT_RUN` |
| BrowseComp-Plus | setup ready; dataset/model evaluation `NOT_RUN` |
| DeepResearch Bench II | `LICENSE_REVIEW_REQUIRED` |
| AgentBench v2.1 Expanded | design/public builder ready; source acquisition and task generation `NOT_RUN` |

Development has an approximate 80% power MDE of 17.865 percentage points and is concentrated in RAG/evidence tasks. It supports directional paired evidence only.

## Sealed and hidden access

Sealed-A/B were not used for model execution, scoring, training, Teacher generation, or model selection. Final Sealed evaluation remains `NOT_RUN`.

One legacy manifest-validation invocation on 2026-08-29 hashed 18 hidden files and checked hidden-manifest binding because hidden validation was then the default. It did not parse task/grader semantics or export content. This process deviation is recorded in `benchmarks/studyhub-agent-v2/HIDDEN_ACCESS_LEDGER.json`, and the default has been changed to public-only.

## RL status

Main GRPO/RL is `NOT_RUN`. Reward v3 remains `PROGRAMMATIC_CONTRACT_CALIBRATION_ONLY`; no free-policy learnability or reward/evaluator divergence gate has passed. RL must not start before the controlled SFT and evaluation chain closes.

## Claim boundary

Supported:

- The corrected recovery, control, governance, and promotion code is locally testable and fail-closed.
- Mixed-v3.0 is a completed negative-direction internal baseline.
- Open-Only v1.1 inputs and model-affecting controls are prepared, with data-condition differences disclosed.
- Current data composition is RAG-heavy and does not directly train several AgentBench capability lanes.

Not supported:

- Open-Only v1.1 improves the model.
- SFT improves broad Agentic ability.
- Recovery is bitwise or numerically equivalent under the cadence contract.
- BFCL, tau2, BrowseComp, or Deep Research performance improved.
- The candidate is ready for RL, Sealed evaluation, deployment, or final freeze.

## Unresolved blockers

1. Authorized `cadence-210` R1-R4 holdout confirmation is not run.
2. Formal Open-Only v1.1 SFT and paired Development are not run.
3. Mixed and candidate variance panels are incomplete.
4. Official BFCL/tau2 model results are absent; external formal orchestration remains unverified.
5. AgentBench v2.1 still needs independent sources, public candidates, independent semantic review, shortcut tests, and freeze.
6. Teacher re-entry requirements are not met.

## Evidence index

| Evidence | SHA-256 |
|---|---|
| `benchmarks/studyhub-agent-v2/manifest.json` | `da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b` |
| `docs/training/evidence/open-only-sft-v1-1-control-diff.json` | `222c158e7408f1a0f023aef6f725497371f063e31dc83caa9fbb6ff64aacc012` |
| `docs/training/evidence/open-only-sft-v1-1-recovery-ready-not-run-20260828.json` | `65620b2bde59159251a471e501540f65e5e7e93499ba93c2ac988dd9eb9604bf` |
| `docs/training/evidence/open-only-sft-v1-1-benchmark-portfolio.json` | `f8bfe4217d85f490a01bd677afe616f2c30af8699dd5953d6aafca5b6c47b47c` |
| `docs/training/evidence/open-only-sft-v1-1-promotion-decision.json` | `20ef207f27b54c8be9ccb2f971fa3513b58984c924f5585f1332a9c1397782b8` |
| `docs/training/evidence/open-only-sft-v1-1-data-benchmark-alignment.json` | `a6292ca159479d408122f18307060f6f5b71597318a5c101d45b4f7640a4e971` |
| `docs/training/evidence/teacher-mainline-policy-audit-20260829.json` | `f4469a57ea0be203b24bb030c4796d2ee1de352d59f7ce2f3a94e4aaee441e08` |
| `docs/benchmark/evidence/agentbench-v2.1-design-preflight-20260829.json` | `9e5117e8cf5f27febe53ad7f2620f2699b6271d48f8fcf939df33c4829e73743` |

## Next unique gate

`cadence-210` recovery confirmation is the only next model-affecting action. Until it passes, the promotion decision remains `BLOCKED_RECOVERY_CONTRACT`.
