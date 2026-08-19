from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from time import perf_counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from studyhub_rag.schemas import Chunk, SearchHit
from studyhub_rag.text import mixed_tokens


def hits_from_scores(chunks: Sequence[Chunk], scores: np.ndarray, *, top_k: int) -> list[SearchHit]:
    if len(chunks) != len(scores):
        raise ValueError("Chunk and score lengths differ")
    count = min(max(0, top_k), len(chunks))
    if not count:
        return []
    candidate_indices = np.argpartition(-scores, count - 1)[:count]
    ordered = candidate_indices[np.argsort(-scores[candidate_indices], kind="stable")]
    return [
        SearchHit(
            chunk_id=chunks[int(index)].chunk_id,
            material_id=chunks[int(index)].material_id,
            score=float(scores[int(index)]),
            rank=rank,
            title=chunks[int(index)].title,
            text=chunks[int(index)].text,
        )
        for rank, index in enumerate(ordered, start=1)
    ]


class TfidfCharRetriever:
    name = "tfidf_char_2_4"

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = list(chunks)
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), sublinear_tf=True, norm="l2")
        self.matrix = self.vectorizer.fit_transform(chunk.retrieval_text for chunk in self.chunks)

    def search(self, query: str, *, top_k: int) -> tuple[list[SearchHit], float]:
        started = perf_counter()
        query_vector = self.vectorizer.transform([query])
        scores = (self.matrix @ query_vector.T).toarray().ravel()
        return hits_from_scores(self.chunks, scores, top_k=top_k), (perf_counter() - started) * 1000


class BM25Retriever:
    name = "bm25_mixed_tokens"

    def __init__(self, chunks: Sequence[Chunk], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        tokenized = [mixed_tokens(chunk.retrieval_text) for chunk in self.chunks]
        self.term_frequencies = [Counter(tokens) for tokens in tokenized]
        self.doc_lengths = np.asarray([len(tokens) for tokens in tokenized], dtype=np.float32)
        self.avg_doc_length = float(self.doc_lengths.mean()) if len(self.doc_lengths) else 0.0
        document_frequency: Counter[str] = Counter()
        for tokens in tokenized:
            document_frequency.update(set(tokens))
        total = len(tokenized)
        self.idf = {
            token: math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            for token, frequency in document_frequency.items()
        }

    def score(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.chunks), dtype=np.float32)
        if not self.chunks or self.avg_doc_length <= 0:
            return scores
        for token in mixed_tokens(query):
            idf = self.idf.get(token)
            if idf is None:
                continue
            frequencies = np.fromiter((terms.get(token, 0) for terms in self.term_frequencies), dtype=np.float32)
            denominator = frequencies + self.k1 * (1 - self.b + self.b * self.doc_lengths / self.avg_doc_length)
            scores += idf * (frequencies * (self.k1 + 1)) / np.maximum(denominator, 1e-12)
        return scores

    def search(self, query: str, *, top_k: int) -> tuple[list[SearchHit], float]:
        started = perf_counter()
        hits = hits_from_scores(self.chunks, self.score(query), top_k=top_k)
        return hits, (perf_counter() - started) * 1000


class SentenceTransformerEncoder:
    def __init__(self, model_path: Path, *, device: str, batch_size: int, max_length: int) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError("Dense dependencies are missing; run `uv sync --extra dense`") from error
        self.model_path = model_path
        self.batch_size = batch_size
        self.model = SentenceTransformer(str(model_path), device=device, trust_remote_code=False)
        self.model.max_seq_length = max_length
        self.query_prompt_name = "query" if "query" in getattr(self.model, "prompts", {}) else None

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            self.model.encode(
                list(texts),
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=True,
            ),
            dtype=np.float32,
        )

    def encode_queries(self, texts: Sequence[str]) -> tuple[np.ndarray, float]:
        started = perf_counter()
        kwargs = {"prompt_name": self.query_prompt_name} if self.query_prompt_name else {}
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            **kwargs,
        )
        elapsed_ms = (perf_counter() - started) * 1000
        return np.asarray(vectors, dtype=np.float32), elapsed_ms


class ExactDenseIndex:
    name = "exact"

    def __init__(self, chunks: Sequence[Chunk], embeddings: np.ndarray) -> None:
        started = perf_counter()
        self.chunks = list(chunks)
        self.embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)
        self.build_ms = (perf_counter() - started) * 1000
        self.serialized_size_bytes = int(self.embeddings.nbytes)

    def search_vector(self, query_vector: np.ndarray, *, top_k: int) -> tuple[list[SearchHit], float]:
        started = perf_counter()
        scores = self.embeddings @ np.asarray(query_vector, dtype=np.float32)
        return hits_from_scores(self.chunks, scores, top_k=top_k), (perf_counter() - started) * 1000


class FaissDenseIndex:
    def __init__(
        self,
        chunks: Sequence[Chunk],
        embeddings: np.ndarray,
        *,
        kind: str,
        hnsw_m: int = 32,
        hnsw_ef_search: int = 64,
        ivf_nlist: int = 16,
        ivf_nprobe: int = 4,
    ) -> None:
        try:
            import faiss
        except ImportError as error:
            raise RuntimeError("FAISS is missing; run `uv sync --extra dense`") from error
        started = perf_counter()
        self.faiss = faiss
        self.chunks = list(chunks)
        vectors = np.ascontiguousarray(embeddings, dtype=np.float32)
        dimension = vectors.shape[1]
        if kind == "hnsw":
            index = faiss.IndexHNSWFlat(dimension, hnsw_m, faiss.METRIC_INNER_PRODUCT)
            index.hnsw.efConstruction = max(80, hnsw_ef_search * 2)
            index.hnsw.efSearch = hnsw_ef_search
        elif kind == "ivf":
            # FAISS recommends roughly 39 training points per IVF centroid.
            max_trained_nlist = max(1, len(vectors) // 39)
            nlist = max(1, min(ivf_nlist, max_trained_nlist))
            quantizer = faiss.IndexFlatIP(dimension)
            index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
            index.train(vectors)
            index.nprobe = max(1, min(ivf_nprobe, nlist))
        else:
            raise ValueError(f"Unsupported FAISS index kind: {kind}")
        index.add(vectors)
        self.name = kind
        self.index = index
        self.build_ms = (perf_counter() - started) * 1000
        self.serialized_size_bytes = len(faiss.serialize_index(index))

    def search_vector(self, query_vector: np.ndarray, *, top_k: int) -> tuple[list[SearchHit], float]:
        started = perf_counter()
        scores, indices = self.index.search(np.asarray(query_vector, dtype=np.float32).reshape(1, -1), top_k)
        hits: list[SearchHit] = []
        for rank, (score, index) in enumerate(zip(scores[0], indices[0], strict=True), start=1):
            if index < 0:
                continue
            chunk = self.chunks[int(index)]
            hits.append(
                SearchHit(
                    chunk_id=chunk.chunk_id,
                    material_id=chunk.material_id,
                    score=float(score),
                    rank=rank,
                    title=chunk.title,
                    text=chunk.text,
                )
            )
        return hits, (perf_counter() - started) * 1000


def average_search_latency(latencies: Iterable[float]) -> float:
    values = list(latencies)
    return float(np.mean(values)) if values else 0.0
