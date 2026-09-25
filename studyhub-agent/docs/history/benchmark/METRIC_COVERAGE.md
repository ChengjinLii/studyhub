# AgentBench v2 Metric Coverage

The table distinguishes a capability-oriented task family from the metrics that the local evaluator actually operationalizes. It does not claim independent semantic validation where the semantic judge status is `NOT_RUN` or `NOT_REQUIRED`.

| Capability family | Tasks | Outcome mode | Process contract | Operationalized metrics | Semantic judge |
| --- | ---: | --- | --- | --- | --- |
| `authentic_web_research` | 5 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `cross_chunk_synthesis` | 20 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `direct_answer_tool_relevance` | 2 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `factual_passage_retrieval` | 34 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `insufficient_evidence` | 1 | abstain | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `long_horizon` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `memory_absence` | 1 | abstain | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `memory_collective_conflict` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality | NOT_REQUIRED |
| `memory_collective_low_confidence` | 2 | abstain | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `memory_cross_user_privacy` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality | NOT_REQUIRED |
| `memory_current_conflict` | 2 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality | NOT_REQUIRED |
| `memory_incomplete_abstention` | 1 | abstain | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `memory_irrelevant_tool_abstention` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `memory_rag_composition` | 2 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `memory_scope_resolution` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality | NOT_REQUIRED |
| `memory_selection` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality | NOT_REQUIRED |
| `memory_temporal_change` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality | NOT_REQUIRED |
| `memory_user_correction` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality | NOT_REQUIRED |
| `memory_web_composition` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `memory_web_conflict_resolution` | 2 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `multi_source_synthesis` | 1 | atomic_rubric | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_RUN |
| `permission_avoidance` | 2 | facts | permission_avoidance | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness, recovery_or_process_success | NOT_REQUIRED |
| `permission_recovery` | 2 | facts | permission_recovery | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness, recovery_or_process_success | NOT_REQUIRED |
| `query_reformulation` | 1 | facts | query_reformulation | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness, recovery_or_process_success | NOT_REQUIRED |
| `source_disambiguation_ood` | 2 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `state_conditional_action` | 2 | state | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `state_function_calling` | 2 | state | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `state_multistep_postcondition` | 1 | state | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency | NOT_REQUIRED |
| `stop_cost_control` | 1 | facts | open_path | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness | NOT_REQUIRED |
| `tool_failure_recovery` | 3 | facts | failure_recovery | strict_success, task_outcome, answer_correctness, tool_validity, privacy_policy, efficiency, claim_support, source_quality, citation_correctness, citation_completeness, recovery_or_process_success | NOT_REQUIRED |
