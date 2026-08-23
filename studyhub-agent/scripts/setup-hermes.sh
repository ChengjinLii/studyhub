#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCK_FILE="${AGENT_DIR}/integrations/hermes/upstream.lock.json"
CHECKOUT_DIR="${STUDYHUB_HERMES_DIR:-${AGENT_DIR}/.vendor/hermes-agent}"

if [[ ! -f "${LOCK_FILE}" ]]; then
  printf 'Hermes lock file not found: %s\n' "${LOCK_FILE}" >&2
  exit 1
fi

mapfile -t LOCK_VALUES < <(
  python3 - "${LOCK_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    lock = json.load(handle)

repository = str(lock.get("repository", "")).strip()
commit = str(lock.get("commit", "")).strip()
if not repository or not commit:
    raise SystemExit("Hermes lock file must define repository and commit")
print(repository)
print(commit)
PY
)

HERMES_REPOSITORY="${LOCK_VALUES[0]}"
HERMES_COMMIT="${LOCK_VALUES[1]}"

if [[ -e "${CHECKOUT_DIR}" && ! -d "${CHECKOUT_DIR}/.git" ]]; then
  printf 'Refusing to replace non-Git path: %s\n' "${CHECKOUT_DIR}" >&2
  exit 1
fi

if [[ ! -d "${CHECKOUT_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${CHECKOUT_DIR}")"
  git clone --filter=blob:none --no-checkout "${HERMES_REPOSITORY}" "${CHECKOUT_DIR}"
else
  CURRENT_REMOTE="$(git -C "${CHECKOUT_DIR}" remote get-url origin)"
  if [[ "${CURRENT_REMOTE%.git}" != "${HERMES_REPOSITORY%.git}" ]]; then
    printf 'Hermes checkout has unexpected origin: %s\n' "${CURRENT_REMOTE}" >&2
    exit 1
  fi
  if [[ -n "$(git -C "${CHECKOUT_DIR}" status --porcelain --untracked-files=no)" ]]; then
    printf 'Hermes checkout has tracked local changes; refusing to overwrite them.\n' >&2
    exit 1
  fi
fi

git -C "${CHECKOUT_DIR}" fetch --depth=1 origin "${HERMES_COMMIT}"
git -C "${CHECKOUT_DIR}" checkout --detach "${HERMES_COMMIT}"

ACTUAL_COMMIT="$(git -C "${CHECKOUT_DIR}" rev-parse HEAD)"
if [[ "${ACTUAL_COMMIT}" != "${HERMES_COMMIT}" ]]; then
  printf 'Hermes checkout mismatch: expected %s, got %s\n' "${HERMES_COMMIT}" "${ACTUAL_COMMIT}" >&2
  exit 1
fi

printf 'Hermes checkout ready: %s\n' "${CHECKOUT_DIR}"
printf 'Pinned commit: %s\n' "${ACTUAL_COMMIT}"
