#!/usr/bin/env bash
set -euo pipefail

# Patch only this feature onto the running baseline. Never implicitly deploy
# unrelated main changes or rebuild the online frontend from this command.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="${STUDYHUB_RELEASE_ROOT:-/data/studyhub-runtime}"
SOURCE_BASE="$(git -C "$ROOT" rev-parse --verify "${1:?source base commit required}^{commit}")"
TARGET="$(git -C "$ROOT" rev-parse --verify "${2:?target commit required}^{commit}")"
PREVIOUS="$(readlink -e "$RUNTIME/current")"
BASE="$(cat "$PREVIOUS/.backend-base-git-sha" 2>/dev/null || cat "$PREVIOUS/.build-git-sha")"
RELEASE="$RUNTIME/releases/${TARGET:0:12}-preview"
PORT=18311
exec 9>"$RUNTIME/deploy.lock"
flock -n 9 || { echo "deployment already running"; exit 1; }
[[ ! -e "$RELEASE" && -z "$(ss -H -lnt "sport = :$PORT")" ]]
(( $(df -Pk "$RUNTIME" | awk 'NR == 2 {print $4}') >= 1024 * 1024 ))
FILES=(backend/app/api/routes/materials.py backend/app/services/materials_compat.py
  backend/app/services/materials_service.py backend/app/services/materials_storage_mutation.py backend/app/services/requests_service.py
  backend/app/services/material_preview_service.py backend/app/services/material_preview_renderer.py
  backend/app/services/material_preview_state.py backend/app/repos/material_preview_repo.py
  backend/app/ops/material_previews.py backend/tests/test_material_preview_generation.py)

SMOKE_PID=""
SWITCHED=0
cleanup() {
  local status=$?
  [[ -z "$SMOKE_PID" ]] || { kill "$SMOKE_PID" 2>/dev/null || true; wait "$SMOKE_PID" 2>/dev/null || true; }
  if (( status != 0 && SWITCHED == 1 )); then
    ln -s "$PREVIOUS" "$RUNTIME/.backend-rollback-$$"
    mv -Tf "$RUNTIME/.backend-rollback-$$" "$RUNTIME/current"
    sudo -n systemctl restart studyhub-backend.service studyhub-worker.service
  fi
}
trap cleanup EXIT
mkdir -p "$RELEASE"
git -C "$ROOT" archive "$BASE" | tar -x -C "$RELEASE"
git -C "$ROOT" diff --binary "$SOURCE_BASE" "$TARGET" -- "${FILES[@]}" > "$RELEASE/preview-feature.patch"
git -C "$RELEASE" apply --check "$RELEASE/preview-feature.patch"
git -C "$RELEASE" apply "$RELEASE/preview-feature.patch"
git -C "$ROOT" archive "$TARGET" backend/app/services/material_lightweight_scanner.py backend/requirements-preview.lock \
  | tar -x -C "$RELEASE"
ln -s "$ROOT/private" "$RELEASE/private"
printf '%s\n' "$TARGET" > "$RELEASE/.build-git-sha"
printf '%s\n' "$BASE" > "$RELEASE/.backend-base-git-sha"
printf '%s\n' "$SOURCE_BASE" > "$RELEASE/.preview-source-base"

# Copy, do not hardlink, installed packages. A separate interpreter ensures the
# PDFium addition cannot upgrade or mutate dependencies of the rollback release.
python3.12 -m venv "$RELEASE/.venv"
cp -a "$PREVIOUS/.venv/lib/python3.12/site-packages/." "$RELEASE/.venv/lib/python3.12/site-packages/"
PIP_INDEX_URL=https://pypi.org/simple "$RELEASE/.venv/bin/python" -m pip install --no-cache-dir --no-deps \
  --require-hashes -r "$RELEASE/backend/requirements-preview.lock"
"$RELEASE/.venv/bin/python" -m pip check
# The systemd unit's existing executable path stays valid with this interpreter.
printf '#!%s/.venv/bin/python\nfrom uvicorn.main import main\nmain()\n' "$RELEASE" > "$RELEASE/.venv/bin/uvicorn"
chmod 0755 "$RELEASE/.venv/bin/uvicorn"
(
  cd "$RELEASE/backend"
  "$RELEASE/.venv/bin/python" -m pytest tests/test_material_preview_generation.py -q
  exec env STUDYHUB_ENVIRONMENT=production STUDYHUB_PRIVATE_DIR_PATH="$ROOT/private" \
    "$RELEASE/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
) > "$RELEASE/backend-smoke.log" 2>&1 &
SMOKE_PID=$!
for _ in $(seq 1 90); do
  if curl -fsS --max-time 3 -H 'Host: study-hub.cn' "http://127.0.0.1:$PORT/api/readyz" >/dev/null; then break; fi
  kill -0 "$SMOKE_PID" || { echo "backend smoke failed; inspect $RELEASE/backend-smoke.log"; exit 1; }
  sleep 1
done
curl -fsS --max-time 20 -H 'Host: study-hub.cn' "http://127.0.0.1:$PORT/api/materials?size=1" >/dev/null
kill "$SMOKE_PID"
wait "$SMOKE_PID" 2>/dev/null || true
SMOKE_PID=""
ln -s "$RELEASE" "$RUNTIME/.backend-current-$$"
SWITCHED=1
mv -Tf "$RUNTIME/.backend-current-$$" "$RUNTIME/current"
sudo -n systemctl restart studyhub-backend.service studyhub-worker.service
for _ in $(seq 1 45); do
  if curl -fsS --max-time 3 -H 'Host: study-hub.cn' http://127.0.0.1:8311/api/readyz >/dev/null; then break; fi
  sleep 1
done
curl -fsS --max-time 20 -H 'Host: study-hub.cn' http://127.0.0.1:8311/api/readyz >/dev/null
echo "Preview backend deployed: $RELEASE; frontend and database schema unchanged."
