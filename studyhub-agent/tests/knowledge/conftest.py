import pytest

from studyhub_agent.contracts.knowledge import Corpus, KnowledgeScope
from studyhub_agent.knowledge.chunking import make_document
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.knowledge.store import upsert_document


@pytest.fixture
def corpus():
    result = Corpus()
    for source, kb, text in (
        ("projection.md", "demo", "# 正交投影\n\n非零向量的投影公式为 v^T u / u^T u。残差与 u 正交。\n"),
        ("least-squares.md", "demo", "# 最小二乘\n\n最小二乘通过 QR 分解求解，残差与列空间正交。\n"),
        ("secret.md", "private", "# 私密记录\n\n不可向其他知识库返回的秘密：隐藏答案为 991。\n"),
    ):
        result = upsert_document(result, make_document(kb, source, text))
    return result


@pytest.fixture
def retriever(corpus):
    return KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})))
