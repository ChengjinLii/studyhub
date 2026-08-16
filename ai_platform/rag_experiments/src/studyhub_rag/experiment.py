from __future__ import annotations

import csv
import gc
import importlib.metadata
import json
import platform
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from studyhub_rag.benchmark import load_benchmark
from studyhub_rag.config import ExperimentConfig
from studyhub_rag.corpus import build_chunks, corpus_fingerprint, read_corpus, write_corpus
from studyhub_rag.evaluation import collapse_to_materials, evaluate_method
from studyhub_rag.fusion import reciprocal_rank_fusion, weighted_score_fusion
from studyhub_rag.guards import require_experiment_output
from studyhub_rag.plotting import plot_results
from studyhub_rag.reporting import write_report
from studyhub_rag.reranking import BgeCrossEncoderReranker
from studyhub_rag.retrieval import (
    BM25Retriever,
    ExactDenseIndex,
    FaissDenseIndex,
    SentenceTransformerEncoder,
    TfidfCharRetriever,
    average_search_latency,
)
from studyhub_rag.schemas import Chunk, QueryCase, SearchHit

Rankings = dict[str, list[SearchHit]]


def _search_sparse(retriever: Any, cases: Sequence[QueryCase], *, candidate_k: int) -> tuple[Rankings, float]:
    rankings: Rankings = {}
    latencies: list[float] = []
    for case in cases:
        rankings[case.query_id], latency = retriever.search(case.query, top_k=candidate_k)
        latencies.append(latency)
    return rankings, average_search_latency(latencies)


def _search_dense_index(
    index: Any,
    query_vectors: np.ndarray,
    cases: Sequence[QueryCase],
    *,
    candidate_k: int,
    query_encode_latency_ms: float,
) -> tuple[Rankings, float]:
    rankings: Rankings = {}
    latencies: list[float] = []
    for case, vector in zip(cases, query_vectors, strict=True):
        rankings[case.query_id], latency = index.search_vector(vector, top_k=candidate_k)
        latencies.append(latency)
    return rankings, query_encode_latency_ms + average_search_latency(latencies)


def _fuse_all(
    cases: Sequence[QueryCase],
    left: Mapping[str, Sequence[SearchHit]],
    right: Mapping[str, Sequence[SearchHit]],
    fusion: Callable[[Sequence[Sequence[SearchHit]]], list[SearchHit]],
) -> tuple[Rankings, float]:
    rankings: Rankings = {}
    started = perf_counter()
    for case in cases:
        rankings[case.query_id] = fusion([left[case.query_id], right[case.query_id]])
    return rankings, (perf_counter() - started) * 1000 / max(1, len(cases))


def _embedding_cache_path(config: ExperimentConfig, model_key: str, fingerprint: str) -> Path:
    artifact_root = config.experiment_path(str(config.section("outputs")["artifact_root"]))
    return require_experiment_output(artifact_root / "embeddings" / f"{model_key}-{fingerprint}.npz")


def _load_or_encode_documents(
    config: ExperimentConfig,
    encoder: SentenceTransformerEncoder,
    chunks: Sequence[Chunk],
    *,
    model_key: str,
    fingerprint: str,
) -> np.ndarray:
    path = _embedding_cache_path(config, model_key, fingerprint)
    chunk_ids = np.asarray([chunk.chunk_id for chunk in chunks])
    if path.exists():
        payload = np.load(path)
        cached_ids = payload["chunk_ids"].astype(str)
        if np.array_equal(cached_ids, chunk_ids):
            return np.asarray(payload["embeddings"], dtype=np.float32)
    embeddings = encoder.encode_documents([chunk.retrieval_text for chunk in chunks])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, chunk_ids=chunk_ids, embeddings=embeddings)
    return embeddings


def _release_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _ann_recall(
    exact: Mapping[str, Sequence[SearchHit]],
    approximate: Mapping[str, Sequence[SearchHit]],
    cases: Sequence[QueryCase],
    *,
    top_k: int,
) -> float:
    recalls: list[float] = []
    for case in cases:
        expected = {hit.chunk_id for hit in exact[case.query_id][:top_k]}
        actual = {hit.chunk_id for hit in approximate[case.query_id][:top_k]}
        recalls.append(len(expected & actual) / len(expected) if expected else 1.0)
    return float(np.mean(recalls))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path = require_experiment_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _package_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for package in ("numpy", "scikit-learn", "torch", "transformers", "sentence-transformers", "faiss-cpu"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return result


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[4],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def run_experiment(config: ExperimentConfig, *, mode: str = "all") -> dict[str, Any]:
    if mode not in {"sparse", "all"}:
        raise ValueError("mode must be sparse or all")
    try:
        chunks = read_corpus(config)
    except FileNotFoundError:
        chunks = build_chunks(config)
        write_corpus(config, chunks)
    allowed_material_ids = {chunk.material_id for chunk in chunks}
    cases = load_benchmark(config, valid_material_ids=allowed_material_ids)
    benchmark_config = config.section("benchmark")
    retrieval_config = config.section("retrieval")
    model_config = config.section("models")
    candidate_k = int(benchmark_config.get("candidate_k", 40))
    top_k = int(benchmark_config.get("top_k", 10))
    fingerprint = corpus_fingerprint(chunks)

    methods: dict[str, Rankings] = {}
    latencies: dict[str, float] = {}
    index_stats: dict[str, dict[str, float | int]] = {}

    tfidf = TfidfCharRetriever(chunks)
    methods[tfidf.name], latencies[tfidf.name] = _search_sparse(tfidf, cases, candidate_k=candidate_k)
    bm25 = BM25Retriever(chunks)
    methods[bm25.name], latencies[bm25.name] = _search_sparse(bm25, cases, candidate_k=candidate_k)

    if mode == "all":
        device = str(model_config.get("device", "cuda:0"))
        batch_size = int(model_config.get("embedding_batch_size", 32))
        max_length = int(model_config.get("max_length", 512))

        bge_encoder = SentenceTransformerEncoder(
            config.repo_path(str(model_config["bge_m3"])),
            device=device,
            batch_size=batch_size,
            max_length=max_length,
        )
        bge_embeddings = _load_or_encode_documents(
            config, bge_encoder, chunks, model_key="bge_m3", fingerprint=fingerprint
        )
        bge_queries, query_elapsed = bge_encoder.encode_queries([case.query for case in cases])
        bge_query_latency = query_elapsed / max(1, len(cases))
        del bge_encoder
        _release_gpu()

        exact = ExactDenseIndex(chunks, bge_embeddings)
        index_stats["bge_m3_exact"] = {
            "index_build_ms": exact.build_ms,
            "index_size_bytes": exact.serialized_size_bytes,
        }
        methods["bge_m3_exact"], latencies["bge_m3_exact"] = _search_dense_index(
            exact,
            bge_queries,
            cases,
            candidate_k=candidate_k,
            query_encode_latency_ms=bge_query_latency,
        )
        hnsw = FaissDenseIndex(
            chunks,
            bge_embeddings,
            kind="hnsw",
            hnsw_m=int(retrieval_config.get("hnsw_m", 32)),
            hnsw_ef_search=int(retrieval_config.get("hnsw_ef_search", 64)),
        )
        index_stats["bge_m3_hnsw"] = {
            "index_build_ms": hnsw.build_ms,
            "index_size_bytes": hnsw.serialized_size_bytes,
        }
        methods["bge_m3_hnsw"], latencies["bge_m3_hnsw"] = _search_dense_index(
            hnsw,
            bge_queries,
            cases,
            candidate_k=candidate_k,
            query_encode_latency_ms=bge_query_latency,
        )
        ivf = FaissDenseIndex(
            chunks,
            bge_embeddings,
            kind="ivf",
            ivf_nlist=int(retrieval_config.get("ivf_nlist", 16)),
            ivf_nprobe=int(retrieval_config.get("ivf_nprobe", 4)),
        )
        index_stats["bge_m3_ivf"] = {
            "index_build_ms": ivf.build_ms,
            "index_size_bytes": ivf.serialized_size_bytes,
        }
        methods["bge_m3_ivf"], latencies["bge_m3_ivf"] = _search_dense_index(
            ivf,
            bge_queries,
            cases,
            candidate_k=candidate_k,
            query_encode_latency_ms=bge_query_latency,
        )

        qwen_encoder = SentenceTransformerEncoder(
            config.repo_path(str(model_config["qwen3_embedding_06b"])),
            device=device,
            batch_size=batch_size,
            max_length=max_length,
        )
        qwen_embeddings = _load_or_encode_documents(
            config, qwen_encoder, chunks, model_key="qwen3_embedding_06b", fingerprint=fingerprint
        )
        qwen_queries, query_elapsed = qwen_encoder.encode_queries([case.query for case in cases])
        qwen_query_latency = query_elapsed / max(1, len(cases))
        del qwen_encoder
        _release_gpu()
        qwen_exact = ExactDenseIndex(chunks, qwen_embeddings)
        index_stats["qwen3_embedding_06b_exact"] = {
            "index_build_ms": qwen_exact.build_ms,
            "index_size_bytes": qwen_exact.serialized_size_bytes,
        }
        methods["qwen3_embedding_06b_exact"], latencies["qwen3_embedding_06b_exact"] = _search_dense_index(
            qwen_exact,
            qwen_queries,
            cases,
            candidate_k=candidate_k,
            query_encode_latency_ms=qwen_query_latency,
        )

        lexical_weight = float(retrieval_config.get("lexical_weight", 0.6))
        dense_weight = float(retrieval_config.get("dense_weight", 0.4))
        rrf_k = int(retrieval_config.get("rrf_k", 60))

        methods["bm25_bge_weighted_06_04"], fuse_latency = _fuse_all(
            cases,
            methods[bm25.name],
            methods["bge_m3_exact"],
            lambda rankings: weighted_score_fusion(rankings, weights=[lexical_weight, dense_weight], top_k=candidate_k),
        )
        latencies["bm25_bge_weighted_06_04"] = latencies[bm25.name] + latencies["bge_m3_exact"] + fuse_latency
        methods["tfidf_bge_weighted_06_04"], fuse_latency = _fuse_all(
            cases,
            methods[tfidf.name],
            methods["bge_m3_exact"],
            lambda rankings: weighted_score_fusion(rankings, weights=[lexical_weight, dense_weight], top_k=candidate_k),
        )
        latencies["tfidf_bge_weighted_06_04"] = latencies[tfidf.name] + latencies["bge_m3_exact"] + fuse_latency
        methods["bm25_bge_rrf"], fuse_latency = _fuse_all(
            cases,
            methods[bm25.name],
            methods["bge_m3_exact"],
            lambda rankings: reciprocal_rank_fusion(rankings, rrf_k=rrf_k, top_k=candidate_k),
        )
        latencies["bm25_bge_rrf"] = latencies[bm25.name] + latencies["bge_m3_exact"] + fuse_latency
        methods["tfidf_bge_rrf"], fuse_latency = _fuse_all(
            cases,
            methods[tfidf.name],
            methods["bge_m3_exact"],
            lambda rankings: reciprocal_rank_fusion(rankings, rrf_k=rrf_k, top_k=candidate_k),
        )
        latencies["tfidf_bge_rrf"] = latencies[tfidf.name] + latencies["bge_m3_exact"] + fuse_latency

        reranker = BgeCrossEncoderReranker(
            config.repo_path(str(model_config["bge_reranker_v2_m3"])),
            device=device,
            batch_size=int(model_config.get("reranker_batch_size", 24)),
            max_length=max_length,
        )
        reranked: Rankings = {}
        rerank_latencies: list[float] = []
        for case in cases:
            reranked[case.query_id], latency = reranker.rerank(
                case.query, methods["bm25_bge_rrf"][case.query_id], top_k=candidate_k
            )
            rerank_latencies.append(latency)
        methods["bm25_bge_rrf_bge_reranker"] = reranked
        latencies["bm25_bge_rrf_bge_reranker"] = latencies["bm25_bge_rrf"] + average_search_latency(rerank_latencies)
        del reranker
        _release_gpu()

    summaries: dict[str, dict[str, Any]] = {}
    per_query_rows: list[dict[str, Any]] = []
    for method, rankings in methods.items():
        summary, rows = evaluate_method(
            cases,
            rankings,
            top_k=top_k,
            latency_ms=latencies[method],
            allowed_material_ids=allowed_material_ids,
        )
        summaries[method] = summary
        per_query_rows.extend({"method": method, **row} for row in rows)

    if mode == "all":
        for method, stats in index_stats.items():
            summaries[method].update(stats)
        summaries["bge_m3_exact"]["ann_recall_at_candidate_k"] = 1.0
        for method in ("bge_m3_hnsw", "bge_m3_ivf"):
            summaries[method]["ann_recall_at_candidate_k"] = _ann_recall(
                methods["bge_m3_exact"], methods[method], cases, top_k=candidate_k
            )

    report_root = config.experiment_path(str(config.section("outputs")["report_root"]))
    require_experiment_output(report_root).mkdir(parents=True, exist_ok=True)
    metric_rows = [
        {
            "method": method,
            **{key: value for key, value in summary.items() if not isinstance(value, (dict, list))},
        }
        for method, summary in summaries.items()
    ]
    metric_fields = [
        "method",
        "queries",
        "answerable_queries",
        "no_answer_queries",
        "hit_at_k",
        "recall_at_k",
        "mrr",
        "ndcg_at_k",
        "map_at_k",
        "latency_ms",
        "no_answer_threshold_p05",
        "no_answer_fpr",
        "permission_leak_count",
        "ann_recall_at_candidate_k",
        "index_build_ms",
        "index_size_bytes",
    ]
    _write_csv(report_root / "metrics.csv", metric_rows, metric_fields)
    per_query_serializable = [
        {**row, "top_material_ids": json.dumps(row["top_material_ids"], ensure_ascii=False)} for row in per_query_rows
    ]
    _write_csv(
        report_root / "per_query_metrics.csv",
        per_query_serializable,
        [
            "method",
            "query_id",
            "query",
            "query_type",
            "answerable",
            "hit_at_k",
            "recall_at_k",
            "mrr",
            "ndcg_at_k",
            "map_at_k",
            "top_material_ids",
        ],
    )

    with (report_root / "top10_results.jsonl").open("w", encoding="utf-8") as handle:
        for method, rankings in methods.items():
            for case in cases:
                hits = collapse_to_materials(rankings[case.query_id], top_k=top_k)
                handle.write(
                    json.dumps(
                        {
                            "method": method,
                            "query_id": case.query_id,
                            "query": case.query,
                            "results": [
                                {
                                    "rank": hit.rank,
                                    "material_id": hit.material_id,
                                    "title": hit.title,
                                    "score": hit.score,
                                    "chunk_id": hit.chunk_id,
                                }
                                for hit in hits
                            ],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    with (report_root / "failure_cases.jsonl").open("w", encoding="utf-8") as handle:
        for row in per_query_rows:
            if row["answerable"] and row["recall_at_k"] < 1.0:
                case = next(item for item in cases if item.query_id == row["query_id"])
                handle.write(
                    json.dumps(
                        {
                            "method": row["method"],
                            "query_id": row["query_id"],
                            "query": row["query"],
                            "expected": case.relevance,
                            "retrieved": row["top_material_ids"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    corpus_summary = {
        "materials": len(allowed_material_ids),
        "chunks": len(chunks),
        "metadata_chunks": sum(chunk.source_kind == "metadata" for chunk in chunks),
        "ocr_chunks": sum(chunk.source_kind == "preview_ocr" for chunk in chunks),
        "fingerprint": fingerprint,
    }
    benchmark_summary = {
        "queries": len(cases),
        "answerable_queries": sum(case.answerable for case in cases),
        "no_answer_queries": sum(not case.answerable for case in cases),
    }
    figure_paths = plot_results(summaries, report_root / "figures")
    report_path = write_report(
        report_root / "RAG_EXPERIMENT_REPORT.md",
        summaries=summaries,
        corpus_summary=corpus_summary,
        benchmark_summary=benchmark_summary,
        figure_paths=figure_paths,
    )
    manifest = {
        "schema": "studyhub-rag-experiment-v1",
        "mode": mode,
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "packages": _package_versions(),
        "corpus": corpus_summary,
        "benchmark": benchmark_summary,
        "methods": list(methods),
        "database_access": "forbidden",
        "source_mode": "static_backup_read_only",
        "report": str(report_path.relative_to(config.experiment_path("."))),
    }
    (report_root / "summary.json").write_text(
        json.dumps({"manifest": manifest, "metrics": summaries}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"manifest": manifest, "metrics": summaries}
