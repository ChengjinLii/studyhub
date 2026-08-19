#!/usr/bin/env bash
set -euo pipefail

AGENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${HOME}/.local/bin"

mkdir -p "$INSTALL_DIR"
ln -sfn "$AGENT_ROOT/bin/studyhub-agent" "$INSTALL_DIR/studyhub-agent"
printf 'Installed %s -> %s\n' "$INSTALL_DIR/studyhub-agent" "$AGENT_ROOT/bin/studyhub-agent"
