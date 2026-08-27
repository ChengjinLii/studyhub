# StudyHub Agent

This directory is isolated from the StudyHub website runtime. The legacy Agent,
training, evaluation, memory, router, and orchestration implementations were
removed before the V2 rebuild.

The only retained historical asset is:

```text
ai_platform/rag_experiments/
```

It is a standalone retrieval research project and is not imported by
`backend/` or `frontend/`. Website data, authentication, authorization,
payments, storage, and database access remain owned by the main application.

Hermes is bootstrapped separately from a clean pinned upstream checkout:

```bash
bash studyhub-agent/scripts/setup-hermes.sh
```

The checkout is stored under the ignored `.vendor/` directory. No legacy
StudyHub router, memory implementation, patch, or skin is carried into V2. See
`integrations/hermes/README.md` for the integration boundary.

## Phase 1 CPU setup

The training-ready contract can be installed and verified without CUDA or model weights:

```bash
bash studyhub-agent/scripts/bootstrap-phase1.sh
bash studyhub-agent/scripts/verify-phase1.sh
```

The bootstrap installs only the Agent contract, CPU RAG dependencies, and the pinned Hermes runtime. It does not install dense-model extras, download checkpoints, access the production database, or run a trainer.

Frozen Phase 1 surfaces:

```text
AgentIdentity / TaskSpec / AgentProfile
Tool schema v1
studyhub.trajectory.v1
RewardResult v1
StudyHub-AgentBench v1
```

See `docs/phase1-completion.md` for the verified boundaries and GPU handoff steps.

## Agentic Post-Training v3

The current training program is Benchmark-first and uses Qwen3.5-9B as the
main model. The 4B matrix, 3k SFT set, 2.4k RL set, Reward v2, and Eval32 are
frozen as historical infrastructure evidence; they do not gate the 9B
program.

StudyHub AgentBench v2 is now frozen at revision `2.0.0`: 98 tasks, 78 source
groups, 51 Development tasks, 13 Sealed-A tasks, 12 Sealed-B tasks, and 10
Calibration-Challenge tasks. Qwen3.5-9B Base completed the 51-task Development
run and a complete 35-task, four-rollout variance panel with zero infrastructure
exclusions. Official external model evaluations remain pending and are reported
separately.

The current data target is a 105,690-trajectory candidate pool followed by
48,500 Benchmark-v2-disjoint runtime-native SFT trajectories and a 10k post-QA
RL task pool. The runtime-native SFT release passed its manifest, tokenizer,
runtime-parity, contamination, and full loss-mask audits. A guarded one-step
dual-H100 AReaL Gate then completed one real optimizer update: loss `0.51857`,
gradient norm `0.40752`, and different initial/final LoRA hashes. This proves
the training and checkpoint path, not model quality. Equal-budget r16/r32
profiles remain pending, and formal SFT is still unauthorized.

- [9B Agentic Post-Training v3 program](docs/StudyHub_9B_Agentic_Post_Training_Program_v3.html)
- [Machine-readable training contract](configs/program-v3/training-program-v3.json)
- [Capability matrix](configs/program-v3/capability-matrix-v1.json)
- [Algorithm decision matrix](configs/program-v3/algorithm-decision-matrix-v1.json)
- [Benchmark v2 data card](benchmarks/studyhub-agent-v2/DATA_CARD.md)
- [9B Base v2 calibration](docs/benchmark/9B_BASE_V2_CALIBRATION.md)
- [Runtime-native SFT v3 data card](docs/training/RUNTIME_SFT_V3_DATA_CARD.md)
- [9B SFT Gate evidence](docs/training/evidence/runtime-sft-v3-9b-gate-20260827.json)
- [Primary-source review](research/primary-source-review.md)
- [Initial design-defect audit](design-defects/index.json)

Validate the program and local 9B assets without starting a trainer:

```bash
cd /data/chengjin/studyhub/studyhub-agent
.venv-train/bin/python scripts/train/validate_v3_program.py --check-local-assets
```

## Historical controlled 4B / 9B setup

The v2 Qwen3.5-4B and Qwen3.5-9B checkpoints, tokenizer-specific SFT datasets,
isolated RL tasks, and AReaL launchers remain available for reproduction.
Verification is CPU-only and never starts a trainer:

```bash
bash studyhub-agent/scripts/train/prepare_controlled_experiment.sh verify
```

These launchers are not v3 entry points. Reproducing them still requires both
an explicit non-`check` mode and `STUDYHUB_ALLOW_TRAINING=YES`. See
`docs/controlled-4b-9b-training-readiness.md` for the experiment matrix,
dataset counts, checkpoint handoff, and launch commands.

## Historical 4B experiment results

The controlled 4B matrix is complete for Base, SFT-only, Direct GRPO, and
SFT-to-GRPO. All four checkpoints were evaluated with the same deterministic
32-task, four-rollout protocol. The paired bootstrap intervals do not support
a broad performance-improvement claim. v3 therefore keeps these results as
lineage and defect evidence rather than replicating their protocol on 9B.

- [4B AReaL SFT and Agentic RL report](docs/StudyHub_4B_AReaL_Agentic_RL_Experiment_Report.html)
- [Interview evidence dossier](docs/interview/index.html)
- [Goal-Pack-based HTML answer bank](docs/interview/answer-bank.html)

Large checkpoints and raw run artifacts remain Git-ignored. The committed
reports preserve trial IDs, aggregate metrics, hashes, evidence grades, and
reproduction entry points without publishing model weights or secrets.
