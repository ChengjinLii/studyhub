# Standalone Validation

Date: 2026-10-05. This validates development functionality, not production readiness.
No website, production service, database, object store, payment API, or real submission
was accessed. The temporary HTTP server used a random loopback port and was stopped.

## Models and Runtime

- Text: `Qwen/Qwen3Guard-Gen-0.6B`, revision `fada3b2f655b89601929198343c94cd2f64d93cc`.
- Images: `OmniJev/OneJev-4B`, revision `c88e18653ceb7a8770716287f55fdefc79d6b588`.
- OneJev weights were verified against the official SHA-256:
  `c725978346bb87ff598b04b6ffe7ea89461368e9b20a0081a3c6a85d377c8f91`.
- Python 3.12; PyTorch 2.9.1+cu129; torchvision 0.24.1+cu129;
  Transformers 5.18.0; Accelerate 1.15.0; safetensors 0.8.0.
- Text inference used CPU with four threads. Image inference used an NVIDIA H100 PCIe,
  automatically selected as `cuda:1` based on available memory.
- FastAPI 0.142.2; Uvicorn 0.54.0; Pillow 12.3.0.
- Inference ran with `HF_HUB_OFFLINE=1` after downloads. Weights and generated reports
  are outside Git; the repository contains code, licenses, policies and synthetic examples only.

## Checks

- Source environment: **135 passed, 3 skipped**. The skipped upstream SDK checks need a live
  OneJev endpoint; they are not represented as passing live-service tests.
- Fresh non-editable wheel environment, Python 3.13.5 without model dependencies:
  **134 passed, 4 skipped**. The additional skip needs optional Transformers/Torch.
- Ruff, staged whitespace checks, sensitive-file checks and standalone wheel installation passed.
- Five real-model cases passed: Chinese text notes, text privacy risk, text plus image,
  image-only input, and two images. All three image cases returned all eleven finite rule scores.
- Two real loopback HTTP cases passed, covering both default routes. `/ready` reported
  ready after both models had loaded. No service was left running.
- Default automatic approval and rejection stayed disabled. All smoke results required review.

The smoke command is:

```bash
HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false \
  .venv/bin/python -m review_jev.smoke --http --output artifacts/smoke.json
```

Remove `HF_HUB_OFFLINE=1` if the default model snapshots have not yet been downloaded.

## Observed Limits

- The text guard identified the synthetic privacy example as `Unsafe / PII`, and marked
  normal notes `Safe`. A separate example instructing an automated reviewer to ignore policy
  was missed. This is a recorded limitation, not a passing safety-quality benchmark.
- Text results always remain `partial`: native labels do not cover all custom StudyHub rules
  or verify rights. Unsupported checks have no probability and cannot permit automatic approval.
- The visual model is a general decision model, not a StudyHub-specific moderation fine-tune.
  Medical teaching images, publisher scans and Chinese screenshot accuracy remain unvalidated.
- Reference PyTorch kernels were used without `causal_conv1d` or `flash-linear-attention`.
  Observed warm image requests took roughly 3-7 seconds; first load/warmup took roughly
  41 seconds. These synthetic timings are not latency guarantees or upstream benchmark replicas.
- No copyright ownership or sharing authorization was verified. No model was trained or
  calibrated for StudyHub, and no held-out moderation quality claim is made.
