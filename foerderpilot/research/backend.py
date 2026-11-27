from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


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
    _RESULT_RE = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S
    )
    _SNIPPET_RE = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S)

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        request = urllib.request.Request(url, headers={"User-Agent": "foerderpilot-research/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            page = resp.read().decode("utf-8", errors="replace")
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


def fetch_text(url: str, max_chars: int = 20000, timeout: float = 20.0) -> str:
    """holt eine Seite und liefert grob bereinigten Text (fuer LLM-Extraktion)."""
    request = urllib.request.Request(url, headers={"User-Agent": "foerderpilot-research/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    raw = _TAG_RE.sub(" ", raw)
    text = html.unescape(_ALL_TAGS_RE.sub(" ", raw))
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def build_backend(config: dict[str, Any]):
    """Backend aus der Config waehlen: research.backend = 'ddg' (Default) oder 'static' (research.sources)."""
    research_cfg = config.get("research") or {}
    kind = str(research_cfg.get("backend", "ddg")).lower()
    if kind == "static":
        return StaticBackend(list(research_cfg.get("sources", [])))
    if kind == "ddg":
        return DuckDuckGoHtmlBackend()
    raise ValueError(f"Unbekanntes research.backend: {kind!r} (erwartet: ddg, static)")
