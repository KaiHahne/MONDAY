from __future__ import annotations

from foerderpilot.agents.base import Agent, AgentContext
from foerderpilot.programs.loader import load_programs
from foerderpilot.programs.matcher import rank_matches


class ProgramMatcherAgent(Agent):
    """Agent 2: laedt die Foerderprogramm-Regeln und matcht sie gegen das
    Unternehmensprofil (Eligibility + Score, absteigend gerankt)."""

    name = "ProgramMatcher"

    def run(self, context: AgentContext) -> None:
        programs = load_programs(context.config["programs_dir"])
        context.programs = programs
        context.log(self.name, "load_programs", f"{len(programs)} Foerderprogramme geladen.")

        matches = rank_matches(context.profile, programs)
        context.matches = matches
        eligible = [m for m in matches if m.eligible]
        context.log(
            self.name,
            "match",
            f"{len(eligible)}/{len(matches)} Programme eligible; Top: "
            + (", ".join(f"{m.program.id} (Score {m.score:g})" for m in eligible[:5]) or "-"),
        )
