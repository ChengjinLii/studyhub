from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studyhub_rag.guards import require_experiment_output


def write_report(
    output_path: Path,
    *,
    summaries: Mapping[str, Mapping[str, Any]],
    corpus_summary: Mapping[str, Any],
    benchmark_summary: Mapping[str, Any],
    figure_paths: Sequence[Path],
) -> Path:
    path = require_experiment_output(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(summaries.items(), key=lambda item: float(item[1]["ndcg_at_k"]), reverse=True)
    lines = [
        "# StudyHub RAG 对比实验报告",
        "",
        f"> 生成时间：{datetime.now(UTC).isoformat()}  ",
        "> 定位：离线实验实现，不代表当前网站生产部署。",
        "",
        "## 结论",
        "",
    ]
    if ordered:
        best_name, best = ordered[0]
        lines.append(
            f"当前 `benchmark_v1` 上，按 nDCG@10 排名最高的方法是 **{best_name}**："
            f"Recall@10={best['recall_at_k']:.4f}，MRR={best['mrr']:.4f}，nDCG@10={best['ndcg_at_k']:.4f}。"
        )
    lines.extend(
        [
            "",
            "本实验把 `Interview_QA-CV` 中提到的 TF-IDF / BM25、BGE-M3、双路融合、RRF、ANN 与 Reranker "
            "落实为可运行代码并做统一评测。StudyHub 当前生产搜索仍是字段包含匹配和人工权重；本目录没有接入生产 API。",
            "",
            "## 数据与隔离",
            "",
            f"- 静态资料数：{corpus_summary['materials']}，全部为免费公开资料。",
            f"- Chunk 数：{corpus_summary['chunks']}，其中元数据 Chunk {corpus_summary['metadata_chunks']}，"
            f"预览 OCR Chunk {corpus_summary['ocr_chunks']}。",
            f"- 评测 Query：{benchmark_summary['queries']}，可回答 {benchmark_summary['answerable_queries']}，"
            f"无答案 {benchmark_summary['no_answer_queries']}。",
            "- 输入只来自 `backup/oss_materials` 静态快照；代码不导入后端、不连接数据库、不读取 SQLite。",
            "- 公开 API 快照没有保留 `files/<uuid>` 到 `material_id` 的映射，因此没有猜测关联原文件；"
            "文档证据使用可验证的 `materials/<id>/preview`。",
            "",
            "## 总体指标",
            "",
            "| 方法 | Recall@10 | Hit@10 | MRR | nDCG@10 | MAP@10 | 延迟 ms | 无答案 FPR | 权限泄漏 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, summary in ordered:
        lines.append(
            f"| {name} | {summary['recall_at_k']:.4f} | {summary['hit_at_k']:.4f} | {summary['mrr']:.4f} | "
            f"{summary['ndcg_at_k']:.4f} | {summary['map_at_k']:.4f} | {summary['latency_ms']:.3f} | "
            f"{summary['no_answer_fpr']:.4f} | {summary['permission_leak_count']} |"
        )
    ann_methods = [name for name in ("bge_m3_exact", "bge_m3_hnsw", "bge_m3_ivf") if name in summaries]
    if ann_methods:
        lines.extend(
            [
                "",
                "## BGE-M3 索引对照",
                "",
                "| 索引 | ANN Recall@candidate_k | 检索延迟 ms | 构建时间 ms | 索引大小 MB |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for name in ann_methods:
            summary = summaries[name]
            lines.append(
                f"| {name} | {summary.get('ann_recall_at_candidate_k', 1.0):.4f} | "
                f"{summary['latency_ms']:.3f} | {summary.get('index_build_ms', 0.0):.3f} | "
                f"{summary.get('index_size_bytes', 0) / 1024 / 1024:.3f} |"
            )
    lines.extend(["", "## 图表", ""])
    for figure in figure_paths:
        lines.append(f"![{figure.stem}]({figure.relative_to(path.parent).as_posix()})")
        lines.append("")
    lines.extend(
        [
            "## 方法口径",
            "",
            "- TF-IDF 使用字符 2-4 gram，BM25 使用中英文混合分词及中文 bigram。",
            "- BGE-M3 与 Qwen3-Embedding-0.6B 使用本地权重和归一化向量；Qwen Query 使用模型内置 instruction。",
            "- Exact、HNSW、IVFFlat 使用同一组 BGE-M3 向量，以便观察 ANN 的质量和速度差异。",
            "- 加权融合先对每路分数做 min-max 归一化，再按词法 0.6 / 向量 0.4 合并。",
            "- RRF 使用排名而非原始分数，默认 `k=60`；精排使用本地 `bge-reranker-v2-m3`。",
            "- Chunk 结果先排序，再按 `material_id` 去重聚合，指标在资料级计算。",
            "",
            "## 局限",
            "",
            "`benchmark_v1` 是依据真实资料标题、标签和用途人工整理的第一版小型评测集，"
            "还不是由多位用户独立标注的金标集。"
            "无答案阈值使用可回答 Query 顶分的 P05 做初步校准，只能用于方法内诊断。后续应增加真实搜索日志、双人标注、"
            "冲突仲裁和按课程分层的置信区间。OCR 只覆盖公开预览页，无法代表原文件全部页内容。",
            "",
            "## 复现",
            "",
            "```bash",
            "cd /data/chengjin/studyhub/studyhub-agent/ai_platform/rag_experiments",
            "uv sync --extra dense --extra ocr --extra dev",
            "uv run studyhub-rag verify-isolation",
            "uv run studyhub-rag ocr-previews",
            "uv run studyhub-rag build-corpus",
            "uv run studyhub-rag run --mode all",
            "uv run studyhub-rag verify-results",
            "```",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
