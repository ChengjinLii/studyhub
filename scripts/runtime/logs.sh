#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_LOG_ENVIRONMENT:-production}"
SERVICE="${STUDYHUB_LOG_SERVICE:-backend}"
SINCE="${STUDYHUB_LOG_SINCE:-30 minutes ago}"
FOLLOW="${STUDYHUB_LOG_FOLLOW:-0}"
REQUEST_ID="${STUDYHUB_LOG_REQUEST_ID:-}"
LEVEL="${STUDYHUB_LOG_LEVEL:-}"

usage() {
  cat <<'USAGE'
Usage: scripts/runtime/logs.sh [--env production|preview] [--service backend|frontend|worker|nginx|all] [--since VALUE] [--follow] [--request-id ID] [--level LEVEL]

Environment variables:
  STUDYHUB_LOG_ENVIRONMENT  production|preview (default: production)
  STUDYHUB_LOG_SERVICE      backend|frontend|worker|nginx|all (default: backend)
  STUDYHUB_LOG_SINCE        journalctl --since value (default: 30 minutes ago)
  STUDYHUB_LOG_FOLLOW       1 to follow
  STUDYHUB_LOG_REQUEST_ID   filter by request id
  STUDYHUB_LOG_LEVEL        filter by level text, e.g. ERROR
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENVIRONMENT="${2:-}"
      shift 2
      ;;
    --service)
      SERVICE="${2:-}"
      shift 2
      ;;
    --since)
      SINCE="${2:-}"
      shift 2
      ;;
    --follow|-f)
      FOLLOW="1"
      shift
      ;;
    --request-id)
      REQUEST_ID="${2:-}"
      shift 2
      ;;
    --level)
      LEVEL="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1"
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${SINCE//[[:space:]]/}" ]]; then
  echo "--since / STUDYHUB_LOG_SINCE cannot be blank"
  exit 2
fi

case "$ENVIRONMENT" in
  production|preview)
    ;;
  *)
    echo "--env must be production or preview; got $ENVIRONMENT"
    exit 2
    ;;
esac

case "$SERVICE" in
  backend|frontend|worker|nginx|all)
    ;;
  *)
    echo "--service must be backend, frontend, worker, nginx, or all; got $SERVICE"
    exit 2
    ;;
esac

if [[ "$SERVICE" == "all" && "$FOLLOW" == "1" ]]; then
  echo "--service all cannot be combined with --follow; choose one service to follow"
  exit 2
fi

systemd_unit_for() {
  local service="$1"
  case "$service" in
    backend) echo "studyhub-backend.service" ;;
    frontend) echo "studyhub-frontend.service" ;;
    worker) echo "studyhub-worker.service" ;;
    nginx) echo "nginx.service" ;;
  esac
}

runtime_log_for() {
  local service="$1"
  local runtime_root
  runtime_root="$PRIVATE_DIR/.runtime-$ENVIRONMENT"
  case "$service" in
    backend|frontend|worker) echo "$runtime_root/logs/$service.log" ;;
    nginx) echo "" ;;
  esac
}

build_filter() {
  local filter=""
  if [[ -n "$REQUEST_ID" ]]; then
    filter="$REQUEST_ID"
  fi
  if [[ -n "$LEVEL" ]]; then
    if [[ -n "$filter" ]]; then
      filter="$filter|$LEVEL"
    else
      filter="$LEVEL"
    fi
  fi
  echo "$filter"
}

filter_stream() {
  local filter="$1"
  if [[ -z "$filter" ]]; then
    cat
  elif command -v rg >/dev/null 2>&1; then
    rg --line-buffered "$filter"
  else
    grep -E --line-buffered "$filter"
  fi
}

filter_file() {
  local filter="$1"
  local file="$2"
  if [[ -z "$filter" ]]; then
    tail -n 200 "$file"
  elif command -v rg >/dev/null 2>&1; then
    rg "$filter" "$file"
  else
    grep -E "$filter" "$file"
  fi
}

stream_one() {
  local service="$1"
  local filter
  filter="$(build_filter)"
  if command -v journalctl >/dev/null 2>&1; then
    local unit
    unit="$(systemd_unit_for "$service")"
    local args=(-u "$unit" --since "$SINCE" --no-pager)
    if [[ "$FOLLOW" == "1" ]]; then
      args+=(-f)
    fi
    journalctl "${args[@]}" | filter_stream "$filter"
    return
  fi

  local log_file
  log_file="$(runtime_log_for "$service")"
  if [[ -z "$log_file" || ! -f "$log_file" ]]; then
    echo "no journalctl and no runtime log file for $service"
    exit 1
  fi
  if [[ "$FOLLOW" == "1" ]]; then
    tail -n 200 -f "$log_file" | filter_stream "$filter"
  else
    filter_file "$filter" "$log_file"
  fi
}

if [[ "$SERVICE" == "all" ]]; then
  for item in backend frontend worker nginx; do
    echo "===== $item ====="
    stream_one "$item"
  done
else
  stream_one "$SERVICE"
fi
