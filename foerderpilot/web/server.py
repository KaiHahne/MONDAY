from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from foerderpilot.config import load_config
from foerderpilot.pipeline import run_pipeline

TOKEN_ENV = "FOERDERPILOT_WEB_TOKEN"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

_APP_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class JobManager:
    """Fuehrt die Pipeline in einem Hintergrund-Thread aus (ein Lauf gleichzeitig)."""

    def __init__(self, pipeline_fn: Callable[[dict[str, Any]], Any]):
        self._pipeline_fn = pipeline_fn
        self._lock = threading.Lock()
        self._job: dict[str, Any] | None = None

    def start(self, config: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            if self._job and self._job["status"] == "running":
                return None
            self._job = {
                "id": uuid.uuid4().hex[:12],
                "status": "running",
                "started": time.time(),
                "finished": None,
                "error": None,
            }
            job = self._job
        threading.Thread(target=self._run, args=(job, config), daemon=True).start()
        return self.snapshot()

    def _run(self, job: dict[str, Any], config: dict[str, Any]) -> None:
        try:
            result = self._pipeline_fn(config)
            job["status"] = "done"
            job["output_dir"] = str(result.output_dir)
            job["applications"] = result.context.applications
            job["eligible"] = sum(1 for m in result.context.matches if m.eligible)
            job["matches_total"] = len(result.context.matches)
            job["trace"] = [e.to_dict() for e in result.context.events]
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["trace"] = []
        finally:
            job["finished"] = time.time()

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._job) if self._job else None


class WebHandler(BaseHTTPRequestHandler):
    server_version = "foerderpilot-web"
    protocol_version = "HTTP/1.1"

    manager: JobManager
    config: dict[str, Any]
    token: str
    index_html: str

    def _authorized(self) -> bool:
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {self.token}")

    def _send(self, body: bytes, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _send_json(self, obj: Any, status: int = 200) -> None:
        self._send(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), status, "application/json")

    def _deny(self) -> None:
        self._send_json({"error": "unauthorized – Bearer-Token fehlt oder falsch"}, 401)

    def _read_out(self, name: str) -> None:
        path = Path(self.config["output_dir"]) / name
        if not path.exists():
            self._send_json({"error": f"noch kein Lauf vorhanden ({name} fehlt)"}, 404)
            return
        self._send_json(json.loads(path.read_text(encoding="utf-8")))

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._deny()
            return
        path = urlparse(self.path).path
        if path == "/":
            self._send(self.index_html.encode("utf-8"), 200, "text/html; charset=utf-8")
        elif path == "/api/status":
            self._send_json({"job": self.manager.snapshot()})
        elif path == "/api/matches":
            self._read_out("matches.json")
        elif path == "/api/applications":
            self._read_out("applications.json")
        elif path == "/api/trace":
            self._read_out("trace.json")
        elif path.startswith("/api/applications/"):
            app_id = path.rsplit("/", 1)[-1]
            if not _APP_ID_RE.match(app_id):
                self._send_json({"error": "ungueltige Programm-ID"}, 400)
                return
            md = Path(self.config["output_dir"]) / "applications" / f"{app_id}.md"
            if not md.exists():
                self._send_json({"error": "Antrag nicht gefunden"}, 404)
                return
            self._send(md.read_bytes(), 200, "text/markdown; charset=utf-8")
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._deny()
            return
        path = urlparse(self.path).path
        if path == "/api/run":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            job = self.manager.start(self.config)
            if job is None:
                self._send_json({"error": "es laeuft bereits ein Lauf"}, 409)
            else:
                self._send_json({"job": job}, 202)
        else:
            self._send_json({"error": "not found"}, 404)

    def log_message(self, *args: Any) -> None:
        pass


def create_server(
    config: dict[str, Any],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str | None = None,
    pipeline_fn: Callable[[dict[str, Any]], Any] | None = None,
) -> ThreadingHTTPServer:
    if not token:
        raise RuntimeError(
            f"Web-UI braucht ein Bearer-Token: bitte {TOKEN_ENV} in der Umgebung setzen "
            "(z. B. export FOERDERPILOT_WEB_TOKEN=<zufaelliges-token>)."
        )
    manager = JobManager(pipeline_fn or (lambda cfg: run_pipeline(cfg)))
    index_html = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
    handler = type(
        "BoundWebHandler",
        (WebHandler,),
        {"manager": manager, "config": config, "token": token, "index_html": index_html},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(config_path: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise SystemExit(
            f"Web-UI verweigert den Start ohne Token: bitte {TOKEN_ENV} setzen, "
            f"z. B. export {TOKEN_ENV}=<zufaelliges-token>."
        )
    config = load_config(config_path)
    server = create_server(config, host=host, port=port, token=token)
    print(f"foerderpilot Web-UI: http://{host}:{port}  (Bearer-Token-Pflicht aktiv, Config: {config_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
