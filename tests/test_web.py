import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd
import pytest

from foerderpilot.config import load_config
from foerderpilot.pipeline import run_pipeline
from foerderpilot.web.server import TOKEN_ENV, create_server


class FakeLLM:
    def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
        return "# Foerderantrag (Entwurf)\n\nFake-LLM-Antwort."


def make_project(tmp_path: Path) -> Path:
    lake = tmp_path / "data_lake"
    lake.mkdir(exist_ok=True)
    pd.DataFrame(
        [{"firma": "Web GmbH", "land": "DE", "mitarbeiter": 50, "umsatz": 5000000}]
    ).to_csv(lake / "stammdaten.csv", index=False)
    (lake / "kennzahlen.json").write_text(
        json.dumps([{"kennzahl": "investitionsbetrag", "wert": 50000}]), encoding="utf-8"
    )
    programs = tmp_path / "programs"
    programs.mkdir(exist_ok=True)
    (programs / "p.json").write_text(
        json.dumps(
            {
                "id": "prog-web",
                "name": "Web-Programm",
                "provider": "Test",
                "criteria": [
                    {"field": "hq_country", "op": "in", "value": ["DE"]},
                    {"field": "investment_amount_eur", "op": ">=", "value": 1000},
                ],
            }
        ),
        encoding="utf-8",
    )
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"connectors:\n  - type: local\n    root: {lake}\nprograms_dir: {programs}\noutput_dir: {tmp_path / 'out'}\n",
        encoding="utf-8",
    )
    return cfg


def start_server(config, token="test-token-123", delay=0.0):
    def fake_pipeline(cfg):
        if delay:
            time.sleep(delay)
        return run_pipeline(cfg, llm_client=FakeLLM())

    server = create_server(config, "127.0.0.1", 0, token=token, pipeline_fn=fake_pipeline)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def req(base, path, token=None, method="GET"):
    r = urllib.request.Request(base + path, method=method)
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture()
def web(tmp_path):
    config = load_config(make_project(tmp_path))
    server, thread = start_server(config)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, "test-token-123", tmp_path
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def test_token_required_at_startup(tmp_path):
    config = load_config(make_project(tmp_path))
    with pytest.raises(RuntimeError, match=TOKEN_ENV):
        create_server(config, "127.0.0.1", 0, token=None)


def test_unauthorized(web):
    base, token, _ = web
    assert req(base, "/")[0] == 401
    assert req(base, "/api/status")[0] == 401
    assert req(base, "/api/run", method="POST")[0] == 401
    assert req(base, "/", token="wrong")[0] == 401


def test_index_and_full_run(web):
    base, token, tmp_path = web
    status, body = req(base, "/", token=token)
    assert status == 200 and b"foerderpilot" in body

    status, body = req(base, "/api/run", token=token, method="POST")
    assert status == 202

    deadline = time.time() + 15
    job = None
    while time.time() < deadline:
        _, body = req(base, "/api/status", token=token)
        job = json.loads(body)["job"]
        if job and job["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert job and job["status"] == "done", job
    assert job["eligible"] == 1 and job["matches_total"] == 1

    _, body = req(base, "/api/matches", token=token)
    matches = json.loads(body)
    assert matches[0]["program"]["id"] == "prog-web" and matches[0]["eligible"] is True

    _, body = req(base, "/api/applications", token=token)
    apps = json.loads(body)
    assert apps[0]["program_id"] == "prog-web"

    status, body = req(base, "/api/applications/prog-web", token=token)
    assert status == 200 and b"Foerderantrag" in body

    status, _ = req(base, "/api/applications/..%2F..%2Fconfig", token=token)
    assert status == 400


def test_conflict_while_running(tmp_path):
    config = load_config(make_project(tmp_path))
    server, thread = start_server(config, delay=1.5)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        token = "test-token-123"
        assert req(base, "/api/run", token=token, method="POST")[0] == 202
        status, body = req(base, "/api/run", token=token, method="POST")
        assert status == 409
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_no_run_yet_returns_404(web):
    base, token, _ = web
    assert req(base, "/api/matches", token=token)[0] == 404
