from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from foerderpilot.llm.client import LLMClient
from foerderpilot.programs.loader import ProgramValidationError
from foerderpilot.programs.models import Criterion, FundingProgram
from foerderpilot.research.backend import SearchBackend, build_fetcher, build_page_fetcher

LEVELS = ("eu", "bund", "land", "gemeinde")

DEFAULT_QUERY_TEMPLATE = (
    "Foerderprogramme {topic} {level} {region} {city} 2026 Unternehmen KMU "
    "Voraussetzungen Kriterien Antragsstelle Zuwendungsgeber"
)

EXTRACT_SYSTEM = (
    "Du recherchierst Foerderprogramme oeffentlicher Stellen. Extrahiere aus dem gegebenen "
    "Webseiten-Text ALLE Foerderprogramme, die dort beschrieben sind, als JSON-Objekt:\n"
    '{"programs": [{"id": "...", "name": "...", "provider": "...", "level": "eu|bund|land|gemeinde", '
    '"url": "...", "description": "...", "contact": {"stelle": "...", "email": "...", "telefon": "..."}, '
    '"criteria": [{"field": "...", "op": "...", "value": ..., "required": true, "weight": 1}], '
    '"required_documents": [...], "funding": {...}, "deadline": null}]}\n'
    "Regeln: nur Angaben verwenden, die im Text explizit stehen; unbekannt -> null bzw. leere Liste; "
    "criteria nur uebernehmen, wenn explizit formuliert (z. B. 'bis 250 Beschaeftigte' -> employees<=250); "
    "contact.email nur wenn sichtbar; op aus ==,!=,>=,<=,>,<,in,not_in,contains,exists; "
    "id als slug (klein, Bindestriche). Antworte ausschliesslich mit JSON."
)


@dataclass
class ResearchReport:
    drafts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    per_level: dict[str, int] = field(default_factory=dict)
    manual: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "drafts": self.drafts,
            "errors": self.errors,
            "per_level": self.per_level,
            "manual": self.manual,
            "manual_hint": "Eintraege unter 'manual' konnten nicht automatisch gelesen werden "
            "(Login/JS/leeres PDF) – bitte manuell oeffnen und als Draft in programs/research/ nachtragen.",
        }


def build_query(template: str, level: str, profile: dict[str, Any], topic: str) -> str:
    return template.format(
        level=level,
        topic=topic,
        region=str(profile.get("hq_state") or "Deutschland"),
        city=str(profile.get("hq_city") or ""),
        industry=str(profile.get("industry") or ""),
    ).strip()


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def extract_program_cards(llm: LLMClient, page_text: str, source_url: str) -> list[dict[str, Any]]:
    prompt = (
        f"QUELL-URL: {source_url}\n\nTEXT:\n{page_text}\n\n"
        "Extrahiere die Foerderprogramme als JSON (siehe System-Prompt)."
    )
    raw = _strip_fences(llm.complete(EXTRACT_SYSTEM, prompt, temperature=0.0, max_tokens=3000))
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProgramValidationError(f"LLM-Antwort ist kein JSON: {exc}") from exc
    cards = data.get("programs") if isinstance(data, dict) else data
    if not isinstance(cards, list):
        raise ProgramValidationError("LLM-Antwort enthaelt keine Programmliste.")
    return [c for c in cards if isinstance(c, dict)]


def card_to_program(card: dict[str, Any], level: str, source_url: str) -> FundingProgram:
    card = dict(card)
    card.setdefault("id", "unbekannt")
    card.setdefault("name", "Unbenanntes Programm")
    card.setdefault("level", level)
    criteria = []
    for c in card.get("criteria") or []:
        crit = Criterion(
            field=str(c.get("field", "")),
            op=str(c.get("op", "")),
            value=c.get("value"),
            required=bool(c.get("required", True)),
            weight=float(c.get("weight", 1.0)),
        )
        crit.validate()
        criteria.append(crit)
    program = FundingProgram(
        id=str(card["id"]),
        name=str(card["name"]),
        provider=str(card.get("provider") or ""),
        description=str(card.get("description") or ""),
        url=str(card.get("url") or source_url),
        region=[str(card.get("level") or level)],
        purposes=list(card.get("purposes") or []),
        criteria=criteria,
        funding=dict(card.get("funding") or {}),
        required_documents=list(card.get("required_documents") or []),
        deadline=card.get("deadline"),
        contact=dict(card.get("contact") or {}),
    )
    program.validate()
    return program


def research_programs(
    config: dict[str, Any],
    llm: LLMClient,
    search_backend: SearchBackend,
    out_dir: str | Path = "programs/research",
    levels: list[str] | None = None,
    max_per_level: int = 5,
    profile: dict[str, Any] | None = None,
    fetcher: Callable[[str], str] | None = None,
    page_fetcher: Callable[[str], tuple[str, list[str]]] | None = None,
) -> ResearchReport:
    """Recherchiert pro Verwaltungsebene Foerderprogramme und schreibt Draft-Regeln nach out_dir.

    Drafts landen NICHT automatisch im Matching – ein Mensch reviewed sie und verschiebt sie nach programs/.
    """
    research_cfg = config.get("research") or {}
    levels = [l.lower() for l in (levels or research_cfg.get("levels") or list(LEVELS))]
    for level in levels:
        if level not in LEVELS:
            raise ValueError(f"Unbekannte Ebene {level!r} (erlaubt: {LEVELS})")
    topics = list(research_cfg.get("topics") or ["Digitalisierung", "Investition", "Energieeffizienz", "Forschung"])
    template = str(research_cfg.get("query_template") or DEFAULT_QUERY_TEMPLATE)
    profile = profile or {}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ResearchReport()
    if fetcher is None:
        fetcher = build_fetcher(config)
    link_cfg = research_cfg.get("link_follow") or {}
    max_depth = int(link_cfg.get("max_depth", 1))
    max_links = int(link_cfg.get("max_links_per_page", 5))
    same_host_only = bool(link_cfg.get("same_host_only", True))
    if page_fetcher is None:
        if max_depth > 1:
            page_fetcher = build_page_fetcher(config)
        else:
            page_fetcher = lambda url: (fetcher(url), [])  # type: ignore[assignment]
    visited: set[str] = set()

    def crawl(url: str, depth: int, level: str, topic: str, title: str, counter: list[int]) -> None:
        """Multi-Hop: Seite lesen, Cards extrahieren, dann verlinkte PDFs/Seiten (gleicher Host) bis max_depth."""
        if url in visited or depth > max_depth or counter[0] >= max_per_level:
            return
        visited.add(url)
        try:
            page, links = page_fetcher(url)
            is_pdf = url.lower().split("?")[0].endswith(".pdf")
            if len(page) < 200 and not is_pdf:
                raise ProgramValidationError("Seite zu kurz/leer (ggf. Login oder JS-only)")
            for card in extract_program_cards(llm, page, url):
                if counter[0] >= max_per_level:
                    break
                program = card_to_program(card, level, url)
                slug = re.sub(r"[^a-z0-9_-]+", "-", f"{level}-{program.id}".lower()).strip("-")
                target = out / f"{slug}.json"
                payload = program.to_dict()
                payload["status"] = "draft"
                payload["source_url"] = url
                payload["researched_level"] = level
                payload["crawl_depth"] = depth
                target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                report.drafts.append(target.name)
                counter[0] += 1
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            report.errors.append(f"{level}/{topic} {url}: {reason}")
            report.manual.append({"url": url, "title": title, "level": level, "reason": reason})
            return
        if depth < max_depth:
            host = urllib.parse.urlparse(url).netloc
            for link in links[:max_links]:
                if counter[0] >= max_per_level:
                    break
                if same_host_only and urllib.parse.urlparse(link).netloc != host:
                    continue
                if not link.lower().split("?")[0].endswith((".pdf", ".html", ".htm", "/")):
                    continue
                crawl(link, depth + 1, level, topic, title, counter)

    for level in levels:
        counter = [0]
        for topic in topics:
            query = build_query(template, level, profile, topic)
            try:
                results = search_backend.search(query, max_results=max_per_level)
            except Exception as exc:
                report.errors.append(f"{level}/{topic}: Suche fehlgeschlagen: {type(exc).__name__}: {exc}")
                continue
            for result in results:
                if counter[0] >= max_per_level:
                    break
                crawl(result.url, 1, level, topic, result.title, counter)
        report.per_level[level] = counter[0]
    (out / "research-report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
