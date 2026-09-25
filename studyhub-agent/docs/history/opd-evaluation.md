# OPD evaluation: archived conclusions

This note archives the conclusions of the Optimal Policy Distillation (OPD)
experiment for the Qwen3.5-4B StudyHub agent before the GitHub branches (and
most of the local branches/worktrees) that produced it were deleted (Task 15
of the v3 foundation plan, with the repository owner's explicit
authorization; see "Where the code went" below for exactly what was and
was not removed). Full commit history for this work is retained forever via
the tags pushed in Task 1. The numeric results in this doc, however, come
from a gitignored, untagged evaluation-suite run directory on the server
(see "Run" below) — that raw data is *not* reachable from any tag or
branch, so this summary (plus that directory, while it exists) is the only
record of it. Every source below is cited as `archive/opd-evaluation:<path>`
(or the sibling `archive/opd-execution`, `archive/opd-preflight` tags) and
can be read at any time with `git show <tag>:<path>` on
`/data/chengjin/studyhub`, since tags are never deleted.

## What OPD was

A controlled experiment applying the THUNLP OPD recipe
(`thunlp/OPD@ac26e38d6f1572eb027597b48a9f4e01f6915ef8`) as a process-local
extension of the StudyHub AReaL training runtime: a frozen 9B teacher scores
the student's own top-k token IDs on the identical visible prefix, producing
detached token-level rewards (`adv_estimator=token_reward_direct`,
`top_k_strategy=only_stu`, `reward_weight_mode=student_p`), which drive a
strict on-policy PPO-style update on top of the frozen Qwen3.5-4B M2 (SFT2)
LoRA adapter. Official `verl` and StudyHub's existing `AReaL` runtime were
kept only as independent implementation references, not as the training
path. Source: `archive/opd-evaluation:studyhub-agent/docs/training/OPD_INTEGRATION_DECISION.md`.

## Run

- **Training run:** `qwen35-4b-opd-formal-seed-20260827-attempt-20260907_115956`
  — 300 optimizer updates at LR 3e-6, batch 8, two responses per prompt,
  starting from the frozen M2 adapter. All 300 updates completed; the last
  update finished 2026-09-08 03:20:56 +08:00. Final adapter SHA256:
  `6551b6ae3fdf242561a13aae5c7379b12526c746894320cad13fd227b7995ca8`.
  Source: `archive/opd-evaluation:studyhub-agent/docs/training/OPD_FORMAL_300_CLOSEOUT.md`.
- **Student (M2):** frozen SFT2 checkpoint,
  `StudyHub/qwen35-4b-base-canonical-tokenizer-sft2@4b7ee7462d82cd17`.
- **OPD checkpoint:** post-training adapter,
  `StudyHub/qwen35-4b-base-canonical-tokenizer-opd@6551b6ae3fdf2425`.
- **Evaluation suite run:** `qwen35-4b-opd-closeout-20260908-managed-v2`, run
  2026-09-08 (~03:15–03:25 UTC / ~11:15–11:25 +08:00), at git commit
  `43011283d8bb5bd6653db07e27737fa4a2891609` (the `archive/opd-evaluation`
  tag tip). It sequentially ran both M2 and OPD on four fixed panels:
  Protocol128 (128 rows / 438 items), AgentBench Development51 (51 public
  development tasks), BFCL70 (70 public cases) and tau2-15 (15 public tasks).
  Source: `archive/opd-evaluation:studyhub-agent/docs/training/OPD_FORMAL_300_EXECUTION.md`
  and `archive/opd-evaluation:studyhub-agent/scripts/train/run_qwen35_4b_opd_evaluation_suite.py`.
  Raw run output (`suite.json`, per-panel `summary.json`/`episodes.jsonl`,
  GPU/server logs) is retained on the server at
  `/data/chengjin/studyhub/studyhub-agent/artifacts/evaluation-suite/qwen35-4b-opd-closeout-20260908-managed-v2/`
  — this directory is gitignored (not part of any tag or branch) and lives
  in the main checkout, so it was left untouched by Task 15's deletions. The
  suite's own status is `PARTIAL_EVALUATION` (BFCL/tau2 did not produce
  results; see below).

## Results

### Development51 (AgentBench, 51 public development tasks)

- M2 strict-success: **4/51** (7.84%)
- OPD strict-success: **4/51** (7.84%) — identical aggregate rate
- Paired per-task comparison (`strict_success`, task-by-task, OPD vs M2):
  **3 wins / 3 losses / 45 ties**

Source: computed directly from `m2/agentbench/episodes.jsonl` and
`opd/agentbench/episodes.jsonl` in the evaluation-suite run above (both
files carry `git_commit`/model hashes matching the `archive/opd-evaluation`
tag tip and the OPD adapter SHA256 above).

### Protocol128 (teacher-forced protocol validity; 429 scored / 438 expected items, 9 infra-excluded)

| Metric | M2 | OPD |
|---|---|---|
| tool_call_parse_rate | 97.1% | 89.1% |
| exact_tool_name_match_rate | 90.1%\* | 79.2% |
| final_nonempty_rate | 87.3% | 98.4% |

\* The task brief for this step quoted 90.2% for M2's tool-name match rate.
The primary source
(`m2/protocol/summary.json`: `"exact_tool_name_match_rate": 0.90145985`)
rounds to **90.1%**; this doc uses the source value and flags the
discrepancy rather than silently reconciling it.

Source: `m2/protocol/summary.json` and `opd/protocol/summary.json` in the
evaluation-suite run above.

### BFCL70 / tau2-15

Not produced. All four stages (`m2-bfcl`, `opd-bfcl`, `m2-tau2`, `opd-tau2`)
failed before writing a summary or episodes file:

```
FileNotFoundError: [Errno 2] No such file or directory: 'uv'
```

The `uv` binary was not on `PATH` inside the guarded GPU launch environment.
Run manifests exist (`m2/bfcl/run-manifest.json`, `m2/tau2/run-manifest.json`,
and the OPD equivalents) but no `summary.json`/`episodes.jsonl` were ever
written for these two panels, in either the M2 or OPD condition. Source:
`m2-bfcl.gpu.log`, `opd-bfcl.gpu.log`, `m2-tau2.gpu.log`, `opd-tau2.gpu.log`
in the evaluation-suite run above.

## Conclusion

**No measurable gain; the teacher is not stronger than the student on the
target distribution.**

- Development51's aggregate strict-success rate is identical (4/51 for both
  models), and the paired per-task comparison is balanced (3 wins vs 3
  losses) with the overwhelming majority of tasks (45/51) unchanged either
  way — no net capability improvement.
- Protocol128 shows a mixed, not a clean, signal: OPD *regresses* on
  tool-call parsing (97.1% → 89.1%) and exact tool-name matching (90.1% →
  79.2%), while only final-turn non-emptiness improves (87.3% → 98.4%). A
  model that calls tools less reliably and names them less accurately is not
  evidence of a stronger policy, even where one surface metric moved up.
- BFCL70 and tau2-15 — the two panels meant to give an independent,
  non-protocol read on tool-use capability — were never produced (`uv`
  missing), so no further evidence closes the gap in OPD's favor.

This is the evidence basis for freezing the OPD line of work rather than
promoting the OPD adapter, and for archiving (not merging)
`codex/qwen35-4b-opd-preflight`, `codex/qwen35-4b-opd-execution`, and
`codex/qwen35-4b-opd-evaluation`.

## Where the code went

The full commit history for the OPD preflight/execution/evaluation work, and
for the prior "agent v2" codebase this v3 rewrite replaces, is preserved
indefinitely by four tags pushed to `git@github.com:ChengjinLii/studyhub.git`
in Task 1 (never deleted):

- `legacy-agent-v2` → `ff2d6d24d8bb281ae39134305e1de584c383d1e0` (== `origin/main`
  at the time of the v3 rewrite)
- `archive/opd-preflight` → `3d77f45a7307f1d9e6c75f95242f75cf0ec334be`
  (was branch `codex/qwen35-4b-opd-preflight`)
- `archive/opd-execution` → `2f72a72f947fdd4b166b2a61247127fc43c9cb92`
  (was branch `codex/qwen35-4b-opd-execution`)
- `archive/opd-evaluation` → `43011283d8bb5bd6653db07e27737fa4a2891609`
  (was branch `codex/qwen35-4b-opd-evaluation`)

In Task 15, the GitHub branches `codex/qwen35-4b-opd-execution` and
`codex/qwen35-4b-opd-preflight` were deleted (`codex/qwen35-4b-opd-evaluation`
was never pushed to GitHub in the first place). On the server
(`/data/chengjin/studyhub`), the local branch and worktree for
`opd-preflight` and `opd-evaluation` were also removed. The local branch
`codex/qwen35-4b-opd-execution` and its worktree
(`/data/chengjin/studyhub-opd-execution-worktree`) were **retained** — not
deleted — because that worktree holds gitignored, untagged run artifacts
(`artifacts/experiments/*/{checkpoints,trajectories,metrics}`,
`datasets/interim`, ~62M total) that `git worktree remove` would destroy
along with the checkout. Its commits are already fully covered by the
`archive/opd-execution` and `archive/opd-evaluation` tags, so no history is
at risk either way; only the convenience of a local checkout differs.

Any path cited above as `archive/opd-evaluation:<path>` (or under the other
three tags) remains retrievable at any time with `git show <tag>:<path>` —
deleting a branch only removes the mutable pointer, not the commits, which
stay reachable from the tag.
