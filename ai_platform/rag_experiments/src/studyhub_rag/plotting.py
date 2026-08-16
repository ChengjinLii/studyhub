from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from studyhub_rag.guards import require_experiment_output

GOLD = "#D3A73C"
GREEN = "#4A9D7A"
DARK_GREEN = "#2E6A57"
INK = "#17201D"
PAPER = "#F6F6F1"
LABEL_OFFSETS = {
    "bge_m3_exact": (-8, 19),
    "bge_m3_hnsw": (8, -20),
    "bm25_bge_weighted_06_04": (8, 8),
    "tfidf_bge_weighted_06_04": (10, 18),
    "bm25_bge_rrf": (-10, -22),
}


def _label(name: str) -> str:
    labels = {
        "tfidf_char_2_4": "TF-IDF char",
        "bm25_mixed_tokens": "BM25",
        "bge_m3_exact": "BGE-M3 exact",
        "bge_m3_hnsw": "BGE-M3 HNSW",
        "bge_m3_ivf": "BGE-M3 IVF",
        "qwen3_embedding_06b_exact": "Qwen3-Emb 0.6B",
        "bm25_bge_weighted_06_04": "BM25+BGE weighted",
        "tfidf_bge_weighted_06_04": "TF-IDF+BGE weighted",
        "bm25_bge_rrf": "BM25+BGE RRF",
        "tfidf_bge_rrf": "TF-IDF+BGE RRF",
        "bm25_bge_rrf_bge_reranker": "RRF+BGE reranker",
    }
    return labels.get(name, name)


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "axes.edgecolor": DARK_GREEN,
            "axes.labelcolor": INK,
            "text.color": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "font.size": 10,
            "axes.titleweight": "bold",
        }
    )


def plot_results(summaries: Mapping[str, Mapping[str, Any]], output_dir: Path) -> list[Path]:
    output = require_experiment_output(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _style()
    methods = list(summaries)
    labels = [_label(method) for method in methods]
    x = np.arange(len(methods))
    width = 0.25
    paths: list[Path] = []

    fig, ax = plt.subplots(figsize=(15, 7.5))
    for offset, (metric, title, color) in enumerate(
        (("recall_at_k", "Recall@10", GOLD), ("mrr", "MRR", GREEN), ("ndcg_at_k", "nDCG@10", DARK_GREEN))
    ):
        values = [float(summaries[method][metric]) for method in methods]
        bars = ax.bar(x + (offset - 1) * width, values, width, label=title, color=color)
        ax.bar_label(bars, fmt="%.3f", fontsize=7, padding=2, rotation=90)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Score")
    ax.set_title("StudyHub RAG retrieval quality on benchmark_v1")
    ax.set_xticks(x, labels, rotation=28, ha="right")
    ax.grid(axis="y", alpha=0.2)
    ax.legend(frameon=False, ncols=3)
    fig.tight_layout()
    path = output / "retrieval_quality.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    fig, ax = plt.subplots(figsize=(10.5, 7))
    for method in methods:
        latency = max(float(summaries[method]["latency_ms"]), 0.001)
        quality = float(summaries[method]["ndcg_at_k"])
        ax.scatter(
            latency,
            quality,
            s=95,
            color=GREEN if "reranker" not in method else GOLD,
            edgecolor=INK,
            linewidth=0.6,
        )
        offset = LABEL_OFFSETS.get(method, (5, 5))
        ax.annotate(
            _label(method),
            (latency, quality),
            xytext=offset,
            textcoords="offset points",
            fontsize=8,
            ha="right" if offset[0] < 0 else "left",
            arrowprops={"arrowstyle": "-", "color": DARK_GREEN, "alpha": 0.45, "linewidth": 0.6}
            if method in LABEL_OFFSETS
            else None,
        )
    ax.set_xscale("log")
    ax.set_xlabel("Mean query latency (ms, log scale)")
    ax.set_ylabel("nDCG@10")
    ax.set_title("Quality / latency trade-off")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    path = output / "quality_latency_tradeoff.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    query_types = sorted({kind for summary in summaries.values() for kind in summary.get("by_query_type", {})})
    matrix = np.asarray(
        [
            [
                float(summaries[method].get("by_query_type", {}).get(kind, {}).get("ndcg_at_k", 0.0))
                for kind in query_types
            ]
            for method in methods
        ]
    )
    fig, ax = plt.subplots(figsize=(max(9, len(query_types) * 1.4), max(6, len(methods) * 0.55)))
    image = ax.imshow(matrix, cmap="YlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(query_types)), query_types, rotation=30, ha="right")
    ax.set_yticks(range(len(methods)), labels)
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            ax.text(column, row, f"{matrix[row, column]:.2f}", ha="center", va="center", fontsize=8)
    ax.set_title("nDCG@10 by query type")
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout()
    path = output / "query_type_ndcg_heatmap.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)
    return paths
