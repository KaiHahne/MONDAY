import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from foerderpilot.research import build_fetcher, pdf_to_text, research_programs, StaticBackend
from foerderpilot.research.backend import _html_to_text
from foerderpilot.util.http import HttpFetcher, RobotsBlocked


def make_pdf(text: str) -> bytes:
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        None,
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs[3] = b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objs)+1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF\n".encode())
    out.seek(0)
    return out.read()


class HardeningHandler(BaseHTTPRequestHandler):
    state = {"hits": 0}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/robots.txt":
            body = b"User-agent: *\nDisallow: /private\n"
            ctype = "text/plain"
        elif path == "/private/doc":
            body = b"<html>geheim</html>"
            ctype = "text/html"
        elif path == "/flaky":
            HardeningHandler.state["hits"] += 1
            if HardeningHandler.state["hits"] <= 2:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b"<html><body>OK nach Retry</body></html>"
            ctype = "text/html"
        elif path == "/doc.pdf":
            body = make_pdf("Investitionsbetrag 150000 EUR foerderung")
            ctype = "application/pdf"
        else:
            body = b"<html><body>Hallo Foerderprogramm Seite mit genug Text damit sie nicht zu kurz ist. " * 5 + b"</body></html>"
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    HardeningHandler.state["hits"] = 0
    srv = HTTPServer(("127.0.0.1", 0), HardeningHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    t.join()


def test_pdf_to_text_real_pdf():
    text = pdf_to_text(make_pdf("Investitionsbetrag 150000 EUR"))
    assert "150000" in text


def test_build_fetcher_reads_pdf(server):
    fetch = build_fetcher({"research": {"respect_robots": False, "crawl_delay": 0}})
    text = fetch(f"{server}/doc.pdf")
    assert "150000" in text and "foerderung" in text


def test_build_fetcher_reads_html(server):
    fetch = build_fetcher({"research": {"respect_robots": False, "crawl_delay": 0}})
    text = fetch(f"{server}/public")
    assert "Hallo Foerderprogramm" in text and "<html>" not in text


def test_robots_txt_block_and_allow(server):
    http = HttpFetcher(respect_robots=True, crawl_delay=0, max_retries=0)
    with pytest.raises(RobotsBlocked):
        http.get_bytes(f"{server}/private/doc")
    data, _ = http.get_bytes(f"{server}/public")
    assert b"Hallo" in data


def test_retry_backoff_on_500(server):
    http = HttpFetcher(respect_robots=False, crawl_delay=0, max_retries=2, backoff_base=0.01)
    data, _ = http.get_bytes(f"{server}/flaky")
    assert b"OK nach Retry" in data
    assert HardeningHandler.state["hits"] == 3
    http0 = HttpFetcher(respect_robots=False, crawl_delay=0, max_retries=0)
    HardeningHandler.state["hits"] = 0
    with pytest.raises(RuntimeError, match="HTTP 500"):
        http0.get_bytes(f"{server}/flaky")


def test_crawl_delay(server):
    http = HttpFetcher(respect_robots=False, crawl_delay=0.15, max_retries=0)
    start = time.monotonic()
    http.get_bytes(f"{server}/a")
    http.get_bytes(f"{server}/b")
    assert time.monotonic() - start >= 0.14


class FakeLLM:
    def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
        return json.dumps({"programs": []})


def test_research_manual_fallback_list(server, tmp_path):
    short_url = f"{server}/robots.txt"  # robots.txt ist kurz -> 'Seite zu kurz' -> manual
    config = {
        "research": {
            "backend": "static",
            "levels": ["bund"],
            "topics": ["X"],
            "respect_robots": False,
            "crawl_delay": 0,
            "sources": [{"query": "Foerderprogramme X", "results": [{"title": "Kurz", "url": short_url}]}],
        }
    }
    report = research_programs(
        config,
        llm=FakeLLM(),
        search_backend=StaticBackend(config["research"]["sources"]),
        out_dir=tmp_path / "research",
    )
    assert report.drafts == []
    assert report.errors
    assert report.manual and report.manual[0]["url"] == short_url
    payload = json.loads((tmp_path / "research" / "research-report.json").read_text(encoding="utf-8"))
    assert payload["manual"] and "manual_hint" in payload
