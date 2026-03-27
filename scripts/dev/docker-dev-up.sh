#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; please install Docker Engine / Docker Desktop first"
  exit 1
fi

mkdir -p "$ROOT_DIR/.local-dev-docker"

docker compose -f "$COMPOSE_FILE" up -d --build "$@"

cat <<'EOF'
docker local-dev started
frontend: http://127.0.0.1:3100
backend:  http://127.0.0.1:8111/api/healthz
mysql:    127.0.0.1:3307
EOF
