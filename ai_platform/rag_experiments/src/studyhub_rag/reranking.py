from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from studyhub_rag.schemas import SearchHit


class BgeCrossEncoderReranker:
    def __init__(self, model_path: Path, *, device: str, batch_size: int, max_length: int) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as error:
            raise RuntimeError("Reranker dependencies are missing; run `uv sync --extra dense`") from error
        self.torch = torch
        self.device = torch.device(device)
        self.batch_size = batch_size
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
        dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(model_path), local_files_only=True, torch_dtype=dtype
        ).to(self.device)
        self.model.eval()

    def rerank(self, query: str, candidates: Sequence[SearchHit], *, top_k: int) -> tuple[list[SearchHit], float]:
        if not candidates:
            return [], 0.0
        started = perf_counter()
        scores: list[float] = []
        pairs = [[query, f"{hit.title}\n{hit.text}"] for hit in candidates]
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start : start + self.batch_size]
            encoded = self.tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            ).to(self.device)
            with self.torch.inference_mode():
                logits = self.model(**encoded, return_dict=True).logits.view(-1).float().cpu().tolist()
            scores.extend(float(value) for value in logits)
        ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: -pair[1])[:top_k]
        hits = [
            SearchHit(
                chunk_id=hit.chunk_id,
                material_id=hit.material_id,
                score=score,
                rank=rank,
                title=hit.title,
                text=hit.text,
            )
            for rank, (hit, score) in enumerate(ranked, start=1)
        ]
        return hits, (perf_counter() - started) * 1000
