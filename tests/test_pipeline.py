import json
from pathlib import Path

import pandas as pd
import pytest

from foerderpilot.config import load_config
from foerderpilot.pipeline import run_pipeline


class FakeLLMClient:
    def __init__(self):
        self.calls = []

    def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
        self.calls.append((system, prompt))
        return "# Foerderantrag (Entwurf)\n\nProgramm aus dem Prompt.\n"


@pytest.fixture()
def project(tmp_path):
    lake = tmp_path / "data_lake"
    lake.mkdir()
    pd.DataFrame(
        [
            {
                "firma": "Digital GmbH",
                "land": "DE",
                "bundesland": "BE",
                "branche": "Software",
                "mitarbeiter": 80,
                "umsatz": 9000000,
            }
        ]
    ).to_csv(lake / "stammdaten.csv", index=False)
    (lake / "kennzahlen.json").write_text(
        json.dumps(
            [
                {"kennzahl": "investitionsbetrag", "wert": 150000},
                {"kennzahl": "vorhaben", "wert": "Digitalisierung der Produktion"},
            ]
        ),
        encoding="utf-8",
    )
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "digital.json").write_text(
        json.dumps(
            {
                "id": "prog-digital",
                "name": "Digitalisierungszuschuss",
                "provider": "Testbehoerde",
                "criteria": [
                    {"field": "hq_country", "op": "in", "value": ["DE"], "required": True, "weight": 2},
                    {"field": "employees", "op": "<=", "value": 250, "required": True, "weight": 1},
                    {"field": "investment_amount_eur", "op": ">=", "value": 10000, "required": True, "weight": 3},
                    {"field": "purpose", "op": "contains", "value": "digital", "required": False, "weight": 2},
                ],
                "funding": {"type": "grant", "max_rate": 0.4},
                "required_documents": ["Projektbeschreibung"],
            }
        ),
        encoding="utf-8",
    )
    (programs / "zu-gross.json").write_text(
        json.dumps(
            {
                "id": "prog-grosskonzern",
                "name": "Nur fuer Grosskonzerne",
                "provider": "Testbehoerde",
                "criteria": [{"field": "employees", "op": ">", "value": 1000, "required": True}],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
connectors:
  - type: local
    name: lake_lokal
    root: {lake}
programs_dir: {programs}
output_dir: {tmp_path / "out"}
max_applications: 5
""",
        encoding="utf-8",
    )
    return tmp_path, config_path


def test_pipeline_end_to_end(project):
    tmp_path, config_path = project
    config = load_config(config_path)
    llm = FakeLLMClient()
    result = run_pipeline(config, llm_client=llm)

    out = Path(config["output_dir"])
    for name in ("catalog.json", "profile.json", "matches.json", "applications.json", "trace.json"):
        assert (out / name).exists(), name

    profile = json.loads((out / "profile.json").read_text(encoding="utf-8"))
    assert profile["company_name"] == "Digital GmbH"
    assert profile["investment_amount_eur"] == 150000

    matches = json.loads((out / "matches.json").read_text(encoding="utf-8"))
    by_id = {m["program"]["id"]: m for m in matches}
    assert by_id["prog-digital"]["eligible"] is True
    assert by_id["prog-digital"]["score"] == 2 + 1 + 3 + 2
    assert by_id["prog-grosskonzern"]["eligible"] is False
    assert matches[0]["program"]["id"] == "prog-digital"

    assert len(llm.calls) == 1
    app_file = out / "applications" / "prog-digital.md"
    assert app_file.exists()
    assert "Foerderantrag" in app_file.read_text(encoding="utf-8")

    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    agents = [e["agent"] for e in trace]
    assert "DataLakeExplorer" in agents and "ProgramMatcher" in agents and "ApplicationWriter" in agents
