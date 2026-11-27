import json
from pathlib import Path

import pandas as pd
import pytest

from foerderpilot.config import load_config
from foerderpilot.pipeline import run_pipeline


class FakeLLM:
    def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
        if "Wissensträger" in system or "Wissenstraeger" in system:
            return "An: intern@example.com\nAbteilung: Controlling\nBetreff: Offene Datenpunkte\n\nBitte um Bereitstellung."
        if "zustaendige Stelle" in system:
            return (
                "An: hotline@behoerde.example\nBetreff: Rueckfrage\n\n"
                "Sehr geehrte Damen und Herren von Behoerde – Hotline,\n\nbitte um Klarstellung ..."
            )
        return "# Foerderantrag (Entwurf)\n\nFake."


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNAL_MAIL", "intern@example.com")
    lake = tmp_path / "data_lake"
    lake.mkdir()
    pd.DataFrame([{"firma": "Cov GmbH", "land": "DE", "mitarbeiter": 80}]).to_csv(lake / "stammdaten.csv", index=False)
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "p.json").write_text(
        json.dumps(
            {
                "id": "prog-cov",
                "name": "Coverage-Programm",
                "provider": "Behoerde",
                "criteria": [
                    {"field": "hq_country", "op": "in", "value": ["DE"]},
                    {"field": "investment_amount_eur", "op": ">=", "value": 1000, "required": False, "weight": 3},
                ],
                "required_documents": ["Geheimdokument XYZ"],
                "contact": {"stelle": "Behoerde – Hotline", "email": "hotline@behoerde.example"},
            }
        ),
        encoding="utf-8",
    )
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""
connectors:
  - type: local
    root: {lake}
programs_dir: {programs}
output_dir: {tmp_path / 'out'}
clarification:
  enabled: true
  max_emails: 3
  internal:
    enabled: true
    email: env:INTERNAL_MAIL
    abteilung: Controlling
""",
        encoding="utf-8",
    )
    return cfg


def test_coverage_report_and_dual_emails(project):
    config = load_config(project)
    result = run_pipeline(config, llm_client=FakeLLM())
    out = Path(config["output_dir"])

    coverage = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["profile_fields"]["investment_amount_eur"]["status"] == "open"
    assert coverage["profile_fields"]["hq_country"]["status"] == "ok"
    assert coverage["programs"]["prog-cov"]["contact"]["status"] == "ok"
    assert coverage["programs"]["prog-cov"]["contact"]["stelle"] == "Behoerde – Hotline"
    assert coverage["programs"]["prog-cov"]["required_documents"][0]["status"] == "offen"
    assert "investment_amount_eur" in coverage["summary"]["open_fields"]
    assert coverage["summary"]["programs_without_contact"] == []

    emails = json.loads((out / "emails.json").read_text(encoding="utf-8"))
    ext = [e for e in emails if e.get("type") != "internal"]
    internal = [e for e in emails if e.get("type") == "internal"]
    assert ext and ext[0]["to"] == "hotline@behoerde.example"
    assert internal and internal[0]["to"] == "intern@example.com"
    assert internal[0]["abteilung"] == "Controlling"
    assert internal[0]["open_items"] >= 2  # Feld + Unterlage

    ext_text = (out / "emails" / "prog-cov.md").read_text(encoding="utf-8")
    assert "Sehr geehrte Damen und Herren von" in ext_text  # Stelle in der Anrede
    int_text = (out / "emails" / "internal-wissenstraeger.md").read_text(encoding="utf-8")
    assert "An: intern@example.com" in int_text
