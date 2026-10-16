from __future__ import annotations

import os
import tempfile
from pathlib import Path

from studyhub_agent.contracts.knowledge import Corpus, Document
from studyhub_agent.knowledge.chunking import chunk_document


def upsert_document(corpus: Corpus, document: Document, *, child_size: int = 600, parent_size: int = 2400) -> Corpus:
    chunks = chunk_document(document, child_size=child_size, parent_size=parent_size)
    documents = tuple(row for row in corpus.documents if row.document_id != document.document_id) + (document,)
    remaining = tuple(row for row in corpus.chunks if row.document_id != document.document_id) + chunks
    return Corpus(
        documents=tuple(sorted(documents, key=lambda row: row.document_id)),
        chunks=tuple(sorted(remaining, key=lambda row: (row.document_id, row.ordinal))),
    )


def delete_document(corpus: Corpus, document_id: str) -> Corpus:
    return Corpus(
        documents=tuple(row for row in corpus.documents if row.document_id != document_id),
        chunks=tuple(row for row in corpus.chunks if row.document_id != document_id),
    )


def load_corpus(path: Path) -> Corpus:
    return Corpus.model_validate_json(path.read_text(encoding="utf-8"))


def save_corpus(path: Path, corpus: Corpus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish a complete validated revision; a failed reindex never overwrites the last good file.
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(corpus.model_dump_json(indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
