# StudyHub RAG Experiments

This directory turns the retrieval claims documented in `Interview_QA-CV` into
reproducible offline experiments. It is not imported by the production backend.

## Isolation contract

- Inputs are local files below `backup/oss_materials`; database URLs and
  `.db`/`.sqlite*` files are rejected.
- Only free materials (`free=true`, `price=0`) enter the corpus.
- The package does not import `backend`, `app`, SQLAlchemy, SQLite, MySQL, or
  PostgreSQL drivers. `verify-isolation` enforces this with an AST scan.
- Generated OCR, chunks, vectors, and indices stay under `artifacts/` and are
  ignored by Git. Compact metrics, plots, failure cases, and the report stay under
  `reports/`.
- The backup directory is read only from this code path. No command writes to it.

## Implemented comparisons

- TF-IDF character 2-4 grams
- BM25 with mixed Chinese/English tokens
- BGE-M3 dense retrieval with exact search, FAISS HNSW, and FAISS IVFFlat
- Qwen3-Embedding-0.6B exact dense retrieval
- 0.6/0.4 normalized weighted hybrid retrieval
- Reciprocal Rank Fusion (RRF)
- BGE-reranker-v2-m3 cross-encoder reranking
- Material-level Recall@10, Hit@10, MRR, nDCG@10, MAP@10, latency,
  no-answer false-positive rate, and permission leakage

## Reproduce

```bash
cd /data/chengjin/studyhub/ai_platform/rag_experiments
uv sync --extra dense --extra ocr --extra dev
uv run studyhub-rag verify-isolation
uv run studyhub-rag ocr-previews
uv run studyhub-rag build-corpus
uv run studyhub-rag run --mode all
uv run studyhub-rag verify-results
```

For a CPU-only code and benchmark smoke test:

```bash
uv sync --extra dev
uv run pytest
uv run studyhub-rag build-corpus
uv run studyhub-rag run --mode sparse
```

The first full run creates embedding caches. Later runs reuse a cache only when
the ordered chunk IDs and corpus fingerprint match.
