from __future__ import annotations

import time
from typing import Any

from foerderpilot.agents.base import Agent, AgentContext
from foerderpilot.agents.gap import _norm


class CoverageAgent(Agent):
    """Vorletzter Agent: schreibt den Coverage-Report – welche Inputs (programmseitig wie
    unternehmensseitig) sind identifiziert, welche fehlen noch ('open')."""

    name = "Coverage"

    def run(self, context: AgentContext) -> None:
        overrides = set((context.config.get("profile_overrides") or {}).keys())
        evidence_sources = context.profile.get("_evidence_sources") or {}

        referenced: dict[str, set[str]] = {}
        for program in context.programs:
            for crit in program.criteria:
                referenced.setdefault(crit.field, set()).add(program.id)

        profile_fields: dict[str, Any] = {}
        for field, refs in sorted(referenced.items()):
            value = context.profile.get(field)
            if value not in (None, ""):
                status = "override" if field in overrides else "ok"
                source = "profile_overrides" if field in overrides else evidence_sources.get(field, "data_lake")
                profile_fields[field] = {
                    "status": status,
                    "source": source,
                    "value": value,
                    "referenced_by": sorted(refs),
                }
            else:
                profile_fields[field] = {"status": "open", "referenced_by": sorted(refs)}

        dataset_names = " ".join(_norm(d.ref.name) for d in context.catalog.datasets) if context.catalog else ""
        match_by_id = {m.program.id: m for m in context.matches}
        programs_cov: dict[str, Any] = {}
        for program in context.programs:
            match = match_by_id.get(program.id)
            criteria = []
            if match:
                for r in list(match.passed) + list(match.failed):
                    if r.passed:
                        status = "erfuellt"
                    elif r.actual in (None, ""):
                        status = "fehlt"
                    else:
                        status = "nicht_erfuellt"
                    criteria.append(
                        {
                            "field": r.criterion.field,
                            "op": r.criterion.op,
                            "value": r.criterion.value,
                            "required": r.criterion.required,
                            "status": status,
                            "actual": r.actual,
                        }
                    )
            docs = []
            for doc in program.required_documents:
                keyword = _norm(doc).split("_")[0]
                found = bool(keyword) and len(keyword) > 3 and keyword in dataset_names
                docs.append({"document": doc, "status": "gefunden" if found else "offen"})
            email = str(program.contact.get("email", ""))
            programs_cov[program.id] = {
                "eligible": match.eligible if match else None,
                "score": match.score if match else None,
                "criteria": criteria,
                "required_documents": docs,
                "contact": {
                    "stelle": program.contact.get("stelle", ""),
                    "email": email or None,
                    "status": "ok" if email else "offen",
                },
            }

        open_fields = [f for f, v in profile_fields.items() if v["status"] == "open"]
        open_docs = [
            {"program": pid, "document": d["document"]}
            for pid, cov in programs_cov.items()
            for d in cov["required_documents"]
            if d["status"] == "offen"
        ]
        no_contact = [pid for pid, cov in programs_cov.items() if cov["contact"]["status"] == "offen"]
        coverage = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "profile_fields": profile_fields,
            "programs": programs_cov,
            "summary": {
                "open_fields": open_fields,
                "open_documents": open_docs,
                "programs_without_contact": no_contact,
                "programs_eligible": sum(1 for m in context.matches if m.eligible),
                "programs_total": len(context.matches),
            },
        }
        context.coverage = coverage
        context.log(
            self.name,
            "coverage",
            f"offene Felder: {len(open_fields)}, offene Unterlagen: {len(open_docs)}, "
            f"Programme ohne Kontakt: {len(no_contact)}",
        )
