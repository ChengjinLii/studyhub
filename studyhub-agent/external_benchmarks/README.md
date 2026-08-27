# External Benchmark Portfolio

This directory pins official external benchmarks without mixing their tasks or metrics into StudyHub AgentBench.

## Workflow

```bash
python scripts/benchmark/external/fetch.py --benchmark all
python scripts/benchmark/external/validate_registry.py
python scripts/benchmark/external/smoke.py
```

Use `--offline` with `fetch.py` to verify and reuse an existing cache. Sources, datasets, indexes, decrypted answers, trajectories, and model outputs stay under ignored `artifacts/external-benchmarks/`.

`result_schema.py` preserves each upstream raw metric. The OpenAI-compatible adapter is only a policy transport; it does not implement a new agent loop or replace an official evaluator.

Current pinned revisions and exact setup states are recorded in `registry.yaml`, `lock.json`, and `smoke-status.json`. A missing license or credential is reported explicitly rather than converted into a passing score.
