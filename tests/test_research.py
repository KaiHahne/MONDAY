import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from foerderpilot.programs.loader import load_programs
from foerderpilot.research import StaticBackend, fetch_text, research_programs

PAGE = """
<html><body><h1>BAFA Energieberatung</h1>
<p>Das BAFA foerdert Energieberatungen fuer KMU bis 250 Beschaeftigte mit 80 Prozent,
maximal 6000 Euro. Antragsstelle: BAFA, Referat 412, E-Mail: energieberatung@bafa.bund.de.
Voraussetzungen: Sitz in Deutschland, Jahresumsatz bis 50 Mio Euro.</p></body></html>
"""


class _PageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def page_server():
    server = HTTPServer(("127.0.0.1", 0), _PageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/programm"
    server.shutdown()
    thread.join()


class FakeLLM:
    def __init__(self, card=None):
        self.card = card or {
            "programs": [
                {
                    "id": "bafa-ebm-test",
                    "name": "BAFA Energieberatung (Test)",
                    "provider": "BAFA",
                    "level": "bund",
                    "url": "https://example.org",
                    "contact": {"stelle": "BAFA Referat 412", "email": "energieberatung@bafa.bund.de"},
                    "criteria": [
                        {"field": "employees", "op": "<=", "value": 250, "required": True, "weight": 2},
                        {"field": "hq_country", "op": "in", "value": ["DE"]},
                    ],
                    "required_documents": ["Antragsformular"],
                    "funding": {"type": "Zuschuss", "max_rate": 0.8, "max_amount_eur": 6000},
                }
            ]
        }

    def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
        return "```json\n" + json.dumps(self.card, ensure_ascii=False) + "\n```"


def make_config(page_url, tmp_path):
    return {
        "research": {
            "backend": "static",
            "levels": ["bund"],
            "topics": ["Energie"],
            "sources": [{"query": "Foerderprogramme Energie", "results": [{"title": "BAFA", "url": page_url, "snippet": "..."}]}],
        }
    }


def test_research_writes_draft(page_server, tmp_path):
    config = make_config(page_server, tmp_path)
    out = tmp_path / "research"
    report = research_programs(
        config,
        llm=FakeLLM(),
        search_backend=StaticBackend(config["research"]["sources"]),
        fetcher=fetch_text,
        out_dir=out,
        profile={"hq_state": "BY", "industry": "Maschinenbau"},
    )
    assert report.errors == [], report.errors
    assert report.per_level == {"bund": 1}
    draft = out / "bund-bafa-ebm-test.json"
    assert draft.exists()
    data = json.loads(draft.read_text(encoding="utf-8"))
    assert data["status"] == "draft"
    assert data["researched_level"] == "bund"
    assert data["contact"]["email"] == "energieberatung@bafa.bund.de"
    assert data["criteria"][0]["field"] == "employees"
    assert (out / "research-report.json").exists()
    # Drafts landen NICHT im normalen programs_dir -> werden nicht vom Loader gepickt
    programs = load_programs(tmp_path / "programs") if (tmp_path / "programs").exists() else []
    assert programs == []


def test_research_bad_llm_json_counted_as_error(page_server, tmp_path):
    class BadLLM:
        def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
            return "das ist kein json"

    config = make_config(page_server, tmp_path)
    out = tmp_path / "research"
    report = research_programs(
        config,
        llm=BadLLM(),
        search_backend=StaticBackend(config["research"]["sources"]),
        fetcher=lambda url: "x" * 500,
        out_dir=out,
    )
    assert report.drafts == []
    assert report.errors and "kein JSON" in report.errors[0]


def test_research_rejects_unknown_level(tmp_path):
    with pytest.raises(ValueError, match="Unbekannte Ebene"):
        research_programs({}, llm=FakeLLM(), search_backend=StaticBackend([]), out_dir=tmp_path, levels=["mars"])
