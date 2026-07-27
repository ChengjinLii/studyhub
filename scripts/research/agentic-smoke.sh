#!/usr/bin/env bash
set -euo pipefail

# Offline quality gate for the first Agentic Platform phase.  It uses only the
# repository's fixture/SQLite tests; it never starts a model, worker, browser,
# production service, or external research provider.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

fail() {
  printf 'agentic-smoke: %s\n' "$*" >&2
  exit 1
}

[[ -x "$PYTHON_BIN" ]] || fail "missing Python interpreter: $PYTHON_BIN"

cd "$BACKEND_DIR"

"$PYTHON_BIN" -m ruff check app/agentic_platform tests/agentic_platform ../ml

"$PYTHON_BIN" -m pytest -q \
  tests/agentic_platform/test_runtime.py::test_kernel_persists_interrupt_and_resumes_after_sqlite_process_restart \
  tests/agentic_platform/test_runtime.py::test_replay_state_hash_and_transitions_are_stable \
  tests/agentic_platform/test_runtime.py::test_redis_checkpoint_mirror_failure_does_not_interrupt_a_durable_run \
  tests/agentic_platform/test_policy.py::test_context_compaction_keeps_the_capability_catalog_while_only_compacting_the_view \
  tests/agentic_platform/test_deepresearch.py::test_context_compression_never_deletes_evidence_from_the_ledger \
  tests/agentic_platform/test_deepresearch.py::test_policy_can_rewrite_an_empty_first_query_without_a_hardcoded_retry_path \
  tests/agentic_platform/test_deepresearch.py::test_conflicting_internal_evidence_is_preserved_and_marked_for_cross_validation \
  tests/agentic_platform/test_deepresearch.py::test_unreadable_pdf_is_a_recoverable_observation_that_policy_can_retry \
  tests/agentic_platform/test_deepresearch.py::test_invalid_citation_target_is_rejected_by_citation_validation \
  tests/agentic_platform/test_deepresearch.py::test_unsupported_claim_is_rejected_by_citation_validation \
  tests/agentic_platform/test_proactive.py::test_duplicate_material_event_dispatches_once_and_artifact_is_admin_visible \
  tests/agentic_platform/test_proactive.py::test_worker_restart_reclaims_stale_proactive_job \
  tests/agentic_platform/test_persistence.py::test_artifact_versions_increment_and_inline_content_stays_bounded \
  tests/agentic_platform/test_simulation.py::test_same_snapshot_seed_and_actions_replay_to_the_same_state_hash_for_ten_turns \
  tests/agentic_platform/test_dynamic_snapshot_environment.py \
  tests/agentic_platform/test_data_governance.py \
  tests/agentic_platform/test_trajectory_export.py::test_transition_sink_preserves_raw_token_ids_and_masks_observations \
  tests/agentic_platform/test_trajectory_export.py::test_corrupted_trajectory_is_quarantined_before_a_fresh_trace_is_written \
  tests/test_admin_agentic_auth.py::test_admin_agentic_health_rejects_developer \
  tests/test_admin_agentic_auth.py::test_admin_agentic_health_rejects_regular_user \
  tests/test_admin_agentic_runs.py::test_resume_token_is_one_time_and_queues_durable_resume_job

printf 'Agentic smoke check passed.\n'
