from __future__ import annotations

from typing import Any

from foerderpilot.agents.base import Agent, AgentContext


class Orchestrator:
    """Fuehrt die Agenten sequenziell ueber einen geteilten Kontext aus
    und zeichnet jeden Schritt als Audit-Trace auf."""

    def __init__(self, agents: list[Agent]):
        if not agents:
            raise ValueError("Orchestrator braucht mindestens einen Agenten.")
        self.agents = agents

    def run(self, context: AgentContext) -> AgentContext:
        context.log("Orchestrator", "start", f"Pipeline mit {len(self.agents)} Agenten: {[a.name for a in self.agents]}")
        for agent in self.agents:
            context.log("Orchestrator", "agent_start", agent.name)
            agent.run(context)
            context.log("Orchestrator", "agent_done", agent.name)
        context.log("Orchestrator", "done", "Pipeline abgeschlossen.")
        return context

    def trace(self, context: AgentContext) -> list[dict[str, Any]]:
        return [e.to_dict() for e in context.events]
