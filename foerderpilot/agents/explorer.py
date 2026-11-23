from __future__ import annotations

from foerderpilot.agents.base import Agent, AgentContext
from foerderpilot.catalog import DataCatalog
from foerderpilot.connectors.factory import build_connectors
from foerderpilot.profile import extract_profile


class DataLakeExplorerAgent(Agent):
    """Agent 1: erkundet alle konfigurierten Data Lakes, baut den Katalog
    und destilliert daraus das Unternehmensprofil."""

    name = "DataLakeExplorer"

    def run(self, context: AgentContext) -> None:
        cfg = context.config
        connectors = build_connectors(cfg.get("connectors", []))
        context.log(self.name, "connect", f"{len(connectors)} Connector konfiguriert: {[c.name for c in connectors]}")

        catalog = DataCatalog(sample_rows=int(cfg.get("sample_rows", 5))).build(connectors)
        context.catalog = catalog
        context.log(
            self.name,
            "catalog",
            f"{len(catalog.datasets)} Datasets gefunden: "
            + ", ".join(f"{d.ref.connector}:{d.ref.name}" for d in catalog.datasets),
        )

        profile = extract_profile(catalog, overrides=cfg.get("profile_overrides") or {})
        if cfg.get("profile_file"):
            from foerderpilot.config import load_profile_file

            profile.update(load_profile_file(cfg["profile_file"]))
        context.profile = profile
        context.log(
            self.name,
            "profile",
            f"Unternehmensprofil mit {len([k for k in profile if not k.startswith('_')])} Feldern extrahiert "
            f"(Quellen: {', '.join(profile.get('_sources', [])) or 'keine'})",
        )
