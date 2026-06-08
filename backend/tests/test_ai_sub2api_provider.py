from __future__ import annotations

from app.core.config import Settings
from app.services.ai_service import AiService


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _service() -> AiService:
    return AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]


def test_sub2api_sse_parser_prefers_done_text() -> None:
    payload = "\n".join(
        [
            'event: response.output_text.delta',
            'data: {"type":"response.output_text.delta","delta":"{\\"ok\\""}',
            "",
            'event: response.output_text.done',
            'data: {"type":"response.output_text.done","text":"{\\"ok\\":true}"}',
        ]
    )

    assert _service()._extract_sub2api_content(payload) == '{"ok":true}'


def test_sub2api_sse_parser_falls_back_to_delta_text() -> None:
    payload = "\n".join(
        [
            'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":"}',
            'data: {"type":"response.output_text.delta","delta":"true}"}',
        ]
    )

    assert _service()._extract_sub2api_content(payload) == '{"ok":true}'


def test_sub2api_provider_posts_responses_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> _FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse('data: {"type":"response.output_text.done","text":"{\\"ok\\":true}"}')

    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)

    settings = Settings(
        ai_agent_provider="sub2api",
        ai_agent_base_url="http://127.0.0.1:8787/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="gpt-5.4-mini",
        ai_agent_timeout_seconds=12,
    )

    content = _service()._call_agent_model(settings, "system prompt", {"user_query": "期末真题"})

    assert content == '{"ok":true}'
    assert captured["url"] == "http://127.0.0.1:8787/v1/responses"
    assert captured["headers"] == {"Authorization": "Bearer test-key", "Content-Type": "application/json"}
    assert captured["client_kwargs"] == {"timeout": 12, "trust_env": False}
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-5.4-mini"
    assert body["instructions"] == "system prompt"
    assert body["max_output_tokens"] == 900
    assert body["reasoning"] == {"effort": "none"}
    assert body["store"] is False
    assert isinstance(body["input"], list)


def test_chat_completions_provider_keeps_legacy_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatResponse:
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeChatResponse:
            captured["url"] = url
            captured["json"] = json
            return FakeChatResponse()

    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)

    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )

    content = _service()._call_agent_model(settings, "system prompt", {"user_query": "期末真题"})

    assert content == '{"ok":true}'
    assert captured["url"] == "https://example.test/v1/chat/completions"
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["model"] == "demo-model"
    assert isinstance(body["messages"], list)


def test_chat_completions_provider_sends_image_as_multimodal_content(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatResponse:
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeChatResponse:
            del url, headers
            captured["json"] = json
            return FakeChatResponse()

    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)

    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    image_url = "data:image/png;base64,aW1hZ2U="

    _service()._call_agent_model(
        settings,
        "system prompt",
        {
            "user_query": "分析题目截图",
            "image_attachments": [{"name": "question.png", "mime_type": "image/png"}],
            "_image_attachment_data_urls": [image_url],
        },
    )

    body = captured["json"]
    assert isinstance(body, dict)
    messages = body["messages"]
    assert isinstance(messages, list)
    user_message = messages[1]
    assert isinstance(user_message, dict)
    content = user_message["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "_image_attachment_data_urls" not in content[0]["text"]
    assert content[1] == {"type": "image_url", "image_url": {"url": image_url}}


def test_sub2api_provider_sends_image_as_input_image(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> _FakeResponse:
            del url, headers
            captured["json"] = json
            return _FakeResponse('data: {"type":"response.output_text.done","text":"{\\"ok\\":true}"}')

    monkeypatch.setattr("app.services.ai_service.httpx.Client", FakeClient)

    settings = Settings(
        ai_agent_provider="sub2api",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    image_url = "data:image/png;base64,aW1hZ2U="

    _service()._call_agent_model(
        settings,
        "system prompt",
        {
            "user_query": "分析题目截图",
            "_image_attachment_data_urls": [image_url],
        },
    )

    body = captured["json"]
    assert isinstance(body, dict)
    inputs = body["input"]
    assert isinstance(inputs, list)
    content = inputs[0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "input_text"
    assert "_image_attachment_data_urls" not in content[0]["text"]
    assert content[1] == {"type": "input_image", "image_url": image_url}
