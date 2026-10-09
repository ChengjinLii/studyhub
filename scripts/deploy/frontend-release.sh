#!/usr/bin/env bash
set -euo pipefail

CONTROL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_ROOT="${STUDYHUB_RELEASE_ROOT:-/data/studyhub-runtime}"
FRONTEND_LINK="$RUNTIME_ROOT/frontend-current"
SMOKE_PORT="${STUDYHUB_RELEASE_FRONTEND_SMOKE_PORT:-13300}"
DROP_IN="/etc/systemd/system/studyhub-frontend.service.d/zz-frontend-release.conf"
COMMIT="${1:-}"
MANIFEST="${2:-}"
NODE_MAJOR="$(tr -d '[:space:]' < "$CONTROL_ROOT/.nvmrc")"
NPM_BIN="${STUDYHUB_NPM_BIN:-$(compgen -G "/opt/node-v${NODE_MAJOR}*/bin/npm" | sort -V | tail -1)}"
NODE_BIN_DIR="$(dirname "$NPM_BIN")"

if [[ -z "$COMMIT" || ! -f "$MANIFEST" ]]; then
  echo "usage: bash scripts/deploy/frontend-release.sh <commit> <paths-file>"
  exit 2
fi
if ! [[ "$RUNTIME_ROOT" =~ ^/[A-Za-z0-9_./-]+$ && "$SMOKE_PORT" =~ ^[0-9]+$ ]] \
  || (( SMOKE_PORT < 1024 || SMOKE_PORT > 65535 )); then
  echo "invalid runtime root or smoke port"
  exit 2
fi
if [[ ! -x "$NPM_BIN" || "$("$NODE_BIN_DIR/node" --version)" != v"$NODE_MAJOR".* ]]; then
  echo "project Node/npm executable not found or version mismatch"
  exit 1
fi
export PATH="$NODE_BIN_DIR:$PATH"
exec 9>"$RUNTIME_ROOT/deploy.lock"
flock -n 9 || { echo "another deployment is already running"; exit 1; }
if (( $(df -Pk "$RUNTIME_ROOT" | awk 'NR == 2 {print $4}') < 3 * 1024 * 1024 \
  || $(awk '/MemAvailable:/ {print $2}' /proc/meminfo) < 1024 * 1024 )); then
  echo "require 3 GiB disk and 1 GiB available memory"
  exit 1
fi
if [[ -n "$(ss -H -lnt "sport = :$SMOKE_PORT")" ]]; then
  echo "smoke port is already occupied: $SMOKE_PORT"
  exit 1
fi

PREVIOUS="$(readlink -f "$FRONTEND_LINK" 2>/dev/null || true)"
PREVIOUS="${PREVIOUS:-$(readlink -f "$RUNTIME_ROOT/current")}"
BASE_SHA="$(cat "$PREVIOUS/.frontend-base-git-sha" 2>/dev/null || cat "$PREVIOUS/.build-git-sha")"
BASE_SHA="$(git -C "$CONTROL_ROOT" rev-parse --verify "$BASE_SHA^{commit}")"
FULL_SHA="$(git -C "$CONTROL_ROOT" rev-parse --verify "$COMMIT^{commit}")"
SHORT_SHA="$(git -C "$CONTROL_ROOT" rev-parse --short=12 "$FULL_SHA")"
RELEASE="$RUNTIME_ROOT/frontend-releases/$SHORT_SHA"
[[ ! -e "$RELEASE" ]] || { echo "release already exists: $RELEASE"; exit 1; }

# Carry forward previous scoped changes without silently deploying unrelated files.
MANIFESTS=("$MANIFEST")
[[ ! -f "$PREVIOUS/.frontend-deployed-files" ]] || MANIFESTS+=("$PREVIOUS/.frontend-deployed-files")
mapfile -t FILES < <(sed '/^#/d; /^$/d' "${MANIFESTS[@]}" | sort -u)
(( ${#FILES[@]} > 0 )) || { echo "empty deployment manifest"; exit 2; }
for path in "${FILES[@]}"; do
  if [[ "$path" != frontend/* || "$path" == *../* || "$path" == */.. ]] \
    || [[ "$(git -C "$CONTROL_ROOT" cat-file -t "$FULL_SHA:$path")" != blob ]]; then
    echo "manifest entries must be tracked frontend files: $path"
    exit 2
  fi
done

SMOKE_PID=""
SWITCHED=0
HAD_DROP_IN=0
cleanup() {
  local status=$?
  [[ -z "$SMOKE_PID" ]] || { kill "$SMOKE_PID" 2>/dev/null || true; wait "$SMOKE_PID" 2>/dev/null || true; }
  if (( status != 0 && SWITCHED == 1 )); then
    echo "frontend deployment failed; restoring $PREVIOUS"
    switch_frontend "$PREVIOUS"
    if (( HAD_DROP_IN == 1 )); then
      sudo -n install -m 0644 "$RELEASE/frontend-only.previous.conf" "$DROP_IN"
    elif [[ -f "$DROP_IN" ]]; then
      sudo -n rm -- "$DROP_IN"
    fi
    sudo -n systemctl daemon-reload
    sudo -n systemctl restart studyhub-frontend.service
  fi
}
trap cleanup EXIT

switch_frontend() {
  local temporary="$RUNTIME_ROOT/.frontend-current-$SHORT_SHA-$$"
  ln -s "$1" "$temporary"
  mv -Tf "$temporary" "$FRONTEND_LINK"
}

mkdir -p "$RELEASE"
git -C "$CONTROL_ROOT" archive "$BASE_SHA" frontend | tar -x -C "$RELEASE"
git -C "$CONTROL_ROOT" archive "$FULL_SHA" "${FILES[@]}" | tar -x -C "$RELEASE"
printf '%s\n' "$SHORT_SHA" > "$RELEASE/.build-git-sha"
printf '%s\n' "$BASE_SHA" > "$RELEASE/.frontend-base-git-sha"
printf '%s\n' "${FILES[@]}" > "$RELEASE/.frontend-deployed-files"

echo "[1/5] install locked frontend dependencies and audit"
"$NPM_BIN" --prefix "$RELEASE/frontend" ci --no-audit --no-fund
STUDYHUB_FRONTEND_DIR="$RELEASE/frontend" STUDYHUB_AUDIT_NETWORK_POLICY=fail \
  bash "$CONTROL_ROOT/scripts/security/audit-frontend-dependencies.sh"

echo "[2/5] build isolated frontend"
(
  cd "$RELEASE/frontend"
  NEXT_PUBLIC_API_BASE=/api API_BASE_INTERNAL=http://127.0.0.1:8311/api \
  NEXT_PUBLIC_BUILD_GIT_SHA="$SHORT_SHA" "$NPM_BIN" run build
)
cp -a --no-clobber "$PREVIOUS/frontend/.next/static/." "$RELEASE/frontend/.next/static/"

echo "[3/5] smoke and test against the unchanged backend"
(
  cd "$RELEASE/frontend"
  exec env NODE_ENV=production NEXT_PUBLIC_API_BASE=/api API_BASE_INTERNAL=http://127.0.0.1:8311/api \
    "$NODE_BIN_DIR/node" node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port "$SMOKE_PORT"
) > "$RELEASE/frontend-smoke.log" 2>&1 &
SMOKE_PID=$!
SMOKE_BASE="http://127.0.0.1:$SMOKE_PORT"
for _attempt in $(seq 1 45); do
  if curl -fsS --max-time 3 "$SMOKE_BASE/" >/dev/null; then break; fi
  kill -0 "$SMOKE_PID" || { echo "isolated frontend exited"; exit 1; }
  sleep 1
done
curl -fsS --max-time 20 "$SMOKE_BASE/" >/dev/null
SMOKE_BASE_URL="$SMOKE_BASE" "$NPM_BIN" --prefix "$CONTROL_ROOT/frontend" run test:critical -- --workers=1 --reporter=line
STUDYHUB_PREWARM_BASE_URL="$SMOKE_BASE" STUDYHUB_PREWARM_STRICT=1 \
  "$NODE_BIN_DIR/node" "$RELEASE/frontend/scripts/prewarm-public-pages.mjs"
kill "$SMOKE_PID"
wait "$SMOKE_PID" 2>/dev/null || true
SMOKE_PID=""

echo "[4/5] switch frontend only"
if [[ -f "$DROP_IN" ]]; then
  HAD_DROP_IN=1
  cp "$DROP_IN" "$RELEASE/frontend-only.previous.conf"
fi
printf '[Service]\nWorkingDirectory=%s/frontend\n' "$FRONTEND_LINK" > "$RELEASE/frontend-only.conf"
SWITCHED=1
switch_frontend "$RELEASE"
sudo -n install -m 0644 "$RELEASE/frontend-only.conf" "$DROP_IN"
sudo -n systemctl daemon-reload
sudo -n systemctl restart studyhub-frontend.service
for _attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:3300/ >/dev/null; then break; fi
  sleep 1
done
curl -fsS --max-time 20 http://127.0.0.1:3300/ >/dev/null
sudo -n systemctl is-active --quiet studyhub-frontend.service

echo "[5/5] frontend deployed: $SHORT_SHA; previous=$PREVIOUS; base=$BASE_SHA"
