from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foerderpilot.agents.base import Agent, AgentContext
from foerderpilot.llm.client import LLMClient, LLMError

SYSTEM_PROMPT = (
    "Du bist ein erfahrener Foerderberater. Du erstellst praezise, formelle Antragsfassungen "
    "fuer deutsche Foerderprogramme auf Deutsch. Du nutzt ausschliesslich die uebergebenen "
    "Unternehmensdaten und Programmregeln, erfindest keine Zahlen und kennzeichnest fehlende "
    "Angaben mit '[TODO: ...]'."
)

APPLICATION_TEMPLATE = """# Antrag auf Foerderung: {name}

- Programm-ID: {id}
- Zuwendungsgeber: {provider}
- Programm-URL: {url}
- Frist: {deadline}

## 1. Antragsteller
{applicant}

## 2. Vorhaben
{project}

## 3. Begruendung der Foerderfaehigkeit
{eligibility}

## 4. Beantragte Foerderung
{funding}

## 5. Anlagen
{documents}
"""


class ApplicationWriterAgent(Agent):
    """Agent 3: erstellt fuer die besten eligible Matches per LLM fertige
    Antragsentwuerfe (Markdown) im Ausgabeverzeichnis."""

    name = "ApplicationWriter"

    def __init__(self, llm: LLMClient, output_dir: str | Path, max_applications: int = 5, max_program_chars: int = 4000):
        self.llm = llm
        self.output_dir = Path(output_dir)
        self.max_applications = max_applications
        self.max_program_chars = max_program_chars

    def _build_prompt(self, match, context: AgentContext) -> str:
        profile = {k: v for k, v in context.profile.items() if not k.startswith("_")}
        relevant = [
            d.to_dict()
            for d in context.catalog.datasets
            if any(h in d.ref.name.lower() for h in ("stammdaten", "firma", "company", "kennzahl", "kpi", "profil"))
        ][:3]
        return (
            "Erstelle einen Foerderantrag (Markdown) gemaess Vorlage. "
            "Nutze dafuer ausschliesslich folgende Daten.\n\n"
            f"PROGRAMM (JSON):\n{json.dumps(match.program.to_dict(), ensure_ascii=False, indent=2)[: self.max_program_chars]}\n\n"
            f"UNTERNEHMENSPROFIL (JSON):\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
            f"ERFUELlte KRITERIEN: {json.dumps([r.criterion.field for r in match.passed], ensure_ascii=False)}\n\n"
            f"RELEVANTE DATASETS AUS DEM DATA LAKE:\n{json.dumps(relevant, ensure_ascii=False, indent=2)}\n\n"
            "Antworte ausschliesslich mit dem vollstaendigen Markdown-Antrag."
        )

    def run(self, context: AgentContext) -> None:
        if not hasattr(self.llm, "complete"):
            raise LLMError("ApplicationWriterAgent benoetigt einen LLMClient mit complete().")
        eligible = [m for m in context.matches if m.eligible][: self.max_applications]
        context.log(self.name, "select", f"{len(eligible)} Antraege werden erstellt.")

        apps_dir = self.output_dir / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        for match in eligible:
            prompt = self._build_prompt(match, context)
            text = self.llm.complete(SYSTEM_PROMPT, prompt)
            path = apps_dir / f"{match.program.id}.md"
            path.write_text(text.strip() + "\n", encoding="utf-8")
            context.applications.append(
                {
                    "program_id": match.program.id,
                    "program_name": match.program.name,
                    "provider": match.program.provider,
                    "score": match.score,
                    "file": str(path),
                }
            )
            context.log(self.name, "write_application", f"{match.program.id} -> {path}")
