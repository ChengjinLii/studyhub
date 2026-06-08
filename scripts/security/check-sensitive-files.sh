#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

violations=()

check_path() {
  local path="$1"
  local scope="$2"

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
    *id_rsa*|*id_ed25519*|*.npmrc)
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
  check_path "$path" "historical"
done < <(git rev-list --objects --all)

if [[ "${#violations[@]}" -gt 0 ]]; then
  echo "Sensitive file check failed:"
  printf -- '- %s\n' "${violations[@]}"
  exit 2
fi

echo "Sensitive file check passed."
