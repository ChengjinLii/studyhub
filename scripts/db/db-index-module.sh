#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
MODULE="${1:-}"
COMMAND="${2:-plan}"

case "$MODULE" in
  engagement)
    SCOPES=(
      comment_likes.ix_comment_likes_comment_id
      comments.ix_comments_material_id
      material_downloads.ix_material_downloads_user_id
      material_likes.ix_material_likes_material_id
      material_views.ix_material_views_viewer_token_hash
      materials.ix_materials_uploader_id
    )
    ;;
  auth-community)
    SCOPES=(
      email_verifications.ix_email_verifications_email
      email_verifications.ix_email_verifications_purpose
      email_verifications.ix_email_verifications_user_id
      notifications.ix_notifications_user_id
      reports.ix_reports_target_type
      reports.ix_reports_target_id
      user_notes.ix_user_notes_user_id
    )
    ;;
  finance)
    SCOPES=(
      creator_payout_applications.ix_creator_payout_applications_user_id
      creator_payout_applications.ix_creator_payout_applications_id_hash
      creator_payout_applications.ix_creator_payout_applications_cycle_key
    )
    ;;
  *)
    echo "usage: $0 {engagement|auth-community|finance} {plan|apply}"
    exit 2
    ;;
esac
if [[ "$COMMAND" != plan && "$COMMAND" != apply ]]; then
  echo "command must be plan or apply"
  exit 2
fi

args=("$COMMAND")
for scope in "${SCOPES[@]}"; do args+=(--only "$scope"); done
if [[ "$COMMAND" == apply ]]; then
  if [[ -z "${STUDYHUB_INDEX_PLAN_TOKEN:-}" ]]; then
    echo "STUDYHUB_INDEX_PLAN_TOKEN is required for apply"
    exit 2
  fi
  args+=(--plan-token "$STUDYHUB_INDEX_PLAN_TOKEN")
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT=production
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
exec "$ROOT_DIR/.venv/bin/python" -m app.ops.index_admin "${args[@]}"
