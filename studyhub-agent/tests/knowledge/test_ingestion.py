import json

import pytest
from pydantic import ValidationError

from studyhub_agent.contracts.knowledge import Corpus
from studyhub_agent.knowledge.chunking import chunk_document, make_document
from studyhub_agent.knowledge.store import delete_document, load_corpus, save_corpus, upsert_document


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_chunks_preserve_all_source_characters_and_locations(newline):
    text = newline.join(["# 根标题", "", "## 子标题", *("中文内容🙂，需要保留位置。" for _ in range(80))])
    document = make_document("demo", "notes.md", text)
    chunks = chunk_document(document, child_size=100, parent_size=350)
    assert len(chunks) > 5
    assert "".join(row.text for row in chunks) == text
    assert any(row.context_header == "根标题 / 子标题" for row in chunks)
    assert all(text[row.start : row.end] == row.text for row in chunks)
    assert all(row.line_start == text.count("\n", 0, row.start) + 1 for row in chunks)
    assert Corpus(documents=(document,), chunks=chunks)


@pytest.mark.parametrize(
    "block",
    [
        "```python\n# fake heading\n" + "print(42)\n" * 20 + "```\n",
        "~~~text\n# fake heading\n" + "x\n" * 100 + "~~~\n",
        "$$\n" + "a+b+c+d\n" * 20 + "$$\n",
        "| a | b |\n|---|---|\n" + "| 1 | 2 |\n" * 20,
    ],
)
def test_protected_content_is_not_split_or_used_as_a_heading(block):
    text = "# Real\n\n" + block + "\n## Next\nother content\n"
    chunks = chunk_document(make_document("demo", "notes", text), child_size=64, parent_size=200)
    assert any(block.rstrip("\n") in row.text for row in chunks)
    assert all("fake heading" not in row.context_header for row in chunks)
    assert "".join(row.text for row in chunks) == text


def test_unclosed_code_block_is_preserved():
    text = "# Title\n```python\n" + "x = 1\n" * 40
    chunks = chunk_document(make_document("demo", "notes", text), child_size=64, parent_size=100)
    assert any("x = 1\n" * 40 in row.text for row in chunks)


def test_nested_headings_do_not_create_title_only_search_hits():
    text = "# Root\n\n## Detail\n\nActual paragraph.\n"
    chunks = chunk_document(make_document("demo", "notes", text))
    assert len(chunks) == 1
    assert chunks[0].context_header == "Root / Detail"
    assert chunks[0].text == text


@pytest.mark.parametrize("text", ["", "a" * 300, "\n\n", "没有换行的正文" * 100])
def test_empty_and_unstructured_sources(text):
    document = make_document("demo", "notes", text)
    chunks = chunk_document(document, child_size=64, parent_size=200)
    assert "".join(row.text for row in chunks) == text
    assert Corpus(documents=(document,), chunks=chunks)


@pytest.mark.parametrize("child,parent", [(0, 500), (True, 500), (100, 99), (100, 12001)])
def test_invalid_chunk_budgets(child, parent):
    with pytest.raises(ValueError, match="chunk sizes"):
        chunk_document(make_document("demo", "notes", "content"), child_size=child, parent_size=parent)


def test_oversized_protected_block_fails_instead_of_truncating():
    with pytest.raises(ValueError, match="protected"):
        chunk_document(make_document("demo", "notes", "$$" + "x" * 12000 + "$$"))


def test_document_revision_replaces_old_chunks(corpus):
    original = next(row for row in corpus.documents if row.source == "projection.md")
    updated = make_document("demo", original.source, "# 更新\n新版本答案。")
    replaced = upsert_document(corpus, updated)
    assert updated.document_id == original.document_id
    assert updated.revision != original.revision
    old_ids = {row.chunk_id for row in corpus.chunks if row.document_id == original.document_id}
    assert old_ids.isdisjoint(row.chunk_id for row in replaced.chunks)
    assert upsert_document(replaced, updated).fingerprint == replaced.fingerprint
    deleted = delete_document(replaced, updated.document_id)
    assert all(row.document_id != updated.document_id for row in deleted.chunks)


@pytest.mark.parametrize("field,value", [("text", "tampered"), ("revision", "old"), ("line_start", 99)])
def test_corpus_rejects_forged_source_evidence(corpus, field, value):
    data = corpus.model_dump(mode="json")
    data["chunks"][0][field] = value
    with pytest.raises(ValidationError):
        Corpus.model_validate(data)


def test_snapshot_roundtrip_and_failed_atomic_replace(corpus, tmp_path, monkeypatch):
    path = tmp_path / "corpus.json"
    save_corpus(path, corpus)
    assert load_corpus(path).fingerprint == corpus.fingerprint
    before = path.read_bytes()

    def fail(*args):
        raise OSError("simulated write failure")

    monkeypatch.setattr("studyhub_agent.knowledge.store.os.replace", fail)
    with pytest.raises(OSError):
        save_corpus(path, Corpus())
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    assert json.loads(before)["schema_version"] == "studyhub.knowledge.v1"
