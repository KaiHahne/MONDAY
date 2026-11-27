from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from typing import Any

DEFAULT_USER_AGENT = "foerderpilot-research/0.1 (+https://github.com; kontakt: betreiber)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RobotsBlocked(PermissionError):
    pass


class HttpFetcher:
    """Kleiner HTTP-Client mit robots.txt-Check, Retry/Backoff bei 429/5xx und Crawl-Delay pro Host.

    Wird vom Research-Pfad (Webseiten/PDFs) genutzt. Authentifizierte System-APIs
    (REST-Connector) brauchen robots nicht – die respektieren wir bewusst nur beim Crawlen.
    """

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff_base: float = 1.0,
        crawl_delay: float = 0.0,
        respect_robots: bool = True,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.crawl_delay = crawl_delay
        self.respect_robots = respect_robots
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_request: dict[str, float] = {}

    def robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urllib.parse.urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(origin + "/robots.txt")
            try:
                req = urllib.request.Request(origin + "/robots.txt", headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    rp.parse(resp.read().decode("utf-8", errors="replace").splitlines())
            except Exception:
                rp.parse([])  # ohne robots.txt: alles erlaubt
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(self.user_agent, url)

    def _throttle(self, url: str) -> None:
        if self.crawl_delay <= 0:
            return
        host = urllib.parse.urlparse(url).netloc
        now = time.monotonic()
        wait = self.crawl_delay - (now - self._last_request.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def get_bytes(self, url: str, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
        if not self.robots_allowed(url):
            raise RobotsBlocked(f"robots.txt verbietet den Abruf: {url}")
        base_headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        base_headers.update(headers or {})
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle(url)
            request = urllib.request.Request(url, headers=base_headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    return resp.read(), resp.headers.get("Content-Type", "")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in RETRYABLE_STATUS and attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2**attempt))
                    continue
                raise RuntimeError(f"HTTP {exc.code} beim Abruf von {url.split('?')[0]}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base * (2**attempt))
                    continue
                raise RuntimeError(f"nicht erreichbar: {url} ({exc.reason})") from exc
        raise last_error if last_error else RuntimeError(f"Abruf fehlgeschlagen: {url}")

    def get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        data, _ = self.get_bytes(url, headers=headers)
        return data.decode("utf-8", errors="replace")

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        data, _ = self.get_bytes(url, headers={**(headers or {}), "Accept": "application/json"})
        return json.loads(data.decode("utf-8"))
