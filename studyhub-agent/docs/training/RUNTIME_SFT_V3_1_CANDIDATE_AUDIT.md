# Runtime-SFT-v3.1 Teacher Candidate Audit

Status: `PASS_CANDIDATE_ONLY_INSUFFICIENT_TEACHER`
Candidate SHA-256: `50c08ddee475d0d577f3aead69f3b9a030697327a80e04d2b4195b5d98e0c205`
Teacher rows: `2`
Sealed task files read: `false`

This is a candidate derived from immutable runtime-SFT-v3.0. It is not a formal release and is not used by the overnight v3.0 baseline.

## Constraints

| Check | Result |
| --- | --- |
| candidate_hash_matches_manifest | PASS |
| base_hash_is_frozen_v3 | PASS |
| rows_45k_to_50k | PASS |
| action_only_at_most_5_percent | PASS |
| single_source_at_most_25_percent | PASS |
| custom_source_at_most_15_percent | PASS |
| group_split_overlap_zero | PASS |
| public_benchmark_prompt_overlap_zero | PASS |
| runtime_contract_valid | PASS |
| sealed_task_files_read_false | PASS |

## Source Distribution

| Source | Rows | Share | Complete | Action-only | Runtime-native | Groups | Group p90/max | Paths | Largest path |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| coig_exam | 4,500 | 9.28% | 4,500 | 0 | 0.00% | 4,500 | 1/1 | 1 | 100.00% |
| hermes_function_calling | 2,600 | 5.36% | 2,195 | 405 | 35.65% | 2,600 | 1/1 | 990 | 61.31% |
| studyhub_2wiki_replay | 12,000 | 24.74% | 12,000 | 0 | 100.00% | 12,000 | 1/1 | 2 | 97.28% |
| studyhub_acl_recovery | 4,286 | 8.84% | 4,286 | 0 | 100.00% | 1,946 | 4/14 | 1 | 100.00% |
| studyhub_memory_replay | 4,286 | 8.84% | 4,286 | 0 | 100.00% | 101 | 54/71 | 1 | 100.00% |
| studyhub_metadata_replay | 6,000 | 12.37% | 6,000 | 0 | 100.00% | 99 | 118/138 | 1 | 100.00% |
| studyhub_qasper_replay | 3,589 | 7.40% | 3,589 | 0 | 100.00% | 1,168 | 5/12 | 4 | 56.23% |
| studyhub_state_tools | 4,285 | 8.84% | 4,285 | 0 | 100.00% | 101 | 57/71 | 1 | 100.00% |
| studyhub_teacher_v1 | 2 | 0.00% | 2 | 0 | 0.00% | 1 | 2/2 | 1 | 100.00% |
| studyhub_web_fallback | 4,285 | 8.84% | 4,285 | 0 | 100.00% | 101 | 56/62 | 1 | 100.00% |
| toolace | 2,667 | 5.50% | 647 | 2,020 | 24.26% | 2,667 | 1/1 | 2,640 | 0.07% |

## Interpretation

Teacher rows replace weak action-only rows first. Remaining action-only excess is replaced with complete, benchmark-disjoint rows from the existing audited candidate pool. The candidate keeps group-disjoint train/validation/holdout splits and does not open Sealed-A/B. Token statistics remain unavailable until a candidate reaches the 500 accepted-teacher threshold and is separately tokenized.
