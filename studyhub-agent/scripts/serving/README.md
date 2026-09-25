# Serving Qwen3.5-4B with SGLang (this host)

Exact recipe used for the Task 14 acceptance run (server acceptance: renderer parity against
`transformers`, plus 3 smoke episodes through `scripts/smoke_episodes.py`). Model-dependent, GPU host
only — not part of the local test suite.

Sample output from this exact run: [`docs/evidence/foundation-smoke-2026-09-25.jsonl`](../../docs/evidence/foundation-smoke-2026-09-25.jsonl).

## Shared-GPU etiquette (read first)

This host's two GPUs are shared with other people's jobs. Before doing anything:

1. `nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv` — pick the GPU
   with the most free memory. Re-check every time; usage on this host changes minute to minute.
2. Never stop, signal, or otherwise disturb a process you did not start.
3. Never request more memory than is currently free. `--mem-fraction-static` is close to a fraction of
   the GPU's *total* capacity only when the GPU is otherwise idle. On a shared GPU, SGLang's memory-pool
   formula (`model_runner_kv_cache_mixin.py`) actually computes
   `rest_memory = post_load_avail − pre_load_avail · (1 − mem_fraction_static)`, where both `avail`
   terms are the real free bytes measured at that moment — so raising the fraction only shrinks
   SGLang's own safety headroom carved out of memory that is already free; it never reserves memory
   beyond what `nvidia-smi` already shows as unused. Still, size it conservatively and verify with
   `nvidia-smi` before and after every launch attempt.
4. Stop only the PID (process group) you started, and confirm with `nvidia-smi` that the memory you used
   has been released before considering the job done.

## Environment

- **SGLang install (reused read-only, not modified):** `/data/chengjin/studyhub/studyhub-agent/.venv-train`
  — Python 3.12.13, `sglang==0.5.10.post1`, `torch==2.9.1+cu129`. This is the same SGLang version pinned
  by the legacy OPD evidence files (`sglang: "0.5.10.post1"` in the pre-v3 benchmark evidence), found via
  `find /data/chengjin /home/chengjin -path "*site-packages/sglang" -maxdepth 9 -type d`.
- **Model:** `/data/chengjin/studyhub/models/P1/Qwen3.5-4B` (bf16, hybrid Gated-DeltaNet/Mamba +
  attention architecture — not a plain dense transformer; its `config.json.text_config.num_experts`
  is already `None` on this checkpoint, so the legacy `num_experts=1` SGLang overlay is **not** needed
  here).
- **No CUDA toolkit on this host:** only pip-installed CUDA *runtime* libraries are present (no `nvcc`).
  SGLang's bundled `deep_gemm` package unconditionally asserts `CUDA_HOME` at import time, which crashes
  `sglang.launch_server` immediately. `sitecustomize.py` in this directory is a vendored, minimal extract
  of the legacy no-nvcc compatibility shim (see its header for exact provenance) that stubs this out via
  two env-gated blocks. Put this directory on `PYTHONPATH` so Python auto-imports it at interpreter start.

## Launch command

```bash
V=/data/chengjin/studyhub/studyhub-agent/.venv-train
REPO=/data/chengjin/studyhub-agent-v3/studyhub-agent   # or wherever this repo is checked out
CUDA_RUNTIME_LIB="$V/lib/python3.12/site-packages/nvidia/cuda_runtime/lib"

mkdir -p /tmp/studyhub-agent-smoke

CUDA_VISIBLE_DEVICES=<free gpu, e.g. 1> \
STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC=1 \
STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC=1 \
PYTHONPATH="${REPO}/scripts/serving" \
LD_LIBRARY_PATH="${CUDA_RUNTIME_LIB}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" \
setsid nohup "$V/bin/python" -m sglang.launch_server \
  --model-path /data/chengjin/studyhub/models/P1/Qwen3.5-4B \
  --host 127.0.0.1 --port 30411 \
  --mem-fraction-static 0.40 \
  --context-length 8192 --max-total-tokens 8192 \
  --max-running-requests 1 --max-mamba-cache-size 8 \
  --disable-cuda-graph \
  > /tmp/studyhub-agent-smoke/sglang.log 2>&1 &
echo $! > /tmp/studyhub-agent-smoke/sglang.pid
```

Notes on the flags (all beyond `--mem-fraction-static`/`--context-length`/`--max-total-tokens` were
needed only because Qwen3.5-4B is hybrid, not a plain dense model):

- `--mem-fraction-static 0.40`: the smallest value that produced a non-negative KV/mamba token-pool
  budget on this shared GPU (~28 GB free at process start; `0.28`, a reasonable-looking starting point
  for "4B bf16 weights ≈ 9 GB + KV cache" on an *idle* GPU, produced a negative profiled-token count here
  because of the formula above). A larger value (`0.75`) was blocked by an unrelated safety control before
  it ran; `0.40` was verified against live `nvidia-smi` output to never exceed actually-free memory.
- `--max-mamba-cache-size 8`: the hybrid model's Mamba/GDN layers need a fixed per-request state cache
  independent of context length. Left at its default (auto-sized from `mamba_full_memory_ratio`), it
  consumed the entire static memory budget and left nothing for the actual KV token pool. `8` is enough
  headroom for `--max-running-requests` (SGLang internally requires
  `max_mamba_cache_size // mamba_ratio >= max_running_requests`, and the ratio is 3-4 with radix cache
  enabled).
- `--disable-cuda-graph`: works around an unrelated SGLang bug where `--max-running-requests 1` produces
  an empty CUDA-graph capture batch-size list (`capture_bs=[0]` assertion) during graph capture. Harmless
  for a 3-episode smoke/acceptance run; would matter for throughput serving.
- `setsid` makes the server's PID equal to its process group ID, so the whole process tree (scheduler,
  detokenizer, tokenizer workers) can be torn down with one signal (see "Stop the server" below).

`--context-length`/`--max-total-tokens 8192` comfortably covers the smoke fixture's short conversations
(system prompt + a handful of tool specs + 1-4 tool round-trips); it is **not** meant to satisfy the
episode contract's own `Budget.max_context_tokens` (16384 by default) for longer conversations — raise it
if a task needs more room, subject to the same free-memory check.

## Health check

```bash
until [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:30411/health)" = "200" ]; do
  kill -0 "$(cat /tmp/studyhub-agent-smoke/sglang.pid)" || { echo "server process died, see sglang.log"; break; }
  sleep 5
done
```

Weight loading + memory-pool setup took about 30-35s in this run (from a warm OS page cache). Watch
`/tmp/studyhub-agent-smoke/sglang.log` for `RuntimeError: Not enough memory` (raise
`--mem-fraction-static` a little, staying inside currently-free memory) or `AssertionError` from
`deep_gemm`/`capture_bs` (check the `PYTHONPATH`/env vars above are actually set).

## Run the smoke episodes

```bash
cd "$REPO"
/data/chengjin/.venvs/studyhub-agent/bin/python scripts/smoke_episodes.py \
  --model-dir /data/chengjin/studyhub/models/P1/Qwen3.5-4B \
  --sglang-url http://127.0.0.1:30411 \
  --snapshot tests/fixtures/replay_snapshot.json \
  --tasks tests/fixtures/smoke_tasks.jsonl \
  --out /tmp/studyhub-agent-smoke/episodes.jsonl
```

## Stop the server

```bash
PID=$(cat /tmp/studyhub-agent-smoke/sglang.pid)
kill -TERM -- -"$PID"        # negative PID = whole process group (setsid made PID == PGID)
sleep 5
kill -0 "$PID" 2>/dev/null && kill -KILL -- -"$PID"   # only if TERM didn't finish it in time
pgrep -af sglang                                       # should print nothing but this pgrep itself
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv   # confirm memory returned
```
