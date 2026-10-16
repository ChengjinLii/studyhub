import json

import httpx
import pytest

from studyhub_agent.cli import main
from studyhub_agent.knowledge.store import load_corpus
from tests.runtime.fakes import CharTokenizer


def test_local_index_search_and_read_without_network(tmp_path, capsys, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("local workflow must not create a network client")

    monkeypatch.setattr("studyhub_agent.cli.httpx.Client", no_network)
    path = tmp_path / "notes.md"
    path.write_text("# 投影\n\n残差与方向向量正交。", encoding="utf-8")
    corpus = tmp_path / "corpus.json"
    prefix = ["--corpus", str(corpus)]
    assert main([*prefix, "index", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["documents"] == 1
    assert main([*prefix, "search", "残差"]) == 0
    hit = json.loads(capsys.readouterr().out)["hits"][0]
    assert main([*prefix, "read", hit["evidence"]["chunk_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["evidence"][0]["citation"].startswith("[k_")
    assert main([*prefix, "list"]) == 0
    assert len(json.loads(capsys.readouterr().out)["documents"]) == 1
    assert main([*prefix, "--kb", "other", "search", "残差"]) == 0
    assert not json.loads(capsys.readouterr().out)["hits"]


def test_failed_import_preserves_existing_corpus(tmp_path, capsys):
    source = tmp_path / "notes.txt"
    source.write_text("Original content", encoding="utf-8")
    corpus = tmp_path / "corpus.json"
    prefix = ["--corpus", str(corpus)]
    assert main([*prefix, "index", str(source)]) == 0
    before = corpus.read_bytes()
    source.write_text("Changed content", encoding="utf-8")
    invalid = tmp_path / "unsupported.pdf"
    invalid.write_bytes(b"not a document")
    assert main([*prefix, "index", str(source), str(invalid)]) == 2
    assert corpus.read_bytes() == before


def test_incomplete_provider_config_is_an_error(tmp_path, capsys):
    assert main(["--embedding-endpoint", "http://model/embeddings", "list"]) == 2
    assert "configured together" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["rag", "agent"])
def test_cli_generation_uses_real_policy_wire_contract(tmp_path, capsys, monkeypatch, mode):
    source = tmp_path / "notes.md"
    source.write_text("# 投影\n\n残差与方向向量正交。", encoding="utf-8")
    corpus = tmp_path / "corpus.json"
    assert main(["--corpus", str(corpus), "index", str(source)]) == 0
    capsys.readouterr()
    chunk_id = load_corpus(corpus).chunks[0].chunk_id
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert str(request.url) == "http://model/v1/chat/completions"
        message = {"content": f"残差与方向向量正交。[{chunk_id}]"}
        if mode == "agent" and len(calls) == 1:
            names = [row["function"]["name"] for row in body["tools"]]
            assert names == ["search_knowledge", "read_document", "list_documents"]
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call",
                        "type": "function",
                        "function": {
                            "name": "search_knowledge",
                            "arguments": json.dumps({"query": "残差"}),
                        },
                    }
                ],
            }
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}]})

    class Tokenizer(CharTokenizer):
        revision = "offline-test"

    real_client = httpx.Client
    monkeypatch.setattr("studyhub_agent.cli.HFTokenizer.from_model_dir", lambda path: Tokenizer())
    monkeypatch.setattr(
        "studyhub_agent.cli.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw)
    )
    code = main(
        [
            "--corpus",
            str(corpus),
            "ask",
            "投影的残差是什么？",
            "--mode",
            mode,
            "--model-url",
            "http://model",
            "--model",
            "test-model",
            "--model-dir",
            str(tmp_path),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    if mode == "rag":
        assert result["status"] == "answered"
        assert len(calls) == 1 and not calls[0]["tools"]
    else:
        assert result["termination"] == "final_answer"
        assert result["architecture_trace"]["citation_verified"]
        assert len(calls) == 2
        assert result["spec"]["principal"] == {"principal_id": "local", "kind": "knowledge"}
