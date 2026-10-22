import json

import httpx
import pytest

from studyhub_agent.contracts.render import _template
from studyhub_agent.serving import probe
from tests.runtime.fakes import CharTokenizer


def server(config, *, bad=""):
    calls = []

    def handle(request):
        path = request.url.path
        if path == "/health":
            return httpx.Response(200)
        if path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "wrong" if bad == "alias" else config.served_model_name,
                            "max_model_len": 8192 if bad == "context" else config.max_model_len,
                        }
                    ]
                },
            )
        if path == "/metrics":
            if bad == "metrics":
                raise httpx.ConnectError("test", request=request)
            return httpx.Response(200, text="# mock metrics")
        body = json.loads(request.content)
        if path == "/tokenize":
            # Emulate HF's wire-message path, not render_text's internal Message conversion.
            for message in body["messages"]:
                for call in message.get("tool_calls", []):
                    call["function"]["arguments"] = json.loads(call["function"]["arguments"])
            rendered = _template().render(
                messages=body["messages"],
                tools=body["tools"],
                add_generation_prompt=True,
                enable_thinking=False,
            )
            return httpx.Response(200, json={"tokens": [] if bad == "tokens" else CharTokenizer().encode(rendered)})
        assert path == "/v1/chat/completions"
        calls.append(body)
        if len(calls) == 1:
            arguments = {"a": 17, "b": 27 if bad == "arguments" else 26}
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_server_999",
                        "type": "function",
                        "function": {
                            "name": "studyhub_probe_add",
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            }
            if bad == "reasoning":
                message["reasoning_content"] = "unexpected thinking"
            finish = "length" if bad == "truncated" else "tool_calls"
        else:
            assert any(row["role"] == "tool" and row["content"].startswith('{"result":43}') for row in body["messages"])
            assert body["tool_choice"] == "none" and "tools" not in body
            assert any(row["role"] == "tool" and "只输出工具返回的数字" in row["content"] for row in body["messages"])
            message, finish = {"content": "wrong" if bad == "final" else "43"}, "stop"
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": finish}]})

    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def test_tool_roundtrip_and_both_server_prompt_templates(serving_config):
    client, calls = server(serving_config)
    with client:
        report = probe.smoke(serving_config, client=client, tokenizer=CharTokenizer())
    assert report["ok"] and report["model_calls"] == 2 and report["tool_calls"] == 1
    assert len(report["server_prompt_tokens_checked"]) == 2
    assert report["metrics_available"]
    assert not calls[0]["chat_template_kwargs"]["enable_thinking"]


@pytest.mark.parametrize(
    "bad,code",
    [
        ("alias", "model_alias"),
        ("context", "model_context"),
        ("tokens", "server_tokenizer"),
        ("arguments", "tool_arguments"),
        ("reasoning", "tool_call_protocol"),
        ("truncated", "tool_call_protocol"),
        ("final", "tool_result_followup"),
    ],
)
def test_probe_rejects_incompatible_services(serving_config, bad, code):
    client, _ = server(serving_config, bad=bad)
    with client, pytest.raises(probe.ProbeError, match=code):
        probe.smoke(serving_config, client=client, tokenizer=CharTokenizer())


def test_metrics_are_optional(serving_config):
    client, _ = server(serving_config, bad="metrics")
    with client:
        assert not probe.smoke(serving_config, client=client, tokenizer=CharTokenizer())["metrics_available"]


def test_owned_client_disables_env_proxy_and_forwards_key(serving_config, monkeypatch):
    client, _ = server(serving_config)
    original_post = client.post

    def post(*args, **kwargs):
        if args[0].endswith("chat/completions"):
            assert kwargs["headers"]["Authorization"] == "Bearer fake-probe-key"
        return original_post(*args, **kwargs)

    client.post = post

    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["headers"]["Authorization"] == "Bearer fake-probe-key"
        return client

    monkeypatch.setenv(serving_config.api_key_env, "fake-probe-key")
    monkeypatch.setattr(probe.httpx, "Client", factory)
    monkeypatch.setattr(probe.HFTokenizer, "from_model_dir", lambda _: CharTokenizer())
    assert probe.smoke(serving_config)["ok"]
