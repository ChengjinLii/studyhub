#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_PATH="${1:?usage: run-sft-with-telemetry.sh CONFIG [RUN_LABEL]}"
if [[ "$CONFIG_PATH" != /* ]]; then
  CONFIG_PATH="$ROOT_DIR/$CONFIG_PATH"
fi
CONFIG_PATH="$(realpath "$CONFIG_PATH")"
RUN_LABEL="${2:-$(basename "$CONFIG_PATH" .yaml)}"
GPU_ID="${STUDYHUB_SFT_GPU:-0}"
CLI="${STUDYHUB_LLAMFACTORY_CLI:-/data/chengjin/LLaMA-Factory/.venv/bin/llamafactory-cli}"
TELEMETRY_ROOT="${STUDYHUB_SFT_TELEMETRY_ROOT:-$ROOT_DIR/training_artifacts/studyhub_agent_sft/run_telemetry}"
RUN_DIR="$TELEMETRY_ROOT/$RUN_LABEL"
GPU_CSV="$RUN_DIR/gpu_samples.csv"
GPU_PROCESS_CSV="$RUN_DIR/gpu_process_samples.csv"
TRAIN_LOG="$RUN_DIR/train.log"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "training config not found: $CONFIG_PATH" >&2
  exit 2
fi
if [[ ! -x "$CLI" ]]; then
  echo "LLaMA-Factory CLI not executable: $CLI" >&2
  exit 2
fi
if [[ -e "$RUN_DIR/run_summary.json" ]]; then
  echo "telemetry run already finalized: $RUN_DIR" >&2
  exit 2
fi

GPU_USED_MIB="$(nvidia-smi -i "$GPU_ID" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')"
if (( GPU_USED_MIB > 1024 )); then
  echo "GPU $GPU_ID is not idle (${GPU_USED_MIB} MiB used); refusing to interfere" >&2
  exit 3
fi

mkdir -p "$RUN_DIR"
cp "$CONFIG_PATH" "$RUN_DIR/config.snapshot.yaml"
sha256sum "$CONFIG_PATH" > "$RUN_DIR/config.sha256"
git -C "$ROOT_DIR" rev-parse HEAD > "$RUN_DIR/git_commit.txt"
git -C "$ROOT_DIR" status --porcelain --untracked-files=normal > "$RUN_DIR/git_status.txt"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-training"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

printf 'timestamp,index,name,memory_used_mib,gpu_util_percent,temperature_c,power_w\n' > "$GPU_CSV"
printf 'timestamp,compute_process_count,pid_memory_pairs\n' > "$GPU_PROCESS_CSV"
GPU_UUID="$(nvidia-smi -i "$GPU_ID" --query-gpu=uuid --format=csv,noheader | tr -d ' ')"
monitor_gpu() {
  local timestamp process_pairs
  local -a process_rows
  while kill -0 "$TRAIN_PID" 2>/dev/null; do
    nvidia-smi -i "$GPU_ID" \
      --query-gpu=timestamp,index,name,memory.used,utilization.gpu,temperature.gpu,power.draw \
      --format=csv,noheader,nounits >> "$GPU_CSV" || true
    timestamp="$(date --iso-8601=seconds)"
    mapfile -t process_rows < <(
      nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory \
        --format=csv,noheader,nounits 2>/dev/null \
        | awk -F', *' -v uuid="$GPU_UUID" '$1 == uuid {print $2 ":" $3}' \
        | sort -n
    )
    process_pairs="$(IFS='|'; echo "${process_rows[*]}")"
    printf '%s,%s,"%s"\n' "$timestamp" "${#process_rows[@]}" "$process_pairs" \
      >> "$GPU_PROCESS_CSV"
    sleep 1
  done
}

START_EPOCH="$(date +%s)"
set +e
(
  cd "$ROOT_DIR"
  CUDA_VISIBLE_DEVICES="$GPU_ID" "$CLI" train "$CONFIG_PATH"
) > >(tee "$TRAIN_LOG") 2>&1 &
TRAIN_PID=$!
monitor_gpu &
MONITOR_PID=$!
wait "$TRAIN_PID"
TRAIN_STATUS=$?
wait "$MONITOR_PID" 2>/dev/null || true
set -e
END_EPOCH="$(date +%s)"

OUTPUT_DIR="$(awk -F': *' '$1 == "output_dir" {print $2; exit}' "$CONFIG_PATH")"
python3 - "$GPU_CSV" "$GPU_PROCESS_CSV" "$RUN_DIR/run_summary.json" "$OUTPUT_DIR" "$START_EPOCH" "$END_EPOCH" "$TRAIN_STATUS" "$GPU_ID" <<'PY'
import csv
import json
import sys
from pathlib import Path

gpu_csv = Path(sys.argv[1])
gpu_process_csv = Path(sys.argv[2])
summary_path = Path(sys.argv[3])
output_dir = Path(sys.argv[4])
start_epoch, end_epoch, status, gpu_id = map(int, sys.argv[5:])
with gpu_csv.open(encoding="utf-8") as handle:
    samples = list(csv.DictReader(handle))
with gpu_process_csv.open(encoding="utf-8") as handle:
    process_samples = list(csv.DictReader(handle))

def values(field: str) -> list[float]:
    result = []
    for row in samples:
        try:
            result.append(float(row[field]))
        except (KeyError, TypeError, ValueError):
            pass
    return result

def load_json(name: str) -> dict:
    path = output_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

memory = values("memory_used_mib")
utilization = values("gpu_util_percent")
temperature = values("temperature_c")
power = values("power_w")
process_counts = [int(row["compute_process_count"]) for row in process_samples]
observed_processes = sorted(
    {
        pair.split(":", 1)[0]
        for row in process_samples
        for pair in str(row.get("pid_memory_pairs") or "").split("|")
        if pair
    },
    key=int,
)
max_processes = max(process_counts, default=0)
summary = {
    "schema_version": "studyhub.agent.sft.run_telemetry.v2",
    "exit_code": status,
    "training_succeeded": status == 0,
    "gpu_id": gpu_id,
    "duration_seconds": end_epoch - start_epoch,
    "sample_count": len(samples),
    "gpu": {
        "peak_memory_mib": max(memory, default=0),
        "mean_memory_mib": round(sum(memory) / len(memory), 3) if memory else 0,
        "peak_utilization_percent": max(utilization, default=0),
        "mean_utilization_percent": round(sum(utilization) / len(utilization), 3) if utilization else 0,
        "peak_temperature_c": max(temperature, default=0),
        "mean_power_w": round(sum(power) / len(power), 3) if power else 0,
        "max_concurrent_compute_processes": max_processes,
        "observed_compute_pids": observed_processes,
        "exclusive_gpu_observed": max_processes <= 1,
    },
    "output_dir": str(output_dir),
    "train_results": load_json("train_results.json"),
    "eval_results": load_json("eval_results.json"),
}
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

exit "$TRAIN_STATUS"
