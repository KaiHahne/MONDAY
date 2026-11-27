import base64
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd
import pytest

from foerderpilot.agents.gapsearch import GapSearchAgent, extract_value
from foerderpilot.config import load_config
from foerderpilot.connectors.factory import build_connectors
from foerderpilot.pipeline import run_pipeline

SEEN_AUTH = {}


class FakeJiraHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        SEEN_AUTH["header"] = self.headers.get("Authorization", "")
        jql = query.get("jql", [""])[0]
        if "Investitionsbetrag" in jql or "investitionsbetrag" in jql.lower():
            issues = [
                {
                    "key": "PROJ-1",
                    "fields": {
                        "summary": "Investitionsvorhaben 2026",
                        "description": "Investitionsbetrag: 150000 EUR. Anlagen: Kostenplan.pdf",
                        "attachment": [{"filename": "Kostenplan.pdf"}],
                    },
                }
            ]
        else:
            issues = [
                {"key": "PROJ-9", "fields": {"summary": "Allgemein", "description": "nichts Relevantes"}}
            ]
        body = json.dumps({"issues": issues}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def jira_server(monkeypatch):
    monkeypatch.setenv("JIRA_USER", "bot@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "secret-token-xyz")
    server = HTTPServer(("127.0.0.1", 0), FakeJiraHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


def rest_cfg(base_url, name="jira"):
    return {
        "type": "rest",
        "name": name,
        "preset": "jira",
        "base_url": base_url,
        "auth": {"scheme": "basic", "user": "env:JIRA_USER", "password": "env:JIRA_TOKEN"},
    }


def test_rest_connector_catalog_search_and_auth(jira_server):
    connectors = build_connectors([rest_cfg(jira_server)])
    conn = connectors[0]
    refs = conn.list_datasets()
    assert refs and refs[0].name == "jira"
    df = conn.read_dataset(refs[0])
    assert "fields_summary" in df.columns
    hits = conn.search("Investitionsbetrag", limit=5)
    assert hits and hits[0]["id"] == "PROJ-1"
    assert "150000" in hits[0]["snippet"]
    assert hits[0]["url"].endswith("/browse/PROJ-1")
    expected = "Basic " + base64.b64encode(b"bot@example.com:secret-token-xyz").decode()
    assert SEEN_AUTH["header"] == expected  # Token kommt aus der Umgebung, nie aus der Config


def test_factory_rejects_unknown_preset():
    with pytest.raises(ValueError, match="Unbekanntes REST-Preset"):
        build_connectors([{"type": "rest", "preset": "dagobert", "base_url": "http://127.0.0.1:1"}])


def test_extract_value():
    assert extract_value("investment_amount_eur", "Investitionsbetrag: 150000 EUR") == 150000
    assert extract_value("investment_amount_eur", "investitionsbetrag = 12.500,50") == 12500.5
    assert extract_value("employees", "Mitarbeiter: 80") == 80
    assert extract_value("purpose", "Vorhaben: Digitalisierung der Linie") == "Digitalisierung der Linie"
    assert extract_value("employees", "kein Treffer hier") is None


class FakeLLM:
    def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
        return "# Entwurf\n\nFake."


def make_project(tmp_path: Path, jira_base: str) -> Path:
    lake = tmp_path / "data_lake"
    lake.mkdir()
    # absichtlich ohne Investitionsbetrag -> Luecke, die GapSearch im Jira fuellen soll
    pd.DataFrame([{"firma": "Agentik GmbH", "land": "DE", "mitarbeiter": 80}]).to_csv(
        lake / "stammdaten.csv", index=False
    )
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "p.json").write_text(
        json.dumps(
            {
                "id": "prog-jira",
                "name": "Investitionsprogramm",
                "provider": "Behoerde",
                "criteria": [
                    {"field": "hq_country", "op": "in", "value": ["DE"]},
                    {"field": "investment_amount_eur", "op": ">=", "value": 1000, "required": True, "weight": 3},
                ],
                "contact": {"stelle": "Hotline", "email": "hotline@behoerde.example"},
            }
        ),
        encoding="utf-8",
    )
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""
connectors:
  - type: local
    root: {lake}
  - type: rest
    name: jira
    preset: jira
    base_url: {jira_base}
    auth:
      scheme: basic
      user: env:JIRA_USER
      password: env:JIRA_TOKEN
programs_dir: {programs}
output_dir: {tmp_path / 'out'}
""",
        encoding="utf-8",
    )
    return cfg


def test_pipeline_gapsearch_fills_profile_and_rematches(jira_server, tmp_path):
    config = load_config(make_project(tmp_path, jira_server))
    result = run_pipeline(config, llm_client=FakeLLM())
    ctx = result.context
    out = Path(config["output_dir"])

    # GapSearch hat den Investitionsbetrag aus Jira ins Profil getragen
    assert ctx.profile.get("investment_amount_eur") == 150000
    assert ctx.profile_changed is True
    # Re-Match: Programm jetzt eligible
    by_id = {m.program.id: m for m in ctx.matches}
    assert by_id["prog-jira"].eligible is True
    # Evidence protokolliert
    evidence = json.loads((out / "gap_evidence.json").read_text(encoding="utf-8"))
    assert "prog-jira" in evidence
    assert any(e["hit"]["id"] == "PROJ-1" for e in evidence["prog-jira"])
    # nach Re-Gap keine missing_profile_field-Luecke mehr
    gaps = json.loads((out / "gaps.json").read_text(encoding="utf-8"))
    assert all(g["type"] != "missing_profile_field" for g in gaps.get("prog-jira", []))
    # Trace enthaelt GapSearch
    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    assert any(e["agent"] == "GapSearch" for e in trace)


def test_gapsearch_without_rest_sources_is_noop(tmp_path):
    from foerderpilot.agents.base import AgentContext
    from foerderpilot.agents.gap import GapAnalysisAgent
    from foerderpilot.agents.matcher import ProgramMatcherAgent
    from foerderpilot.agents.explorer import DataLakeExplorerAgent
    from foerderpilot.orchestrator import Orchestrator

    cfg = make_project(tmp_path, "http://127.0.0.1:1")
    text = cfg.read_text(encoding="utf-8")
    text = text.split("  - type: rest")[0]  # REST-Quelle entfernen
    cfg.write_text(text, encoding="utf-8")
    config = load_config(cfg)
    ctx = AgentContext(config)
    Orchestrator([DataLakeExplorerAgent(), ProgramMatcherAgent(), GapAnalysisAgent(), GapSearchAgent()]).run(ctx)
    assert ctx.evidence == {}
    assert ctx.profile_changed is False
    assert ctx.profile.get("investment_amount_eur") is None
