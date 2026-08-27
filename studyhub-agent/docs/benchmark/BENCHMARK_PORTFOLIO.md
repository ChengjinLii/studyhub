# StudyHub Agent Evaluation Portfolio

The portfolio separates two questions:

1. **Internal product validity:** StudyHub AgentBench v2 (98 tasks) measures StudyHub RAG, frozen Web, memory, state, ACL, failure recovery, and tool relevance.
2. **External validity:** BFCL, tau2-bench, DeepResearch Bench II, and BrowseComp-Plus retain their official environments and metrics.

Metrics are never averaged into a single AgentScore. Future reports must show StudyHub strict success and cluster-aware intervals alongside each external benchmark's raw metric name and value.

AgentBench v1 remains immutable historical runtime evidence. AgentBench v2 is the baseline ruler for new Base/SFT/GRPO comparisons after this frozen revision.

## Reproduction

The exact StudyHub preview OCR and material metadata used to construct v2 are authorized local snapshots and are intentionally not redistributed. With those inputs present at the paths documented by `scripts/benchmark/v2/build.py`, the complete fail-fast gate is:

```bash
bash scripts/benchmark/run_full_quality_gate.sh
```

The command fetches or validates the licensed Web/external snapshots, rebuilds v2, runs structural and semantic audits, Oracle/negative/metamorphic/challenge tests, validates v1 integrity, scans commit candidates for secrets, freezes the manifest, and verifies all recorded hashes. Without the authorized OCR snapshot, the command exits with an explicit prerequisite error rather than substituting synthetic content.

## Base Calibration

The first post-freeze Qwen3.5-9B Base Gate is recorded in [9B_BASE_V2_CALIBRATION.md](9B_BASE_V2_CALIBRATION.md). It covers one public task per capability and validates the complete runtime, but it is not a full Development or Sealed benchmark result and does not assign empirical difficulty labels.
