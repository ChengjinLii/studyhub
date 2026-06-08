#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
LOCAL_DEV_ROOT="${STUDYHUB_LOCAL_DEV_ROOT_DIR:-$ROOT_DIR/.local-dev}"
BACKEND_PORT="${LOCAL_DEV_BACKEND_PORT:-8011}"
FRONTEND_PORT="${LOCAL_DEV_FRONTEND_PORT:-3000}"

ISSUES=0
WARNINGS=0

ok() {
  echo "[ok] $1"
}

warn() {
  echo "[warn] $1"
  WARNINGS=$((WARNINGS + 1))
}

fail() {
  echo "[fail] $1"
  ISSUES=$((ISSUES + 1))
}

section() {
  printf '\n[%s]\n' "$1"
}

command_version() {
  local command_name="$1"
  shift
  if command -v "$command_name" >/dev/null 2>&1; then
    local version_output
    version_output="$("$command_name" "$@" 2>/dev/null | head -n 1 || true)"
    ok "$command_name ${version_output:-found}"
    return 0
  fi
  warn "$command_name not found"
  return 1
}

port_probe() {
  local port="$1"
  local label="$2"
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 1 "http://127.0.0.1:$port" >/dev/null 2>&1; then
    ok "$label responds on 127.0.0.1:$port"
    return 0
  fi
  warn "$label is not responding on 127.0.0.1:$port"
}

pid_probe() {
  local pid_file="$1"
  local label="$2"
  if [[ ! -f "$pid_file" ]]; then
    warn "$label pid file not found"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    ok "$label process is running (pid=$pid)"
  else
    warn "$label pid file is stale"
  fi
}

section "repository"
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ok "repository root: $ROOT_DIR"
else
  fail "not a git repository: $ROOT_DIR"
fi

if [[ -f "$ROOT_DIR/docker-compose.yml" ]]; then
  ok "docker-compose.yml found"
else
  fail "docker-compose.yml not found"
fi

if [[ -f "$BACKEND_DIR/pyproject.toml" ]]; then
  ok "backend project found"
else
  fail "backend/pyproject.toml not found"
fi

if [[ -f "$FRONTEND_DIR/package-lock.json" ]]; then
  ok "frontend package lock found"
else
  fail "frontend/package-lock.json not found"
fi

section "toolchain"
DOCKER_READY=0
if command -v docker >/dev/null 2>&1; then
  ok "docker $(docker --version 2>/dev/null | head -n 1)"
  if docker compose version >/dev/null 2>&1; then
    ok "docker compose $(docker compose version 2>/dev/null | head -n 1)"
    DOCKER_READY=1
  else
    warn "docker compose plugin not available"
  fi
else
  warn "docker not found"
fi

NODE_READY=0
NPM_READY=0
PYTHON_READY=0
command_version node --version && NODE_READY=1
command_version npm --version && NPM_READY=1
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  ok "$ROOT_DIR/.venv/bin/python $("$ROOT_DIR/.venv/bin/python" --version 2>&1)"
  PYTHON_READY=1
else
  warn "missing Python virtualenv: $ROOT_DIR/.venv/bin/python"
fi

section "local-dev inputs"
if [[ -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
  ok "uvicorn found in .venv"
else
  warn "missing uvicorn: $ROOT_DIR/.venv/bin/uvicorn"
fi

if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
  ok "frontend/node_modules found"
else
  warn "frontend dependencies missing; run npm --prefix frontend ci"
fi

if [[ -d "$LOCAL_DEV_ROOT" ]]; then
  ok "local-dev root exists: $LOCAL_DEV_ROOT"
else
  warn "local-dev root has not been created yet: $LOCAL_DEV_ROOT"
fi

SHELL_READY=0
if [[ "$NODE_READY" -eq 1 && "$NPM_READY" -eq 1 && "$PYTHON_READY" -eq 1 && -x "$ROOT_DIR/.venv/bin/uvicorn" && -d "$FRONTEND_DIR/node_modules" ]]; then
  SHELL_READY=1
fi

section "runtime probes"
pid_probe "$LOCAL_DEV_ROOT/run/backend.pid" "local-dev backend"
pid_probe "$LOCAL_DEV_ROOT/run/frontend.pid" "local-dev frontend"
port_probe "$BACKEND_PORT/api/healthz" "local-dev backend health"
port_probe "$FRONTEND_PORT" "local-dev frontend"

section "summary"
if [[ "$DOCKER_READY" -eq 1 ]]; then
  ok "Docker local-dev path is available"
else
  warn "Docker local-dev path is not ready"
fi

if [[ "$SHELL_READY" -eq 1 ]]; then
  ok "Shell quickstart path is available"
else
  warn "Shell quickstart path is not ready"
fi

if [[ "$DOCKER_READY" -ne 1 && "$SHELL_READY" -ne 1 ]]; then
  fail "no local development path is ready"
fi

if [[ "$ISSUES" -gt 0 ]]; then
  echo "doctor found $ISSUES issue(s) and $WARNINGS warning(s)."
  exit 1
fi

if [[ "$WARNINGS" -gt 0 ]]; then
  echo "doctor completed with $WARNINGS warning(s)."
else
  echo "doctor passed."
fi
