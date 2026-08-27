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

Current v3 targets are 160 Regression tasks, 1,005 StudyHub Development tasks,
500 Sealed tasks, 45k runtime-native SFT trajectories, and a 10k post-QA RL
task pool. Training remains disabled until Benchmark v1 is frozen and the 9B
Base baseline is complete.

- [9B Agentic Post-Training v3 program](docs/StudyHub_9B_Agentic_Post_Training_Program_v3.html)
- [Machine-readable training contract](configs/program-v3/training-program-v3.json)
- [Capability matrix](configs/program-v3/capability-matrix-v1.json)
- [Algorithm decision matrix](configs/program-v3/algorithm-decision-matrix-v1.json)
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
