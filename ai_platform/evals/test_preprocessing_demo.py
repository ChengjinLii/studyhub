from __future__ import annotations

import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.preprocessing.ai_document import build_ai_documents, chunk_text, load_source_records, redact_contacts


SAMPLE_PATH = AI_PLATFORM_ROOT / "data" / "sample_documents.json"


def test_build_ai_documents_preserves_source_identity() -> None:
    records = load_source_records(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))
    documents = build_ai_documents(records, chunk_size=120, overlap=20)

    assert documents
    assert {document.source_type for document in documents} == {"material", "column", "request"}
    assert all(document.id.startswith(f"{document.source_type}:{document.source_id}:chunk:") for document in documents)


def test_redact_contacts_removes_direct_contact_values() -> None:
    text = "联系邮箱 user@example.com，手机号 13800138000，QQ 12345678"

    redacted = redact_contacts(text)

    assert "user@example.com" not in redacted
    assert "13800138000" not in redacted
    assert "12345678" not in redacted
    assert redacted.count("[REDACTED_CONTACT]") == 3


def test_chunk_text_uses_overlap() -> None:
    chunks = chunk_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10, overlap=2)

    assert chunks[0] == "abcdefghij"
    assert chunks[1].startswith("ij")
