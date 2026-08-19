#!/usr/bin/env bash
set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="$AGENT_ROOT/integrations/hermes/upstream.lock.json"
TARGET="${1:-$AGENT_ROOT/.vendor/hermes-agent}"

read_lock() {
  python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$LOCK_FILE" "$1"
}

REPOSITORY="$(read_lock repository)"
COMMIT="$(read_lock commit)"
PATCH_RELATIVE="$(read_lock patch)"
PATCH_SHA256="$(read_lock patch_sha256)"
PATCH_FILE="$AGENT_ROOT/integrations/hermes/$PATCH_RELATIVE"

ACTUAL_PATCH_SHA256="$(sha256sum "$PATCH_FILE" | awk '{print $1}')"
if [[ "$ACTUAL_PATCH_SHA256" != "$PATCH_SHA256" ]]; then
  printf 'Hermes patch checksum mismatch.\n' >&2
  exit 2
fi

if [[ ! -d "$TARGET/.git" ]]; then
  mkdir -p "$TARGET"
  git -C "$TARGET" init
  git -C "$TARGET" remote add origin "$REPOSITORY"
  git -C "$TARGET" fetch --depth 1 origin "$COMMIT"
  git -C "$TARGET" checkout --detach FETCH_HEAD
fi

ACTUAL_COMMIT="$(git -C "$TARGET" rev-parse HEAD)"
if [[ "$ACTUAL_COMMIT" != "$COMMIT" ]]; then
  printf 'Hermes checkout is at %s; expected %s. Refusing to overwrite it.\n' \
    "$ACTUAL_COMMIT" "$COMMIT" >&2
  exit 2
fi

if git -C "$TARGET" apply --check --reverse "$PATCH_FILE" >/dev/null 2>&1; then
  printf 'StudyHub Hermes patch already applied at %s\n' "$TARGET"
elif git -C "$TARGET" apply --check "$PATCH_FILE" >/dev/null 2>&1; then
  git -C "$TARGET" apply "$PATCH_FILE"
  printf 'Applied StudyHub Hermes patch at %s\n' "$TARGET"
else
  printf 'Hermes checkout has conflicting changes; patch was not applied.\n' >&2
  exit 2
fi

printf 'Hermes source is ready. Install its dependencies in a local virtual environment before launching.\n'
