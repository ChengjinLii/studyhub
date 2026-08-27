# StudyHub AgentBench v2 Data Card

## Scope

AgentBench v2 is an internal product-validity benchmark for StudyHub's read-only learning agent. It contains **98 tasks**, **30 capability-oriented task families**, and **78 non-overlapping source groups**. It does not replace BFCL, tau2-bench, DeepResearch Bench II, or BrowseComp-Plus.

## Splits

| Split | Tasks |
| --- | ---: |
| `regression` | 12 |
| `development` | 51 |
| `sealed_a` | 13 |
| `sealed_b` | 12 |
| `calibration_challenge` | 10 |

`regression`, `development`, and `calibration_challenge` tasks are tracked. Sealed-A and Sealed-B tasks, environments, corpora, and graders remain ignored local artifacts. Source-group and declared semantic-template overlap across splits are both zero.

## Sources

The hidden source inventory contains **84 records**: {'preview_ocr': 34, 'official_pinned_repository_documentation': 10, 'official_documentation': 40}. StudyHub records come only from free public preview OCR and contain no paid/private/cross-user material. The Web lane uses 50 frozen official documentation pages whose URLs, licenses, content hashes, and snapshot lock are recorded.

| Environment origin | Tasks | Share |
| --- | ---: | ---: |
| `authentic_studyhub_preview` | 54 | 55.10% |
| `synthetic_adversarial` | 16 | 16.33% |
| `synthetic_state` | 5 | 5.10% |
| `authentic_web_snapshot` | 5 | 5.10% |
| `synthetic_memory` | 18 | 18.37% |

Authentic-source tasks account for **59/98 (60.20%)**; synthetic adversarial, memory, and state fixtures account for **39/98 (39.80%)**.

## Languages

- Chinese: **71 (72.45%)**
- English: **27 (27.55%)**

English task instructions use English split prefixes. Source titles and quoted technical terms can remain in their original language.

## Construction

Authentic RAG tasks use preview body text rather than metadata-only lookup. Companion-term graders accept every supported non-anchor technical term in the cited passage instead of one arbitrary generator choice. Query reformulation requires an observed alias bridge, a changed query, and target-recall gain. Web pages are fetched only from an HTTPS allowlist and replayed offline. Memory/state fixtures carry explicit invariants and final-state assertions.

## Review And Limitations

Codex self-reviewed 32 stratified representatives across all 30 capability families, five splits, both languages, and all source origins. Independent human review and external LLM judging were **not run**.

Known limits: preview OCR quality varies; some passage tasks remain extraction-oriented; some cross-passage tasks use the same anchor in two distinct passages; the internal research lane measures controlled multi-source synthesis rather than general open-web Deep Research quality; initial difficulty remains `UNSCORED` until post-freeze calibration.
