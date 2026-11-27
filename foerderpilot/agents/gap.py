from __future__ import annotations

import re
from typing import Any

from foerderpilot.agents.base import Agent, AgentContext


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def compute_gaps(match, profile: dict[str, Any], catalog) -> list[dict[str, Any]]:
    """Informationsluecken pro Programm: fehlende/fehlgeschlagene Profil-Felder,
    nicht auffindbare Pflicht-Unterlagen im Lake, fehlender Ansprechpartner."""
    gaps: list[dict[str, Any]] = []
    for result in list(match.passed) + list(match.failed):
        crit = result.criterion
        if result.actual is None or str(result.actual) == "":
            gaps.append(
                {
                    "type": "missing_profile_field",
                    "field": crit.field,
                    "expected": f"{crit.op} {crit.value!r}",
                    "required": crit.required,
                    "hint": "Feld fehlt im Data Lake – in profile_overrides nachtragen oder Dataset ergaenzen.",
                }
            )
        elif not result.passed and crit.required:
            gaps.append(
                {
                    "type": "failed_required_criterion",
                    "field": crit.field,
                    "expected": f"{crit.op} {crit.value!r}",
                    "actual": result.actual,
                    "hint": "Ist-Wert im Lake erfuellt das Kriterium nicht.",
                }
            )
    dataset_names = " ".join(_norm(d.ref.name) for d in catalog.datasets) if catalog else ""
    for doc in match.program.required_documents:
        keyword = _norm(doc).split("_")[0]
        if keyword and len(keyword) > 3 and keyword not in dataset_names:
            gaps.append(
                {
                    "type": "missing_document",
                    "document": doc,
                    "hint": "Keine Datei im Data Lake deutet auf diese Unterlage hin.",
                }
            )
    contact_email = str(match.program.contact.get("email", ""))
    if not contact_email:
        gaps.append(
            {
                "type": "no_contact",
                "hint": "Kein Ansprechpartner (contact.email) recherchiert – Klärungs-Mail nicht moeglich.",
            }
        )
    return gaps


class GapAnalysisAgent(Agent):
    """Agent nach dem Matcher: identifiziert Informationsluecken pro Match."""

    name = "GapAnalysis"

    def run(self, context: AgentContext) -> None:
        gaps: dict[str, list[dict[str, Any]]] = {}
        for match in context.matches:
            found = compute_gaps(match, context.profile, context.catalog)
            if found:
                gaps[match.program.id] = found
        context.gaps = gaps
        n_prog = len(gaps)
        n_gaps = sum(len(v) for v in gaps.values())
        context.log(self.name, "analyze", f"{n_gaps} Luecken bei {n_prog} Programmen.")
