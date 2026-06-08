#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

violations=()

while IFS= read -r path; do
  case "$path" in
    .env.example|*/.env.example)
      continue
      ;;
  esac

  case "$path" in
    .env|*/.env|.env.*|*/.env.*)
      violations+=("$path: tracked env file")
      ;;
    private|private/*|*/private|*/private/*)
      violations+=("$path: tracked private path")
      ;;
    *.pem|*.key|*.p12|*.pfx|*.crt|*.cer)
      violations+=("$path: tracked key or certificate file")
      ;;
    *id_rsa*|*id_ed25519*|*.npmrc)
      violations+=("$path: tracked credential-like file")
      ;;
  esac
done < <(git ls-files)

if [[ "${#violations[@]}" -gt 0 ]]; then
  echo "Sensitive file check failed:"
  printf -- '- %s\n' "${violations[@]}"
  exit 2
fi

echo "Sensitive file check passed."
