# Toy retrieval versus StudyHub Hybrid RAG

- **Defect:** v2 RL uses a small frozen lexical fixture rather than the intended StudyHub Hybrid RAG stack.
- **Discovery:** 2026-08-27 environment audit.
- **Evidence:** `training/rl/frozen_environment.py` and v2 generated corpora differ from the BM25+dense+fusion+reranking research path.
- **Scope:** query quality, source selection, stopping behavior and transfer to StudyHub materials.
- **Why systemic:** the policy can exploit fixture IDs and lexical regularities that do not exist in the target retriever.
- **Competing explanations:** a toy environment is sufficient for wiring and short mechanism tests.
- **Minimal falsification:** replay the same 200 tasks against toy lexical and frozen Hybrid RAG snapshots and compare trajectory/ranking changes.
- **Root cause:** the pilot optimized reproducibility before retrieval realism.
- **Fix:** freeze a versioned Hybrid RAG snapshot with replayable search/read observations for v3 data, RL and Dev.
- **Regression:** record index, corpus, embedding, reranker and retrieval-config hashes in every run.
- **Before/after:** lexical fixture -> versioned product-like retrieval environment.
- **Residual risk:** an offline snapshot cannot represent all production drift.
- **Interview 60s:** explain why retriever quality changes the policy learning problem.
- **Deep dive:** separate retriever offline metrics from end-to-end Agent success.
