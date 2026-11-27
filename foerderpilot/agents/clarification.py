from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foerderpilot.agents.base import Agent, AgentContext
from foerderpilot.llm.client import LLMClient

EMAIL_SYSTEM = (
    "Du bist Foerderberater. Du formulierst eine formelle, freundliche deutsche E-Mail an die "
    "zustaendige Stelle eines Foerderprogramms, um Informationsluecken/Unklarheiten vor Antragstellung "
    "zu klaeren. Nur die uebergebenen Daten verwenden, nichts erfinden. Wenn contact.stelle gesetzt ist, "
    "beginne mit der Anrede 'Sehr geehrte Damen und Herren von <stelle>,' (sonst: 'Sehr geehrte Damen und Herren,'). "
    "Antworte ausschliesslich mit Markdown der Form:\n\nAn: <email>\nBetreff: <betreff>\n\n<body>"
)

INTERNAL_EMAIL_SYSTEM = (
    "Du formulierst eine freundliche interne deutsche E-Mail an einen Wissensträger (Abteilung) eines "
    "Unternehmens. Ziel: fehlende Datenpunkte/Unterlagen für Förderanträge zusammentragen. Liste die offenen "
    "Punkte konkret auf, nenne wo sie vermutlich liegen (System/Abteilung) und bitte um Bereitstellung oder "
    "Upload in den Data Lake. Nur uebergebene Daten verwenden. Markdown:\n\nAn: <email>\nAbteilung: <abteilung>\n"
    "Betreff: <betreff>\n\n<body>"
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
        from foerderpilot.connectors.factory import _resolve_secret

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
            context.log(self.name, "none", "Keine eligible Matches mit Luecken – keine externen Mail-Entwuerfe.")
        self._write_internal_email(context, _resolve_secret)

    def _write_internal_email(self, context: AgentContext, resolve_secret) -> None:
        """Interne Klärungs-Mail an den Wissensträger (Abteilung) fuer offene Unternehmens-Inputs."""
        cfg = (context.config.get("clarification") or {}).get("internal") or {}
        if not cfg.get("enabled", True):
            return
        try:
            to = resolve_secret(str(cfg.get("email", "")))
        except KeyError:
            to = ""
        if not to:
            context.log(self.name, "internal_skip", "clarification.internal.email nicht gesetzt – keine interne Mail.")
            return
        abteilung = str(cfg.get("abteilung", "Controlling / Fördermanagement"))
        open_fields = sorted(
            {
                g["field"]
                for gaps in context.gaps.values()
                for g in gaps
                if g["type"] == "missing_profile_field" and context.profile.get(g["field"]) in (None, "")
            }
        )
        open_docs = sorted(
            {g["document"] for gaps in context.gaps.values() for g in gaps if g["type"] == "missing_document"}
        )
        no_contact = sorted(
            {pid for pid, gaps in context.gaps.items() for g in gaps if g["type"] == "no_contact"}
        )
        if not (open_fields or open_docs or no_contact):
            context.log(self.name, "internal_none", "Keine offenen Unternehmens-Inputs – keine interne Mail.")
            return
        items = [f"Feld '{f}' (Profil)" for f in open_fields]
        items += [f"Unterlage '{d}'" for d in open_docs]
        items += [f"Ansprechpartner recherchieren für Programm '{p}'" for p in no_contact]
        profile = {k: v for k, v in context.profile.items() if not k.startswith("_")}
        prompt = (
            f"UNTERNEHMENSPROFIL (bisher): {json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
            f"OFFENE PUNKTE ({len(items)}):\n- " + "\n- ".join(items) + "\n\n"
            "Bitte um Bereitstellung der Daten/Unterlagen bzw. Upload in den Data Lake."
        )
        text = self.llm.complete(INTERNAL_EMAIL_SYSTEM, prompt, temperature=0.2)
        emails_dir = self.output_dir / "emails"
        emails_dir.mkdir(parents=True, exist_ok=True)
        path = emails_dir / "internal-wissenstraeger.md"
        path.write_text(text.strip() + "\n", encoding="utf-8")
        context.emails.append(
            {
                "program_id": "internal",
                "type": "internal",
                "to": to,
                "abteilung": abteilung,
                "open_items": len(items),
                "file": str(path),
            }
        )
        context.log(self.name, "draft_internal_email", f"interne Mail an {to} ({abteilung}), {len(items)} offene Punkte -> {path}")
