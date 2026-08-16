#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_SFT_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
TASK="${1:?usage: run-sft-controlled-v2-matrix.sh TASK GPU}"
GPU="${2:?missing GPU index}"

if [[ "$TASK" != "router" && "$TASK" != "tutor" ]]; then
  echo "TASK must be router or tutor" >&2
  exit 2
fi
if [[ "$GPU" != "0" && "$GPU" != "1" ]]; then
  echo "GPU must be 0 or 1" >&2
  exit 2
fi

cd "$ROOT_DIR"
export PYTHONPATH="backend:.${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

QUEUE_DIR="$ROOT_DIR/training_artifacts/studyhub_agent_sft/controlled_v2/queue"
TRAINING_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_sft/controlled_v2"
EVALUATION_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/sft_controlled_v2"
STATUS_FILE="$QUEUE_DIR/${TASK}_matrix_gpu${GPU}.status"
mkdir -p "$QUEUE_DIR"

exec 9>"$QUEUE_DIR/gpu${GPU}.lock"
if ! flock -n 9; then
  echo "another StudyHub controlled-v2 matrix owns GPU $GPU" >&2
  exit 3
fi

MATRIX_COMPLETED=false
SIGNAL_STATUS=""
CURRENT_PHASE="startup"

write_status() {
  local value=$1
  local temporary="${STATUS_FILE}.tmp.$$"
  printf '%s\n' "$value" > "$temporary"
  mv "$temporary" "$STATUS_FILE"
}

handle_signal() {
  local signal=$1
  local exit_code=$2
  SIGNAL_STATUS="terminated signal=${signal} task=${TASK} gpu=${GPU} phase=${CURRENT_PHASE} pid=$$"
  write_status "$SIGNAL_STATUS"
  exit "$exit_code"
}

finish() {
  local rc=$?
  if [[ "$MATRIX_COMPLETED" == "true" ]]; then
    write_status "completed task=${TASK} gpu=${GPU} pid=$$"
  elif [[ -n "$SIGNAL_STATUS" ]]; then
    write_status "$SIGNAL_STATUS"
  else
    write_status "failed rc=${rc} task=${TASK} gpu=${GPU} phase=${CURRENT_PHASE} pid=$$"
  fi
}
trap 'handle_signal HUP 129' HUP
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM
trap finish EXIT
write_status "running task=${TASK} gpu=${GPU} phase=${CURRENT_PHASE} pid=$$"

log_step() {
  printf '\n[%s] %s\n' "$(date --iso-8601=seconds)" "$*" >&2
}

wait_for_idle_gpu() {
  local idle_samples=0
  local used_mib
  write_status "waiting_gpu task=${TASK} gpu=${GPU} phase=${CURRENT_PHASE} pid=$$"
  while (( idle_samples < 3 )); do
    used_mib="$(
      nvidia-smi -i "$GPU" --query-gpu=memory.used \
        --format=csv,noheader,nounits | tr -d ' '
    )"
    if (( used_mib <= 1024 )); then
      ((idle_samples += 1))
    else
      idle_samples=0
    fi
    printf '[matrix-wait] task=%s gpu=%s used=%sMiB idle=%s/3\n' \
      "$TASK" "$GPU" "$used_mib" "$idle_samples" >&2
    if (( idle_samples < 3 )); then
      sleep 10
    fi
  done
}

run_inference_with_retries() {
  local label=$1
  shift
  local attempt rc
  for attempt in 1 2 3; do
    CURRENT_PHASE="inference:${label}:attempt${attempt}"
    wait_for_idle_gpu
    write_status "running_inference task=${TASK} gpu=${GPU} phase=${CURRENT_PHASE} pid=$$"
    log_step "run inference=$label attempt=$attempt gpu=$GPU"
    if "$@"; then
      return 0
    else
      rc=$?
    fi
    log_step "inference failed with rc=$rc; completed condition artifacts will be reused"
  done
  echo "inference retries exhausted: $label" >&2
  return 1
}

telemetry_field() {
  local experiment_id=$1
  local seed=$2
  local field=$3
  local summary="$TRAINING_ROOT/run_telemetry/${experiment_id}-seed${seed}/run_summary.json"
  if [[ ! -f "$summary" ]]; then
    return 1
  fi
  "$PYTHON" -c \
    'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2], ""))' \
    "$summary" "$field"
}

archive_interrupted_training() {
  local experiment_id=$1
  local seed=$2
  local exit_code=$3
  local stamp destination task_dir
  stamp="$(date +%Y%m%d_%H%M%S)_exit${exit_code}"
  destination="$TRAINING_ROOT/interrupted_attempts/$experiment_id/seed_${seed}/$stamp"
  mkdir -p "$destination"
  for task_dir in router tutor; do
    if [[ -d "$TRAINING_ROOT/$task_dir/$experiment_id/$seed" ]]; then
      mv "$TRAINING_ROOT/$task_dir/$experiment_id/$seed" "$destination/model_output"
      break
    fi
  done
  if [[ -d "$TRAINING_ROOT/run_telemetry/${experiment_id}-seed${seed}" ]]; then
    mv "$TRAINING_ROOT/run_telemetry/${experiment_id}-seed${seed}" \
      "$destination/telemetry"
  fi
  printf '{\n  "experiment_id": "%s",\n  "seed": %s,\n  "exit_code": %s,\n  "reason": "retriable external interruption",\n  "reusable_checkpoint": false\n}\n' \
    "$experiment_id" "$seed" "$exit_code" > "$destination/interruption.json"
  log_step "archived interrupted attempt at $destination"
}

run_arm() {
  local experiment_id=$1
  local seed=$2
  local attempt rc telemetry_exit succeeded train_log oom_failure
  for attempt in 1 2 3; do
    CURRENT_PHASE="arm:${experiment_id}:seed${seed}:attempt${attempt}"
    wait_for_idle_gpu
    write_status "running_arm task=${TASK} gpu=${GPU} phase=${CURRENT_PHASE} pid=$$"
    log_step "run arm=$experiment_id seed=$seed attempt=$attempt gpu=$GPU"
    if "$ROOT_DIR/scripts/research/run-sft-controlled-v2-arm.sh" \
      "$experiment_id" "$seed" "$GPU"; then
      return 0
    else
      rc=$?
    fi
    telemetry_exit="$(telemetry_field "$experiment_id" "$seed" exit_code || true)"
    succeeded="$(telemetry_field "$experiment_id" "$seed" training_succeeded || true)"
    train_log="$TRAINING_ROOT/run_telemetry/${experiment_id}-seed${seed}/train.log"
    oom_failure=false
    if [[ -f "$train_log" ]] && rg -qi \
      'CUDA out of memory|out of memory|CUBLAS_STATUS_ALLOC_FAILED' "$train_log"; then
      oom_failure=true
    fi
    if [[ "$succeeded" == "False" && ( "$telemetry_exit" == "137" || "$telemetry_exit" == "143" || "$oom_failure" == "true" ) ]]; then
      archive_interrupted_training "$experiment_id" "$seed" "$telemetry_exit"
    elif [[ "$succeeded" == "True" ]]; then
      log_step "training is complete; retrying interrupted evaluation"
    elif [[ "$rc" != "137" && "$rc" != "143" ]]; then
      echo "non-retriable arm failure: $experiment_id seed=$seed rc=$rc" >&2
      return "$rc"
    fi
    if (( attempt == 3 )); then
      echo "retries exhausted: $experiment_id seed=$seed" >&2
      return 1
    fi
  done
}

json_specs() {
  local path=$1
  local key=$2
  "$PYTHON" -c '
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
if sys.argv[2] != "list":
    value = value[sys.argv[2]]
for item in value:
    print("{}\t{}".format(item["experiment_id"], item["seed"]))
' "$path" "$key"
}

adapter_path_for() {
  local experiment_id=$1
  local seed=$2
  "$PYTHON" -c '
import json, sys
registry = json.load(open(sys.argv[1], encoding="utf-8"))
matches = [
    item
    for section in ("initial_experiments", "reference_experiments", "dynamic_experiments")
    for item in registry.get(section, [])
    if item["experiment_id"] == sys.argv[2] and int(item["seed"]) == int(sys.argv[3])
]
if len(matches) != 1:
    raise SystemExit("expected exactly one registered experiment")
item = matches[0]
print(
    item.get("reference_adapter_path")
    or "{}/{}/{}/{}".format(
        sys.argv[4], item["task"], item["experiment_id"], item["seed"]
    )
)
' \
    "$EVALUATION_ROOT/contract/experiment_registry.json" \
    "$experiment_id" "$seed" "$TRAINING_ROOT"
}

first_experiment_id() {
  local path=$1
  local key=$2
  "$PYTHON" -c '
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
if sys.argv[2] != "list":
    value = value[sys.argv[2]]
if not value:
    raise SystemExit("experiment list is empty")
print(value[0]["experiment_id"])
' "$path" "$key"
}

run_specs_file() {
  local path=$1
  local key=$2
  local experiment_id seed spec_lines
  spec_lines="$(json_specs "$path" "$key")"
  if [[ -z "$spec_lines" ]]; then
    echo "experiment list is empty: $path key=$key" >&2
    return 1
  fi
  while IFS=$'\t' read -r experiment_id seed; do
    run_arm "$experiment_id" "$seed"
  done <<< "$spec_lines"
}

select_stage() {
  local stage=$1
  local output="$QUEUE_DIR/${stage}.json"
  if [[ ! -f "$output" ]]; then
    log_step "select stage=$stage from frozen development Gates"
    "$PYTHON" -m ml.agentic_platform.sft.controlled_v2.select "$stage" > "$output.tmp"
    mv "$output.tmp" "$output"
  fi
  printf '%s\n' "$output"
}

run_baselines() {
  local output="$QUEUE_DIR/${TASK}_baselines.json"
  local canonical="$EVALUATION_ROOT/baselines/$TASK/baseline_index.json"
  local stdout_log="$QUEUE_DIR/${TASK}_baselines.stdout.log"

  if [[ -s "$canonical" ]] && \
    "$PYTHON" -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' \
      "$canonical" 2>/dev/null; then
    log_step "reuse completed canonical $TASK baselines"
  else
    log_step "run Base / Prompt / Few-shot / completed-SFT references"
    run_inference_with_retries "${TASK}-baselines" \
      "$PYTHON" -m ml.agentic_platform.sft.controlled_v2.baselines \
      "$TASK" --gpu "$GPU" > "$stdout_log.tmp"
    mv "$stdout_log.tmp" "$stdout_log"
  fi

  if [[ ! -s "$canonical" ]]; then
    echo "canonical baseline index was not produced: $canonical" >&2
    return 1
  fi
  log_step "write canonical $TASK baseline queue artifact"
  "$PYTHON" -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
json.dump(value, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
sys.stdout.write("\n")
' "$canonical" > "$output.tmp"
  mv "$output.tmp" "$output"
}

register_extensions() {
  local winner_id=$1
  local winner_seed=$2
  local output="$QUEUE_DIR/${TASK}_extensions.json"
  if [[ ! -f "$output" ]]; then
    log_step "register Roadmap attribution arms from $winner_id"
    "$PYTHON" -m ml.agentic_platform.sft.controlled_v2.extensions "$TASK" \
      --experiment-id "$winner_id" --seed "$winner_seed" > "$output.tmp"
    mv "$output.tmp" "$output"
  fi
  printf '%s\n' "$output"
}

assemble_ablations() {
  local winner_id=$1
  local winner_seed=$2
  log_step "assemble paired statistics, family deltas, and resource evidence"
  "$PYTHON" -m ml.agentic_platform.sft.controlled_v2.ablation "$TASK" \
    --experiment-id "$winner_id" --seed "$winner_seed" \
    > "$QUEUE_DIR/${TASK}_ablation_index.json.tmp"
  mv "$QUEUE_DIR/${TASK}_ablation_index.json.tmp" \
    "$QUEUE_DIR/${TASK}_ablation_index.json"
}

finalize_development() {
  local winner_id=$1
  log_step "assemble multi-seed, paired-statistics, regression, and resource evidence"
  "$PYTHON" -m ml.agentic_platform.sft.controlled_v2.finalize "$TASK" \
    --experiment-id "$winner_id"
  log_step "sealed evaluation remains unopened for the final supervised single-use step"
}

if [[ "$TASK" == "router" ]]; then
  # Establish the common comparison point before any configuration selection.
  run_baselines
  # Complete the last pre-registered learning-rate arm before any stage selection.
  run_arm r-opt-r16-all-lr8e5-e1-cosine 7703
  lr_json="$(select_stage router-lr)"
  run_specs_file "$lr_json" list
  epoch_json="$(select_stage router-epoch)"
  run_specs_file "$epoch_json" list
  scheduler_json="$(select_stage router-scheduler)"
  run_specs_file "$scheduler_json" list
  target_json="$(select_stage router-lora-rank)"
  run_specs_file "$target_json" list
  seed_json="$(select_stage router-lora-target)"
  run_specs_file "$seed_json" list
  winner_id="$(first_experiment_id "$seed_json" list)"
  extension_json="$(register_extensions "$winner_id" 7703)"
  run_specs_file "$extension_json" registered
  assemble_ablations "$winner_id" 7703
  finalize_development "$winner_id"
else
  run_baselines
  lr_json="$(select_stage tutor-lr)"
  run_specs_file "$lr_json" list
  seed_json="$(select_stage tutor-lora)"
  run_specs_file "$seed_json" list
  winner_id="$(first_experiment_id "$seed_json" list)"
  extension_json="$(register_extensions "$winner_id" 6209)"
  run_specs_file "$extension_json" registered
  assemble_ablations "$winner_id" 6209
  log_step "run Tutor context length, evidence density, and output-budget study"
  winner_adapter="$(adapter_path_for "$winner_id" 6209)"
  run_inference_with_retries "tutor-context-study" \
    "$PYTHON" -m ml.agentic_platform.sft.controlled_v2.context_study run \
    --adapter "$winner_adapter" \
    --output-root "$EVALUATION_ROOT/t-context/results"
  finalize_development "$winner_id"
fi

"$PYTHON" -m ml.agentic_platform.sft.controlled_v2.result_index
log_step "$TASK controlled-v2 matrix complete"
MATRIX_COMPLETED=true
