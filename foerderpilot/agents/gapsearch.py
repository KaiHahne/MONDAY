from __future__ import annotations

import re
from typing import Any

from foerderpilot.agents.base import Agent, AgentContext
from foerderpilot.profile import FIELD_ALIASES, _to_number


def _terms_for_field(field: str, max_terms: int = 3) -> list[str]:
    terms = [field] + list(FIELD_ALIASES.get(field, []))
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:max_terms]


def extract_value(field: str, text: str) -> Any:
    """Heuristik: 'investitionsbetrag: 150000 EUR' o. ae. im Treffer-Text -> Wert fuers Profil."""
    aliases = [re.escape(a) for a in _terms_for_field(field, max_terms=6)]
    pattern = re.compile(
        r"(?i)(?:" + "|".join(aliases) + r")\s*[:=]\s*([0-9][0-9.,]*\s*(?:eur|€)?|[A-ZÄÖÜ][\wÄÖÜäöüß.\- ]{2,60})"
    )
    match = pattern.search(text or "")
    if not match:
        return None
    raw = match.group(1).strip().rstrip(".")
    num = _to_number(raw)
    return num if num is not None else raw


class GapSearchAgent(Agent):
    """Agent: durchsucht die proprietären Quellen (REST-Connectoren mit search()) gezielt
    nach den Lücken aus der Gap-Analyse und fuellt das Profil, wo ein Treffer einen Wert liefert."""

    name = "GapSearch"

    def __init__(self, max_hits_per_query: int = 5, max_terms_per_gap: int = 3):
        self.max_hits_per_query = max_hits_per_query
        self.max_terms_per_gap = max_terms_per_gap

    def run(self, context: AgentContext) -> None:
        sources = [c for c in context.connectors if hasattr(c, "search")]
        context.evidence = {}
        filled = 0
        if not sources:
            context.log(self.name, "skip", "keine REST-Quellen mit search() konfiguriert.")
            return
        for program_id, gaps in context.gaps.items():
            evidence: list[dict[str, Any]] = []
            for gap in gaps:
                gtype = gap.get("type")
                if gtype in ("missing_profile_field", "failed_required_criterion"):
                    field = gap["field"]
                    for term in _terms_for_field(field, self.max_terms_per_gap):
                        for src in sources:
                            try:
                                hits = src.search(term, self.max_hits_per_query)
                            except Exception as exc:
                                context.log(self.name, "search_error", f"{src.name} '{term}': {type(exc).__name__}: {exc}")
                                continue
                            for hit in hits:
                                evidence.append(
                                    {"source": src.name, "gap_type": gtype, "field": field, "query": term, "hit": hit}
                                )
                                if context.profile.get(field) in (None, ""):
                                    value = extract_value(field, f"{hit.get('title', '')} {hit.get('snippet', '')}")
                                    if value is not None:
                                        context.profile[field] = value
                                        context.profile.setdefault("_evidence_sources", {})[field] = f"{src.name}: {hit.get('url', hit.get('id', ''))}"
                                        filled += 1
                elif gtype == "missing_document":
                    doc = gap.get("document", "")
                    term = doc.split()[0] if doc else ""
                    if not term:
                        continue
                    for src in sources:
                        try:
                            hits = src.search(term, self.max_hits_per_query)
                        except Exception as exc:
                            context.log(self.name, "search_error", f"{src.name} '{term}': {type(exc).__name__}: {exc}")
                            continue
                        for hit in hits:
                            evidence.append(
                                {"source": src.name, "gap_type": gtype, "document": doc, "query": term, "hit": hit}
                            )
            if evidence:
                context.evidence[program_id] = evidence
        context.profile_changed = filled > 0
        n_hits = sum(len(v) for v in context.evidence.values())
        context.log(
            self.name,
            "search",
            f"{n_hits} Treffer in {len(sources)} Quellen; {filled} Profil-Felder nachgefuellt.",
        )
