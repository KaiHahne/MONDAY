from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foerderpilot.agents import (
    AgentContext,
    ApplicationWriterAgent,
    ClarificationAgent,
    CoverageAgent,
    DataLakeExplorerAgent,
    GapAnalysisAgent,
    GapSearchAgent,
    ProgramMatcherAgent,
)
from foerderpilot.llm.client import LLMClient, OpenAICompatibleClient
from foerderpilot.orchestrator import Orchestrator


class PipelineResult:
    def __init__(self, context: AgentContext, output_dir: Path):
        self.context = context
        self.output_dir = output_dir

    def to_dict(self) -> dict[str, Any]:
        ctx = self.context
        return {
            "datasets": ctx.catalog.to_dict() if ctx.catalog else {},
            "profile": ctx.profile,
            "matches": [m.to_dict() for m in ctx.matches],
            "applications": ctx.applications,
            "trace": [e.to_dict() for e in ctx.events],
        }


def run_pipeline(config: dict[str, Any], llm_client: LLMClient | None = None) -> PipelineResult:
    """Komplette Multi-Agent-Pipeline: Data Lakes erkunden -> Programme matchen -> Antraege schreiben.

    llm_client=None verwendet OpenAICompatibleClient.from_env() (Key nur aus Umgebung).
    """
    output_dir = Path(config.get("output_dir", "out"))
    output_dir.mkdir(parents=True, exist_ok=True)

    if llm_client is None:
        llm_client = OpenAICompatibleClient.from_env()

    clarification_cfg = config.get("clarification") or {}
    context = AgentContext(config)

    # Phase 1: Lake erkunden, matchen, Luecken finden
    Orchestrator([DataLakeExplorerAgent(), ProgramMatcherAgent(), GapAnalysisAgent()]).run(context)
    # Phase 2: Luecken agentisch in proprietären Quellen suchen; Profil ggf. nachfuellen
    Orchestrator([GapSearchAgent()]).run(context)
    # Phase 3: bei nachgefuelltem Profil neu matchen und Luecken aktualisieren
    if context.profile_changed:
        Orchestrator([ProgramMatcherAgent(), GapAnalysisAgent()]).run(context)
    # Phase 4: Klaerungs-Mails + Antraege
    final_agents: list = []
    if clarification_cfg.get("enabled", True):
        final_agents.append(
            ClarificationAgent(
                llm=llm_client,
                output_dir=output_dir,
                max_emails=int(clarification_cfg.get("max_emails", 3)),
            )
        )
    final_agents.append(
        ApplicationWriterAgent(
            llm=llm_client,
            output_dir=output_dir,
            max_applications=int(config.get("max_applications", 5)),
        )
    )
    final_agents.append(CoverageAgent())
    Orchestrator(final_agents).run(context)

    (output_dir / "catalog.json").write_text(
        json.dumps(context.catalog.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "profile.json").write_text(
        json.dumps(context.profile, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "matches.json").write_text(
        json.dumps([m.to_dict() for m in context.matches], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / "applications.json").write_text(
        json.dumps(context.applications, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "gaps.json").write_text(
        json.dumps(context.gaps, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "gap_evidence.json").write_text(
        json.dumps(context.evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "coverage.json").write_text(
        json.dumps(context.coverage, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "emails.json").write_text(
        json.dumps(context.emails, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "trace.json").write_text(
        json.dumps([e.to_dict() for e in context.events], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return PipelineResult(context, output_dir)
