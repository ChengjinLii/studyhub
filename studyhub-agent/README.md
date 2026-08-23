# StudyHub Agent V2

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
