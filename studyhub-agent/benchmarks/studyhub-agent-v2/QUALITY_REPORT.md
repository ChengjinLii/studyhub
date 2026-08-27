# StudyHub AgentBench v2 Quality Report

## Decision

Status: **FROZEN_FOR_BASELINE** at revision **2.0.0**. The engineering gate passed; independent expert review remains pending.

## Evidence

- Structural audit: **18/18 passed**.
- Development semantic clusters: **51/51**; largest cluster **1.96%**.
- Scripted Oracle: **73/73 (100.00%)**.
- Negative controls: empty, random, generic, tool spam, citation decoration, and wrong-source attacks each achieved **0 strict passes**.
- Metamorphic tests: **8/8**.
- Evaluator challenge cases: **21/21**.
- Shortcut probe: 98 tasks, 71 answer signatures, largest signature share **6.12%**.
- Frozen v1 integrity: unchanged under `configs/benchmark-v1-frozen-hashes.json`.

## Measurement Boundaries

Deterministic facts, citations, ACL, tool contracts, state postconditions, query change, recall gain, and runtime exclusion are evaluated locally. No online semantic judge result is claimed. Scalar scores from training Reward are not imported. INFRA failures remain excluded from policy accuracy.

The review packs are ignored because they include sealed tasks and hidden graders. Only their counts and SHA256 hashes are tracked. `self_review` is not labeled as human review.
