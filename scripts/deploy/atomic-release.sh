#!/usr/bin/env bash
set -euo pipefail

CONTROL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_ROOT="${STUDYHUB_RELEASE_ROOT:-/data/studyhub-runtime}"
RELEASES_ROOT="$RUNTIME_ROOT/releases"
CURRENT_LINK="$RUNTIME_ROOT/current"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$CONTROL_ROOT/private}"
COMMIT="${1:-HEAD}"
KEEP_RELEASES="${STUDYHUB_RELEASE_KEEP:-3}"
BACKEND_SMOKE_PORT="${STUDYHUB_RELEASE_BACKEND_SMOKE_PORT:-18311}"
FRONTEND_SMOKE_PORT="${STUDYHUB_RELEASE_FRONTEND_SMOKE_PORT:-13300}"
LOCK_FILE="$RUNTIME_ROOT/deploy.lock"

if ! [[ "$KEEP_RELEASES" =~ ^[2-9][0-9]*$ ]]; then
  echo "STUDYHUB_RELEASE_KEEP must be an integer >= 2"
  exit 2
fi
for port in "$BACKEND_SMOKE_PORT" "$FRONTEND_SMOKE_PORT"; do
  if ! [[ "$port" =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
    echo "invalid smoke port: $port"
    exit 2
  fi
done

mkdir -p "$RELEASES_ROOT"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "another deployment is already running"
  exit 1
fi

FULL_SHA="$(git -C "$CONTROL_ROOT" rev-parse --verify "$COMMIT^{commit}")"
SHORT_SHA="$(git -C "$CONTROL_ROOT" rev-parse --short=12 "$FULL_SHA")"
RELEASE="$RELEASES_ROOT/$SHORT_SHA"
PREVIOUS="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
BACKEND_PID=""
FRONTEND_PID=""

cleanup_smoke() {
  [[ -z "$FRONTEND_PID" ]] || kill "$FRONTEND_PID" 2>/dev/null || true
  [[ -z "$BACKEND_PID" ]] || kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup_smoke EXIT

if [[ -e "$RELEASE" ]]; then
  echo "release already exists: $RELEASE"
  exit 1
fi
mkdir "$RELEASE"
git -C "$CONTROL_ROOT" archive "$FULL_SHA" | tar -x -C "$RELEASE"
ln -s "$PRIVATE_DIR" "$RELEASE/private"

echo "[1/5] install locked dependencies"
python3.12 -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/python" -m pip install --disable-pip-version-check --require-hashes -r "$RELEASE/backend/requirements.lock"
npm --prefix "$RELEASE/frontend" ci --no-audit --no-fund

echo "[2/5] build frontend in isolated release"
(
  cd "$RELEASE/frontend"
  NEXT_PUBLIC_API_BASE=/api \
  NEXT_PUBLIC_BUILD_GIT_SHA="$SHORT_SHA" \
  npm run build
)

echo "[3/5] smoke isolated release"
(
  cd "$RELEASE/backend"
  STUDYHUB_ENVIRONMENT=production \
  STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR" \
  STUDYHUB_BUILD_GIT_SHA="$SHORT_SHA" \
  "$RELEASE/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$BACKEND_SMOKE_PORT" \
    --limit-concurrency 32 --backlog 64 --timeout-keep-alive 3
) >"$RELEASE/backend-smoke.log" 2>&1 &
BACKEND_PID=$!
(
  cd "$RELEASE/frontend"
  NODE_ENV=production \
  NEXT_PUBLIC_API_BASE=/api \
  API_BASE_URL="http://127.0.0.1:$BACKEND_SMOKE_PORT/api" \
  API_BASE_INTERNAL="http://127.0.0.1:$BACKEND_SMOKE_PORT/api" \
  npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_SMOKE_PORT"
) >"$RELEASE/frontend-smoke.log" 2>&1 &
FRONTEND_PID=$!

for _attempt in $(seq 1 60); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$BACKEND_SMOKE_PORT/api/readyz" >/dev/null \
    && curl -fsS --max-time 2 "http://127.0.0.1:$FRONTEND_SMOKE_PORT/" >/dev/null; then
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "isolated release process exited; inspect $RELEASE/*-smoke.log"
    exit 1
  fi
  sleep 2
done
STUDYHUB_PUBLIC_SMOKE_BASES=none \
STUDYHUB_SMOKE_EXPECTED_GIT_SHA="$SHORT_SHA" \
STUDYHUB_PYTHON_BIN="$RELEASE/.venv/bin/python" \
bash "$RELEASE/scripts/runtime/production-smoke.sh" \
  "http://127.0.0.1:$BACKEND_SMOKE_PORT" "http://127.0.0.1:$FRONTEND_SMOKE_PORT"
cleanup_smoke
BACKEND_PID=""
FRONTEND_PID=""

switch_current() {
  local target="$1"
  local temporary="$RUNTIME_ROOT/.current-$SHORT_SHA-$$"
  ln -s "$target" "$temporary"
  mv -Tf "$temporary" "$CURRENT_LINK"
}

rollback() {
  if [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]]; then
    echo "deployment failed; rolling back to $PREVIOUS"
    sudo -n systemctl stop studyhub-frontend.service studyhub-worker.service || true
    switch_current "$PREVIOUS"
    sudo -n systemctl restart studyhub-backend.service || true
    for _attempt in $(seq 1 45); do
      if curl -fsS --max-time 2 http://127.0.0.1:8311/api/readyz >/dev/null; then
        break
      fi
      sleep 1
    done
    sudo -n systemctl restart studyhub-worker.service studyhub-frontend.service || true
  fi
}

echo "[4/5] switch current and restart services"
sudo -n systemctl stop studyhub-frontend.service studyhub-worker.service
switch_current "$RELEASE"
if ! sudo -n systemctl restart studyhub-backend.service; then
  rollback
  exit 1
fi

for _attempt in $(seq 1 45); do
  if curl -fsS --max-time 2 http://127.0.0.1:8311/api/readyz >/dev/null; then
    break
  fi
  sleep 2
done
if ! curl -fsS --max-time 2 http://127.0.0.1:8311/api/readyz >/dev/null; then
  rollback
  exit 1
fi
if ! sudo -n systemctl restart studyhub-worker.service studyhub-frontend.service; then
  rollback
  exit 1
fi
for _attempt in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:3300/ >/dev/null; then
    break
  fi
  sleep 1
done
if ! STUDYHUB_SMOKE_EXPECTED_GIT_SHA="$SHORT_SHA" bash "$RELEASE/scripts/runtime/production-smoke.sh"; then
  rollback
  exit 1
fi

echo "[5/5] prune old releases"
mapfile -t releases < <(find "$RELEASES_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
for old_release in "${releases[@]:$KEEP_RELEASES}"; do
  if [[ "$old_release" != "$PREVIOUS" && "$old_release" != "$(readlink -f "$CURRENT_LINK")" ]]; then
    rm -rf --one-file-system "$old_release"
  fi
done
echo "deployed $SHORT_SHA; previous=${PREVIOUS:-none}"
