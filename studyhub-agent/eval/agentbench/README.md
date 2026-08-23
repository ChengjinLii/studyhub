# StudyHub-AgentBench v1

`v1/cases.jsonl` is the frozen Phase 1 task set. It contains 100 deterministic, fixture-only cases across ten task families. The file stores task contracts and verifier expectations only; benchmark scores are always computed from a fresh run and are never committed as fabricated results.

The benchmark must run without live Web access, production databases, user records, or mutable personal-memory state.
