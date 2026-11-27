from __future__ import annotations

import html
import io
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from foerderpilot.util.http import DEFAULT_USER_AGENT, HttpFetcher


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@runtime_checkable
class SearchBackend(Protocol):
    name: str

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...


class StaticBackend:
    """Deterministisches Backend aus der Config (research.sources) – fuer Tests und Offline-Runs."""

    name = "static"

    def __init__(self, sources: list[dict[str, Any]]):
        self._sources = sources

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        results: list[SearchResult] = []
        for entry in self._sources:
            if str(entry.get("query", "")).strip() and str(entry["query"]).strip() not in query:
                continue
            for r in entry.get("results", []):
                results.append(
                    SearchResult(
                        title=str(r.get("title", "")),
                        url=str(r.get("url", "")),
                        snippet=str(r.get("snippet", "")),
                    )
                )
            if len(results) >= max_results:
                break
        return results[:max_results]


class DuckDuckGoHtmlBackend:
    """Best-Effort-Websuche ueber das DuckDuckGo-HTML-Endpunkt (kein API-Key noetig)."""

    name = "ddg"
    _RESULT_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    _SNIPPET_RE = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S)

    def __init__(self, fetcher: HttpFetcher | None = None):
        self.fetcher = fetcher or HttpFetcher()

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        page = self.fetcher.get_text(url)
        links = self._RESULT_RE.findall(page)
        snippets = [re.sub(r"<[^>]+>", "", s) for s in self._SNIPPET_RE.findall(page)]
        results = []
        for i, (href, title_html) in enumerate(links[:max_results]):
            title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            if href.startswith("//"):
                href = "https:" + href
            results.append(
                SearchResult(
                    title=title,
                    url=html.unescape(href),
                    snippet=html.unescape(snippets[i]) if i < len(snippets) else "",
                )
            )
        return results


_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_ALL_TAGS_RE = re.compile(r"<[^>]+>")


def _html_to_text(raw: str, max_chars: int) -> str:
    raw = _TAG_RE.sub(" ", raw)
    text = html.unescape(_ALL_TAGS_RE.sub(" ", raw))
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def pdf_to_text(data: bytes, max_chars: int = 20000) -> str:
    """Extrahiert Text aus einem PDF (Extra: pip install foerderpilot[pdf])."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF-Support fehlt: bitte 'pip install foerderpilot[pdf]' (pypdf) installieren."
        ) from exc
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


_HREF_RE = re.compile(r'(?:href|src)="([^"]+)"', re.I)


def extract_links(html_text: str, base_url: str) -> list[str]:
    """Absolute HTTP(S)-Links aus HTML extrahieren (für Multi-Hop-Crawl), Duplikate entfernt."""
    links: list[str] = []
    seen: set[str] = set()
    for raw in _HREF_RE.findall(html_text):
        url = urllib.parse.urljoin(base_url, html.unescape(raw)).split("#")[0]
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            links.append(url)
    return links


def build_fetcher(config: dict[str, Any]) -> Callable[[str], str]:
    """Fetcher aus config.research aufbauen: UA, robots.txt, Retry/Backoff, Crawl-Delay, PDF/HTML."""
    page_fetch = build_page_fetcher(config)

    def fetch(url: str) -> str:
        return page_fetch(url)[0]

    return fetch


def _http_from_config(config: dict[str, Any]) -> HttpFetcher:
    r = config.get("research") or {}
    return HttpFetcher(
        user_agent=str(r.get("user_agent", DEFAULT_USER_AGENT)),
        timeout=float(r.get("timeout", 30.0)),
        max_retries=int(r.get("max_retries", 2)),
        backoff_base=float(r.get("backoff_base", 1.0)),
        crawl_delay=float(r.get("crawl_delay", 1.0)),
        respect_robots=bool(r.get("respect_robots", True)),
    )


def build_page_fetcher(config: dict[str, Any]) -> Callable[[str], tuple[str, list[str]]]:
    """Wie build_fetcher, liefert aber (text, links) – Basis fürs Multi-Hop-Crawling."""
    r = config.get("research") or {}
    http = _http_from_config(config)
    max_chars = int(r.get("max_chars", 20000))

    def fetch_page(url: str) -> tuple[str, list[str]]:
        data, content_type = http.get_bytes(url)
        if "pdf" in content_type.lower() or urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
            return pdf_to_text(data, max_chars), []
        raw = data.decode("utf-8", errors="replace")
        return _html_to_text(raw, max_chars), extract_links(raw, url)

    return fetch_page


def fetch_text(url: str, max_chars: int = 20000, timeout: float = 20.0, fetcher: Callable[[str], str] | None = None) -> str:
    """Kompatibilitaets-Wrapper: holt eine URL als Text (HTML bereinigt oder PDF via pypdf)."""
    if fetcher is not None:
        return fetcher(url)[:max_chars]
    http = HttpFetcher(timeout=timeout, max_retries=0, crawl_delay=0.0, respect_robots=False)
    data, content_type = http.get_bytes(url)
    if "pdf" in content_type.lower() or urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
        return pdf_to_text(data, max_chars)
    return _html_to_text(data.decode("utf-8", errors="replace"), max_chars)


def build_backend(config: dict[str, Any]):
    """Such-Backend aus der Config waehlen: research.backend = 'ddg' (Default) oder 'static'."""
    research_cfg = config.get("research") or {}
    kind = str(research_cfg.get("backend", "ddg")).lower()
    if kind == "static":
        return StaticBackend(list(research_cfg.get("sources", [])))
    if kind == "ddg":
        return DuckDuckGoHtmlBackend()
    raise ValueError(f"Unbekanntes research.backend: {kind!r} (erwartet: ddg, static)")
