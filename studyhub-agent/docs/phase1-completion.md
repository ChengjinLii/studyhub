# StudyHub Agent V2 Phase 1 Completion

Version: `agent-v2-training-ready-v1`

Historical note: this report describes the frozen schema-v1 fixture surface.
The production runtime now delegates Web and personal-memory lifecycle to
Hermes while retaining schema-v1 under `studyhub_agent.replay`. See
`docs/architecture/HERMES_TOOL_BOUNDARY.md`.

Phase 1 freezes the runtime and training-data contracts required before moving work to a GPU host. It was verified on CPU in a single process. No model checkpoint was downloaded, no CUDA stack was installed, no trainer was started, and no production database was accessed or changed.

## Runtime Boundary

Hermes Agent at commit `5c1a304ce890276a4334d8ced3f29ffeedbbbf93` is the sole Agent harness. The checkout remains an ignored, detached, clean upstream tree. StudyHub registers capabilities through Hermes' public tool registry; it does not patch the Hermes loop, planner, memory internals, or source files.

StudyHub owns deterministic boundaries only:

- Pseudonymous identity and environment-specific memory namespaces.
- Task and tool budgets.
- Strict tool argument schemas.
- Material ACL filtering before chunks reach the model.
- Citation authenticity and output privacy filtering.
- Web SSRF, redirect, content-type, and response-size limits.

There is no StudyHub intent router, query planner, fixed DAG, custom Agent loop, or custom memory manager.

## Capabilities

The frozen tool schema exposes:

- `knowledge_search`, `knowledge_read`, and `knowledge_browse` through the retained RAG retrieval implementation.
- `web_search` and `web_fetch` through provider protocols and guarded fixture providers.
- `personal_memory_search` over a user-isolated personal-memory provider contract.
- `collective_memory_search` over anonymized, read-only aggregate patterns.

Production backend access is represented only by a future read-only protocol. Phase 1 fixtures never connect to the website database.

## Training Contracts

- `TaskSpec`, `AgentIdentity`, and `AgentProfile` are shared by product, evaluation, and training.
- `studyhub.trajectory.v1` records nine event types as append-only JSONL.
- `RewardResult v1` combines deterministic task, grounding, citation, tool-quality, efficiency, and violation signals in `[-1, 1]`.
- StudyHub-AgentBench v1 contains 100 fixed cases, ten cases for each of ten task families. It depends only on repository fixtures and stores no fabricated result report.
- `GroupedEpisodeCoordinator` fixes task, environment seed, memory snapshot, and group ID while varying rollout seed.
- SFT, GRPO, OPD, KDRL, and best-of-N 9B YAML templates validate without importing AReaL or loading model weights.

## Verification

The following command is the authoritative CPU gate:

```bash
bash studyhub-agent/scripts/bootstrap-phase1.sh
bash studyhub-agent/scripts/verify-phase1.sh
```

Verified checks:

- 34 Agent V2 tests, including 100-case AgentBench smoke evaluation.
- Five real clean-Hermes loops: RAG, Web, Memory, RAG plus Memory, and RAG plus Web plus Memory.
- Tool observations must return valid non-error payloads before the fake model can finish.
- 13 retained RAG experiment tests.
- RAG source-isolation AST audit.
- Clean Hermes commit and worktree verification.
- Legacy architecture symbol scan.

The repository fixture only verifies the public-material ID contract for the historical RAG benchmark. A full retrieval-quality run still requires the approved immutable snapshot and model caches configured by `ai_platform/rag_experiments/configs/benchmark.yaml`; no quality numbers are synthesized when those assets are absent.

## GPU Handoff

On the GPU host:

1. Check out tag `agent-v2-training-ready-v1`.
2. Run the bootstrap and verification commands above.
3. Mount approved immutable RAG snapshots and existing model caches where required.
4. Perform model/tokenizer compatibility checks against the configuration templates.
5. Generate real trajectories, then start SFT and evaluate against frozen AgentBench v1.
6. Continue to GRPO, OPD, or KDRL only after SFT and evaluation artifacts pass review.

Do not change Tool Schema v1, TaskSpec, Trajectory v1, RewardResult v1, AgentBench v1, or the Hermes runtime boundary during ordinary training experiments. Contract changes require a separately versioned migration.
