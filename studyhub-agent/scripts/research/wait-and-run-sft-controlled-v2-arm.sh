#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPERIMENT_ID="${1:?usage: wait-and-run-sft-controlled-v2-arm.sh EXPERIMENT_ID SEED GPU [RUN_OPTIONS...]}"
SEED="${2:?missing seed}"
GPU="${3:?missing GPU index}"
shift 3

POLL_SECONDS="${STUDYHUB_SFT_IDLE_POLL_SECONDS:-30}"
IDLE_LIMIT_MIB="${STUDYHUB_SFT_IDLE_LIMIT_MIB:-1024}"
REQUIRED_IDLE_SAMPLES="${STUDYHUB_SFT_REQUIRED_IDLE_SAMPLES:-3}"
idle_samples=0

while (( idle_samples < REQUIRED_IDLE_SAMPLES )); do
  used_mib="$(
    nvidia-smi -i "$GPU" \
      --query-gpu=memory.used \
      --format=csv,noheader,nounits | tr -d ' '
  )"
  if (( used_mib <= IDLE_LIMIT_MIB )); then
    ((idle_samples += 1))
  else
    idle_samples=0
  fi
  printf '[wait-sft] gpu=%s used=%sMiB idle_samples=%s/%s\n' \
    "$GPU" "$used_mib" "$idle_samples" "$REQUIRED_IDLE_SAMPLES"
  if (( idle_samples < REQUIRED_IDLE_SAMPLES )); then
    sleep "$POLL_SECONDS"
  fi
done

exec "$ROOT_DIR/scripts/research/run-sft-controlled-v2-arm.sh" \
  "$EXPERIMENT_ID" "$SEED" "$GPU" "$@"
