from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foerderpilot.agents.base import Agent, AgentContext
from foerderpilot.llm.client import LLMClient

EMAIL_SYSTEM = (
    "Du bist Foerderberater. Du formulierst eine formelle, freundliche deutsche E-Mail an die "
    "zustaendige Stelle eines Foerderprogramms, um Informationsluecken/Unklarheiten vor Antragstellung "
    "zu klaeren. Nur die uebergebenen Daten verwenden, nichts erfinden. Antworte ausschliesslich mit "
    "Markdown der Form:\n\nAn: <email>\nBetreff: <betreff>\n\n<body>"
)


class ClarificationAgent(Agent):
    """Agent: formuliert fuer Matches mit Luecken eine Klaerungs-Mail an die recherchierte Stelle."""

    name = "Clarification"

    def __init__(self, llm: LLMClient, output_dir: str | Path, max_emails: int = 3):
        self.llm = llm
        self.output_dir = Path(output_dir)
        self.max_emails = max_emails

    def _build_prompt(self, match, gaps: list[dict[str, Any]], context: AgentContext) -> str:
        profile = {k: v for k, v in context.profile.items() if not k.startswith("_")}
        return (
            "Formuliere eine Klaerungs-E-Mail zum folgenden Foerderprogramm.\n\n"
            f"PROGRAMM: {json.dumps(match.program.to_dict(), ensure_ascii=False, indent=2)}\n\n"
            f"UNTERNEHMENSPROFIL: {json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
            f"OFFENE LUEKEN/FRAGEN: {json.dumps(gaps, ensure_ascii=False, indent=2)}\n\n"
            "Die E-Mail soll konkret zu jeder Luecke eine Frage stellen (z. B. welche Unterlage akzeptiert wird, "
            "wie ein fehlendes Kennzeichen zu belegen ist)."
        )

    def run(self, context: AgentContext) -> None:
        context.emails = []
        candidates = [
            (m, context.gaps.get(m.program.id, []))
            for m in context.matches
            if m.eligible and context.gaps.get(m.program.id)
        ][: self.max_emails]
        emails_dir = self.output_dir / "emails"
        for match, gaps in candidates:
            contact_email = str(match.program.contact.get("email", ""))
            if not contact_email:
                context.log(self.name, "skip", f"{match.program.id}: kein contact.email – kein Entwurf.")
                continue
            text = self.llm.complete(EMAIL_SYSTEM, self._build_prompt(match, gaps, context), temperature=0.2)
            emails_dir.mkdir(parents=True, exist_ok=True)
            path = emails_dir / f"{match.program.id}.md"
            path.write_text(text.strip() + "\n", encoding="utf-8")
            context.emails.append(
                {
                    "program_id": match.program.id,
                    "to": contact_email,
                    "stelle": match.program.contact.get("stelle", ""),
                    "gaps": len(gaps),
                    "file": str(path),
                }
            )
            context.log(self.name, "draft_email", f"{match.program.id} -> {contact_email} ({path})")
        if not candidates:
            context.log(self.name, "none", "Keine eligible Matches mit Luecken – keine Mail-Entwuerfe.")
