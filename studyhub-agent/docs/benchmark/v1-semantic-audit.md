# StudyHub AgentBench v1 Semantic Audit

Generated: `2026-08-27T12:50:00+00:00`
Frozen manifest: `89b6fe098c26ba8664d27704b28b4571d1c70de636abcfe06ecfb929594c7cb1`

This audit does not modify Benchmark v1. It quantifies why the frozen benchmark remains useful for runtime lineage but is not reused as the formal v2 capability ruler.

## Development split

- Tasks: **1005**
- Source groups: **64**; max reuse **31**; p90 **26.0**
- Normalized template clusters: **630**; largest share **3.58%**
- Semantic shape clusters: **630**; largest share **3.58%**
- Material corpus groups: **45**

## Blocking interpretation issues

The prior `teacher review` was a deterministic contract checker, not an independent semantic review. Direct-answer prompts disclosed the desired policy, query-rewrite recovery did not require a changed query, ACL recovery required a denial, difficulty came from ordinal rotation, and the internal replay backend was BM25 rather than Hybrid RAG.

## Disposition

Benchmark v1 is immutable historical evidence. Benchmark v2 uses source-group/template-separated splits, `UNSCORED` initial difficulty, explicit source origin, cluster-aware statistics, semantic review status, and separate deterministic versus semantic evaluator layers.
