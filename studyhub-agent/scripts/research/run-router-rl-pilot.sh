#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
CONFIG="${1:-$ROOT_DIR/ml/agentic_platform/rl/configs/router_grpo_pilot_v1.json}"
GPU_ID="${STUDYHUB_RL_GPU:-1}"
SEEDS="${STUDYHUB_RL_SEEDS:-3407 7703 9109}"
OUTPUT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1/runs"

if [[ ! -x "$TRAIN_PYTHON" || ! -f "$CONFIG" ]]; then
  echo "RL Python or config is missing" >&2
  exit 2
fi
GPU_USED_MIB="$(nvidia-smi -i "$GPU_ID" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')"
if (( GPU_USED_MIB > 1024 )); then
  echo "GPU $GPU_ID is not idle (${GPU_USED_MIB} MiB used); refusing to interfere" >&2
  exit 3
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-training"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

monitor_gpu() {
  local pid="$1"
  local destination="$2"
  while kill -0 "$pid" 2>/dev/null; do
    nvidia-smi -i "$GPU_ID" \
      --query-gpu=timestamp,index,name,memory.used,utilization.gpu,temperature.gpu,power.draw \
      --format=csv,noheader,nounits >> "$destination" || true
    sleep 1
  done
}

for seed in $SEEDS; do
  if [[ ! "$seed" =~ ^[1-9][0-9]*$ ]]; then
    echo "invalid RL seed: $seed" >&2
    exit 2
  fi
  run_dir="$OUTPUT_ROOT/seed_$seed"
  if [[ -e "$run_dir/run_summary.json" || -e "$run_dir/trainer_metrics.jsonl" ]]; then
    echo "RL seed output already exists: $run_dir" >&2
    exit 4
  fi
  mkdir -p "$run_dir"
  gpu_csv="$run_dir/gpu_samples.csv"
  printf 'timestamp,index,name,memory_used_mib,gpu_util_percent,temperature_c,power_w\n' > "$gpu_csv"
  (
    cd "$ROOT_DIR"
    CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.trainer \
      --config "$CONFIG" \
      --seed "$seed" \
      --output-dir "$run_dir"
  ) > >(tee "$run_dir/train.log") 2>&1 &
  train_pid=$!
  monitor_gpu "$train_pid" "$gpu_csv" &
  monitor_pid=$!
  set +e
  wait "$train_pid"
  status=$?
  wait "$monitor_pid" 2>/dev/null
  set -e
  if (( status != 0 )); then
    echo "RL seed $seed failed with exit code $status" >&2
    exit "$status"
  fi
done
