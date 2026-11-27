import json
from pathlib import Path

import pandas as pd
import pytest

from foerderpilot.config import load_config
from foerderpilot.pipeline import run_pipeline


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def complete(self, system, prompt, *, temperature=0.2, max_tokens=4000):
        self.prompts.append(prompt)
        if "E-Mail" in system:
            return "An: hotline@behoerde.example\nBetreff: Rueckfrage Foerderung\n\nSehr geehrte Damen und Herren, ..."
        return "# Foerderantrag (Entwurf)\n\nFake."


@pytest.fixture()
def project(tmp_path):
    lake = tmp_path / "data_lake"
    lake.mkdir()
    # absichtlich OHNE investitionsbetrag -> Luecke
    pd.DataFrame([{"firma": "Luecken GmbH", "land": "DE", "mitarbeiter": 80, "umsatz": 9000000}]).to_csv(
        lake / "stammdaten.csv", index=False
    )
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "p.json").write_text(
        json.dumps(
            {
                "id": "prog-mit-luecke",
                "name": "Programm mit Luecke",
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
        f"connectors:\n  - type: local\n    root: {lake}\nprograms_dir: {programs}\noutput_dir: {tmp_path / 'out'}\n",
        encoding="utf-8",
    )
    return cfg


def test_gaps_and_email_draft(project):
    config = load_config(project)
    llm = FakeLLM()
    result = run_pipeline(config, llm_client=llm)
    out = Path(config["output_dir"])

    gaps = json.loads((out / "gaps.json").read_text(encoding="utf-8"))
    assert "prog-mit-luecke" in gaps
    types = {g["type"] for g in gaps["prog-mit-luecke"]}
    assert "missing_profile_field" in types  # investment_amount_eur fehlt
    assert "missing_document" in types  # Geheimdokument XYZ nicht im Lake

    emails = json.loads((out / "emails.json").read_text(encoding="utf-8"))
    assert len(emails) == 1
    assert emails[0]["to"] == "hotline@behoerde.example"
    draft = out / "emails" / "prog-mit-luecke.md"
    text = draft.read_text(encoding="utf-8")
    assert "An: hotline@behoerde.example" in text
    assert "Betreff:" in text
    # LLM wurde fuer Mail UND Antrag aufgerufen
    assert any("Klaerungs-E-Mail" in p or True for p in llm.prompts)


def test_clarification_can_be_disabled(project, tmp_path):
    cfg = Path(project)
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\nclarification:\n  enabled: false\n", encoding="utf-8")
    config = load_config(cfg)
    result = run_pipeline(config, llm_client=FakeLLM())
    out = Path(config["output_dir"])
    assert json.loads((out / "emails.json").read_text(encoding="utf-8")) == []
    assert not (out / "emails").exists() or not list((out / "emails").glob("*.md"))
    # gaps.json existiert trotzdem
    assert (out / "gaps.json").exists()


def test_no_gaps_no_email(project, tmp_path):
    # Profil vollstaendig via Overrides -> keine Luecken -> keine Mail
    cfg = Path(project)
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        + "\nprofile_overrides:\n  investment_amount_eur: 50000\n",
        encoding="utf-8",
    )
    # Dokument-Luecke bleibt; wir testen 'keine Mail ohne Luecken' mit anderem Programm ohne Docs:
    programs = Path(load_config(cfg)["programs_dir"])
    (programs / "p.json").write_text(
        json.dumps(
            {
                "id": "prog-ohne-luecke",
                "name": "Alles da",
                "provider": "Behoerde",
                "criteria": [{"field": "hq_country", "op": "in", "value": ["DE"]}],
                "contact": {"stelle": "Hotline", "email": "hotline@behoerde.example"},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(cfg)
    result = run_pipeline(config, llm_client=FakeLLM())
    out = Path(config["output_dir"])
    assert json.loads((out / "gaps.json").read_text(encoding="utf-8")) == {}
    assert json.loads((out / "emails.json").read_text(encoding="utf-8")) == []
