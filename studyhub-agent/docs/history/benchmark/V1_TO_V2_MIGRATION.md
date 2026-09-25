# AgentBench v1 To v2 Migration

v1 remains unchanged and bound to its existing 9B Base lineage. Its Development split has 1005 tasks over 64 source groups, with source reuse up to 31 and a largest normalized semantic shape of 3.58%. Its previous teacher review was a deterministic contract check, not an independent semantic review.

v2 is a new benchmark rather than a score migration. It uses 98 tasks and 78 split-isolated source groups; Development has 51 semantic clusters for 51 tasks. Difficulty starts as `UNSCORED`. Web evidence comes from a locked authentic snapshot, query rewrite requires evidence gain, ACL avoidance is separate from post-denial recovery, and claim support binds answers to read/fetched sources.

Do not recalculate or overwrite v1 results with the v2 evaluator. New 9B Base/SFT/GRPO experiments should bind the v2 manifest hash and report a fresh lineage.
