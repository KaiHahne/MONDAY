import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from foerderpilot.llm.client import ENV_API_KEY, LLMError, OpenAICompatibleClient


class _StubHandler(BaseHTTPRequestHandler):
    captured = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        _StubHandler.captured = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": body,
        }
        if self.path == "/v1/chat/completions":
            response = {
                "choices": [{"message": {"role": "assistant", "content": "# Entwurf\nTest-Antrag"}}]
            }
            payload = json.dumps(response).encode("utf-8")
            self.send_response(200)
        else:
            payload = json.dumps({"error": "not found"}).encode("utf-8")
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture()
def stub_server():
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    thread.join()


def test_from_env_requires_key(monkeypatch):
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    with pytest.raises(LLMError, match=ENV_API_KEY):
        OpenAICompatibleClient.from_env()


def test_complete_against_loopback(stub_server, monkeypatch):
    monkeypatch.setenv(ENV_API_KEY, "test-key-123")
    client = OpenAICompatibleClient.from_env()
    client.base_url = stub_server
    client.model = "test-model"
    answer = client.complete("system", "prompt")
    assert answer == "# Entwurf\nTest-Antrag"
    assert _StubHandler.captured["path"] == "/v1/chat/completions"
    assert _StubHandler.captured["authorization"] == "Bearer test-key-123"
    assert _StubHandler.captured["body"]["model"] == "test-model"
    assert _StubHandler.captured["body"]["messages"][0]["role"] == "system"


def test_complete_http_error(stub_server):
    client = OpenAICompatibleClient(api_key="k", base_url=stub_server + "/wrong", model="m")
    with pytest.raises(LLMError, match="HTTP 404"):
        client.complete("s", "p")


def test_empty_key_rejected():
    with pytest.raises(LLMError):
        OpenAICompatibleClient(api_key="")
