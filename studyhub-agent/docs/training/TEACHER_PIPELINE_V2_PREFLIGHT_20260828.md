# Teacher-to-Hermes v2 Preflight

Date: 2026-08-28

## Scope

This revision corrects the teacher-data measurement defects found after the first ten-task Spark smoke. It does not alter runtime-SFT-v3.0, Benchmark v2, the completed 9B SFT checkpoint, or Hermes upstream code. It does not authorize or run RL.

## v1 Findings

- Public task specs exposed `required_tool_names` derived from the source trajectory. This leaked the gold action set and weakened autonomous routing evidence.
- Nested `web_fetch` observations were not recognized as read evidence. A trajectory that searched, fetched, cited, and answered correctly could be rejected as ungrounded.
- State fixtures required exact free-text fields. Semantically equivalent `study_plan_update.topic` text was rejected even when resource IDs and duration matched.
- Spark quota exhaustion was recorded as a generic execution failure and the collector continued issuing requests.
- The first smoke therefore remains immutable historical evidence; its accepted/rejected hashes are not recomputed.

## v2 Corrections

- Public tasks contain the goal, allowed tools, hard constraints, visible history, and budgets, but no reference answer, verifier, expected tools, required tools, or oracle trajectory.
- Each model turn includes a derived visible runtime state: completed calls, discovered sources, grounded sources, remaining steps, remaining tool calls, last visible error, and citation deficit.
- Only successful Read/Fetch observations ground citations. Search results only discover source IDs.
- `web_fetch` tracks nested source IDs as read evidence.
- State fixtures allow declared equivalence only for the descriptive `topic` field; IDs, durations, key sets, and schemas remain exact.
- Expected tool paths remain hidden diagnostics. Verifier requirements use grounded evidence, task-specific state outcomes, and the small subset of inherently required state/memory operations.
- Spark usage/rate limits stop the bounded collector instead of generating repeated failed requests.
- Smoke task selection is deterministic and stratified by capability family. Run IDs bind the task, model, candidate index, and collector commit.

## Static Task Inventory

The v2 build requested 1,200 tasks and produced 1,152 after enforcing a maximum of 12 rows per underlying source group.

| Item | Value |
| --- | ---: |
| Task rows | 1,152 |
| Capability families | 7 |
| Unique source groups | 261 |
| Largest source-group count | 12 |
| Public gold/verifier key leaks | 0 |
| Public Benchmark prompt overlap | 0 |
| Environment / fixture / verifier files | 1,152 each |
| Web evidence-fetch environments | 180 |
| Flexible state routes | 252 |

Task specs SHA-256: `9f0a8b0855138fc36d8dd9195815082c19d25190b6e3cd00f23dabef686765ca`

Benchmark v2 manifest SHA-256 remains `da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b`. Only Regression, Development, and Calibration public prompts were checked. Sealed task files were not read.

## Gate

Status: `READY_FOR_COMMITTED_TEACHER_SMOKE`

The next step is a maximum ten-task, two-candidate smoke on a clean commit. Expansion is allowed only if tool-using trajectories pass the objective verifier without oracle leakage. A provider quota stop is evidence, not a reason to loop requests.
