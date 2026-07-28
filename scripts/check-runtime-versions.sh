#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-python3}"

node_major="$(node -p 'process.versions.node.split(".")[0]')"
npm_major="$(npm --version | cut -d. -f1)"
python_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if [[ "$node_major" != "22" ]]; then
  echo "Node.js 22 is required; found $(node --version)" >&2
  exit 1
fi
if [[ "$npm_major" != "10" ]]; then
  echo "npm 10 is required; found $(npm --version)" >&2
  exit 1
fi
if [[ "$python_version" != "3.12" ]]; then
  echo "Python 3.12 is required; found $("$PYTHON_BIN" --version 2>&1)" >&2
  exit 1
fi

echo "Runtime versions OK: Node $(node --version), npm $(npm --version), Python $python_version"
