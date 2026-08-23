from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolTurn:
    name: str
    arguments: dict[str, Any]


class ScriptedOpenAIServer:
    """Minimal non-streaming Chat Completions server for real Hermes tests."""

    def __init__(self, turns: list[ToolTurn], final_answer: str) -> None:
        self.turns = list(turns)
        self.final_answer = final_answer
        self.requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("server has not started")
        host, port = self._server.server_address
        return f"http://{host}:{port}/v1"

    @property
    def observed_tool_results(self) -> list[str]:
        observed: list[str] = []
        for request in self.requests:
            for message in request.get("messages", []):
                if message.get("role") == "tool":
                    name = str(message.get("name") or message.get("tool_call_id") or "")
                    if name and name not in observed:
                        observed.append(name)
        return observed

    @property
    def tool_result_messages(self) -> list[dict[str, Any]]:
        if not self.requests:
            return []
        return [message for message in self.requests[-1].get("messages", []) if message.get("role") == "tool"]

    def __enter__(self) -> ScriptedOpenAIServer:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def do_GET(self):
                if self.path.rstrip("/") == "/v1/models":
                    self._json_response(
                        200,
                        {"object": "list", "data": [{"id": "fake-studyhub", "object": "model"}]},
                    )
                    return
                self._json_response(404, {"error": {"message": "not found"}})

            def do_POST(self):
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self._json_response(404, {"error": {"message": "not found"}})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                owner.requests.append(payload)
                index = len(owner.requests) - 1
                if index > 0:
                    previous = owner.turns[index - 1]
                    tool_messages = [
                        message for message in payload.get("messages", []) if message.get("role") == "tool"
                    ]
                    if not tool_messages or not any(message.get("content") for message in tool_messages):
                        self._json_response(400, {"error": {"message": f"missing result for {previous.name}"}})
                        return
                if index < len(owner.turns):
                    turn = owner.turns[index]
                    call_id = f"call_{index:03d}_{turn.name}"
                    message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": turn.name,
                                    "arguments": json.dumps(turn.arguments, ensure_ascii=False),
                                },
                            }
                        ],
                    }
                    finish_reason = "tool_calls"
                else:
                    message = {"role": "assistant", "content": owner.final_answer}
                    finish_reason = "stop"
                self._json_response(
                    200,
                    {
                        "id": f"chatcmpl-fixture-{index}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": "fake-studyhub",
                        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    },
                )

            def _json_response(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="fake-openai", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
