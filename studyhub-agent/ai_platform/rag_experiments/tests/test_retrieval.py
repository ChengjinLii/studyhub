from __future__ import annotations

from studyhub_rag.fusion import reciprocal_rank_fusion, weighted_score_fusion
from studyhub_rag.retrieval import BM25Retriever, TfidfCharRetriever
from studyhub_rag.schemas import Chunk, SearchHit

CHUNKS = [
    Chunk(chunk_id="1:m:0", material_id=1, title="随机信号一页纸", text="考前开卷复习重点"),
    Chunk(chunk_id="2:m:0", material_id=2, title="电子器件期末卷", text="Electronic Devices 2022"),
    Chunk(chunk_id="3:m:0", material_id=3, title="线性代数教材答案", text="课后习题参考"),
]


def test_sparse_retrievers_rank_exact_course_first() -> None:
    for retriever in (BM25Retriever(CHUNKS), TfidfCharRetriever(CHUNKS)):
        hits, _ = retriever.search("随机信号复习", top_k=3)
        assert hits[0].material_id == 1


def test_rrf_rewards_shared_high_rank() -> None:
    first = [SearchHit("a", 1, 10, 1), SearchHit("b", 2, 5, 2)]
    second = [SearchHit("b", 2, 0.9, 1), SearchHit("a", 1, 0.8, 2)]
    fused = reciprocal_rank_fusion([first, second], rrf_k=60, top_k=2)
    assert {hit.material_id for hit in fused} == {1, 2}
    assert fused[0].score == fused[1].score


def test_weighted_fusion_normalizes_incompatible_scales() -> None:
    lexical = [SearchHit("a", 1, 1000, 1), SearchHit("b", 2, 10, 2)]
    dense = [SearchHit("b", 2, 0.9, 1), SearchHit("a", 1, 0.1, 2)]
    fused = weighted_score_fusion([lexical, dense], weights=[0.4, 0.6], top_k=2)
    assert fused[0].material_id == 2
