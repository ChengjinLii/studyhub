from pathlib import Path

from studyhub_agent.environments.replay.index import Bm25Index, mixed_tokens
from studyhub_agent.environments.replay.snapshot import load_snapshot

SNAPSHOT = load_snapshot(Path(__file__).parent.parent / "fixtures" / "replay_snapshot.json")


def test_mixed_tokens_emits_chinese_unigrams_bigrams_and_latin_words() -> None:
    assert mixed_tokens("高数 Final2025") == ["final2025", "高", "数", "高数"]


def test_search_ranks_relevant_material_first_and_is_deterministic() -> None:
    index = Bm25Index(SNAPSHOT.materials)
    first = index.search("高等数学 期末 真题", limit=3)
    assert first[0][1].material_id == 102
    assert index.search("高等数学 期末 真题", limit=3) == first


def test_empty_query_returns_nothing() -> None:
    assert Bm25Index(SNAPSHOT.materials).search("   ", limit=5) == []
