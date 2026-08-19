#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TASK="${1:?usage: start-sft-controlled-v2-matrix.sh TASK GPU}"
GPU="${2:?missing GPU index}"

if [[ "$TASK" != "router" && "$TASK" != "tutor" ]]; then
  echo "TASK must be router or tutor" >&2
  exit 2
fi
if [[ "$GPU" != "0" && "$GPU" != "1" ]]; then
  echo "GPU must be 0 or 1" >&2
  exit 2
fi

QUEUE_DIR="$ROOT_DIR/training_artifacts/studyhub_agent_sft/controlled_v2/queue"
RUNNER="$ROOT_DIR/scripts/research/run-sft-controlled-v2-matrix.sh"
PID_FILE="$QUEUE_DIR/${TASK}_matrix_gpu${GPU}.pid"
LOG_FILE="$QUEUE_DIR/${TASK}_matrix_gpu${GPU}.log"
mkdir -p "$QUEUE_DIR"

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(tr -cd '0-9' < "$PID_FILE")"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    existing_command="$(ps -p "$existing_pid" -o args= 2>/dev/null || true)"
    if [[ "$existing_command" == *"run-sft-controlled-v2-matrix.sh $TASK $GPU"* ]]; then
      echo "matrix already running: task=$TASK gpu=$GPU pid=$existing_pid"
      exit 0
    fi
    echo "PID file points to an unrelated live process: $existing_pid" >&2
    exit 4
  fi
fi

printf '\n[%s] detached launch task=%s gpu=%s\n' \
  "$(date --iso-8601=seconds)" "$TASK" "$GPU" >> "$LOG_FILE"
nohup setsid "$RUNNER" "$TASK" "$GPU" >> "$LOG_FILE" 2>&1 < /dev/null &
matrix_pid=$!
pid_tmp="${PID_FILE}.tmp.$$"
printf '%s\n' "$matrix_pid" > "$pid_tmp"
mv "$pid_tmp" "$PID_FILE"

sleep 2
if ! kill -0 "$matrix_pid" 2>/dev/null; then
  wait "$matrix_pid" || launch_rc=$?
  echo "matrix failed during launch: task=$TASK gpu=$GPU rc=${launch_rc:-0}" >&2
  tail -n 20 "$LOG_FILE" >&2
  exit "${launch_rc:-1}"
fi

echo "matrix started: task=$TASK gpu=$GPU pid=$matrix_pid log=$LOG_FILE"
