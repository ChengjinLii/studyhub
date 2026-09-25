# External Benchmark Portfolio

| Benchmark | Pinned commit | Current status | License |
| --- | --- | --- | --- |
| bfcl | `f7cf7359b7ac615a0b294831c5ba2bc95ee4a000` | SETUP_READY | Apache-2.0 |
| browsecomp_plus | `046949032b0328319cc9a02663a759ec601d9402` | SETUP_READY | MIT |
| deepresearch_bench_ii | `440bdc33728438d317ca7860809942b5a1e40256` | LICENSE_REVIEW_REQUIRED | NOASSERTION |
| tau2 | `fc0055dc4e0a316c3f83133267fbd6faaa770992` | SETUP_READY | MIT |

BFCL keeps the official `bfcl generate`/`bfcl evaluate` pipeline. tau2-bench v1.0.1 keeps official DB/COMMUNICATE outcome semantics; reference actions are not converted into a unique path requirement. BrowseComp-Plus keeps the official fixed-corpus qrels and evaluator path; its large corpus and GPU judge were not run. DeepResearch Bench II has no license file at the pinned official commit, so source export and task evaluation are blocked as `LICENSE_REVIEW_REQUIRED`.

No external model score has been generated. The shared adapter normalizes transport and result packaging only; it does not rewrite official metrics.

```bash
python scripts/benchmark/external/fetch.py --benchmark all
python scripts/benchmark/external/validate_registry.py
python scripts/benchmark/external/smoke.py
```
