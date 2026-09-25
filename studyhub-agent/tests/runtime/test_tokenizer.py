import hashlib
from pathlib import Path

from studyhub_agent.runtime.tokenizer import HFTokenizer, tokenizer_revision


def test_tokenizer_revision_hashes_the_tokenizer_json_contents(tmp_path: Path) -> None:
    model_dir = tmp_path / "Qwen3.5-4B"
    model_dir.mkdir()
    content = b'{"fake": "tokenizer"}'
    (model_dir / "tokenizer.json").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    assert tokenizer_revision(model_dir) == f"Qwen3.5-4B@sha256:{digest[:12]}"


def test_tokenizer_revision_changes_when_contents_change(tmp_path: Path) -> None:
    # A size- or mtime-based revision would miss a same-size content edit; hash the bytes.
    model_dir = tmp_path / "m"
    model_dir.mkdir()
    (model_dir / "tokenizer.json").write_bytes(b"aaaa")
    first = tokenizer_revision(model_dir)
    (model_dir / "tokenizer.json").write_bytes(b"bbbb")
    assert tokenizer_revision(model_dir) != first


def test_hftokenizer_exposes_the_revision_it_was_constructed_with() -> None:
    tokenizer = HFTokenizer(backend=object(), stop_token_ids=(), revision="m@sha256:abc123")
    assert tokenizer.revision == "m@sha256:abc123"
