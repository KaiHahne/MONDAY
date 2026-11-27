from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    agent: str
    action: str
    detail: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "action": self.action,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


class AgentContext:
    """Geteilter Arbeitskontext, den die Agenten sequenziell befuellen."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.catalog: Any = None
        self.profile: dict[str, Any] = {}
        self.programs: list[Any] = []
        self.matches: list[Any] = []
        self.gaps: dict[str, list[dict[str, Any]]] = {}
        self.applications: list[dict[str, Any]] = []
        self.emails: list[dict[str, Any]] = []
        self.events: list[AgentEvent] = []

    def log(self, agent: str, action: str, detail: str) -> None:
        self.events.append(AgentEvent(agent=agent, action=action, detail=detail))


class Agent(ABC):
    name: str = "agent"

    @abstractmethod
    def run(self, context: AgentContext) -> None:
        ...
