#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

violations=()

safe_npmrc() {
  local path="$1"
  local object_id="${2:-}"
  local content
  if [[ -n "$object_id" ]]; then
    content="$(git cat-file blob "$object_id" 2>/dev/null)" || return 1
  else
    [[ -f "$path" ]] || return 1
    content="$(<"$path")"
  fi
  [[ "$content" == $'engine-strict=true\nsave-exact=true' ]]
}

check_path() {
  local path="$1"
  local scope="$2"
  local object_id="${3:-}"

  case "$path" in
    .env.example|*/.env.example)
      return
      ;;
  esac

  case "$path" in
    .env|*/.env|.env.*|*/.env.*)
      violations+=("$path: $scope env file")
      ;;
    private|private/*|*/private|*/private/*)
      violations+=("$path: $scope private path")
      ;;
    *.pem|*.key|*.p12|*.pfx|*.crt|*.cer)
      violations+=("$path: $scope key or certificate file")
      ;;
    *.npmrc)
      if ! safe_npmrc "$path" "$object_id"; then
        violations+=("$path: $scope credential-like file")
      fi
      ;;
    *id_rsa*|*id_ed25519*)
      violations+=("$path: $scope credential-like file")
      ;;
  esac
}

while IFS= read -r path; do
  check_path "$path" "tracked"
done < <(git ls-files)

while IFS= read -r object_and_path; do
  path="${object_and_path#* }"
  if [[ "$path" == "$object_and_path" || -z "$path" ]]; then
    continue
  fi
  object_id="${object_and_path%% *}"
  check_path "$path" "historical" "$object_id"
done < <(git rev-list --objects --all)

while IFS= read -r match; do
  [[ -z "$match" ]] && continue
  violations+=("$match: tracked operational recipient must come from private environment configuration")
done < <(git grep -nI -E -- '--alert-email([=[:space:]]+)[^[:space:]]+@[^[:space:]]+' -- deploy scripts 2>/dev/null || true)

if [[ "${#violations[@]}" -gt 0 ]]; then
  echo "Sensitive file check failed:"
  printf -- '- %s\n' "${violations[@]}"
  exit 2
fi

echo "Sensitive file check passed."
