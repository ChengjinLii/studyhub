#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; please install Docker Engine / Docker Desktop first"
  exit 1
fi

docker compose -f "$COMPOSE_FILE" logs -f "$@"
