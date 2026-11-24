import json
from pathlib import Path

import pytest

from foerderpilot.cli import main
from foerderpilot.programs.importer import (
    ImportReport,
    import_programs,
    parse_criterion,
    row_to_program,
)
from foerderpilot.programs.loader import load_programs

CSV = """id,titel,zuwendungsgeber,foerderart,max_foerdersatz,max_förderbetrag,frist,kriterien,erforderliche_unterlagen
"DEMO-1","Demo Digital","Beispiel-Behoerde",Zuschuss,0.5,100000,,"hq_country in [DE, AT]; employees<=250 | weight=2; purpose contains digital | required=false","Projektbeschreibung; Kostenplan"
"DEMO-2","Demo Energie","Beispiel-Amt",Zuschuss,80%,6000,31.12.2026,"hq_country in [DE]; employees<250","Antragsformular"
"""


def test_parse_criterion_variants():
    c = parse_criterion("employees<=250 | weight=2")
    assert (c.field, c.op, c.value, c.weight, c.required) == ("employees", "<=", 250, 2.0, True)
    c = parse_criterion('hq_country in ["DE","AT"]')
    assert c.value == ["DE", "AT"] and c.op == "in"
    c = parse_criterion("hq_country in [DE, AT]")
    assert c.value == ["DE", "AT"]
    c = parse_criterion("purpose contains digital | required=false | weight=3")
    assert c.op == "contains" and c.required is False and c.weight == 3.0
    c = parse_criterion("purpose exists")
    assert c.op == "exists" and c.value is None
    with pytest.raises(ValueError):
        parse_criterion("kein operator hier")
    with pytest.raises(ValueError):
        parse_criterion("employees ~~ 5")


def test_row_to_program_funding_and_lists():
    program = row_to_program(
        {
            "id": "DEMO X",
            "titel": "Demo",
            "foerderart": "Zuschuss",
            "foerdersatz": "80%",
            "max_förderbetrag": "6000",
            "laender": "DE, AT",
            "anlagen": "A; B",
            "kriterien": "hq_country in [DE]",
        }
    )
    assert program.id == "demo-x"
    assert program.funding == {"type": "Zuschuss", "max_rate": 0.8, "max_amount_eur": 6000}
    assert program.region == ["DE", "AT"]
    assert program.required_documents == ["A", "B"]
    assert program.criteria[0].field == "hq_country"


def test_import_csv_roundtrip(tmp_path):
    src = tmp_path / "export.csv"
    src.write_text(CSV, encoding="utf-8")
    out = tmp_path / "programs"
    report = import_programs(src, out)
    assert report.errors == []
    assert sorted(report.written) == ["demo-1", "demo-2"]
    programs = {p.id: p for p in load_programs(out)}
    assert programs["demo-1"].funding["max_rate"] == 0.5
    assert programs["demo-2"].funding["max_rate"] == 0.8
    assert programs["demo-2"].deadline == "31.12.2026"
    crit = programs["demo-1"].criteria
    assert any(c.field == "employees" and c.op == "<=" and c.value == 250 and c.weight == 2 for c in crit)
    assert any(c.field == "purpose" and c.required is False for c in crit)
    assert programs["demo-1"].required_documents == ["Projektbeschreibung", "Kostenplan"]


def test_import_json_and_duplicates_and_dry_run(tmp_path):
    src = tmp_path / "export.json"
    src.write_text(
        json.dumps({"records": [{"id": "J-1", "name": "Json-Programm", "criteria": "hq_country in [DE]"}]}),
        encoding="utf-8",
    )
    out = tmp_path / "programs"
    r1 = import_programs(src, out)
    assert r1.written == ["j-1"] and r1.errors == []
    r2 = import_programs(src, out)
    assert r2.skipped == ["j-1"] and r2.written == []
    r3 = import_programs(src, out, force=True)
    assert r3.written == ["j-1"]
    out2 = tmp_path / "dry"
    r4 = import_programs(src, out2, dry_run=True)
    assert r4.dry_run and r4.written == ["j-1"] and not out2.exists()


def test_import_collects_row_errors(tmp_path):
    src = tmp_path / "bad.csv"
    src.write_text(
        "id,titel,kriterien\n"
        "OK-1,Gutes Programm,\"hq_country in [DE]\"\n"
        "BAD-1,Falsches Programm,\"employees ~~ 5\"\n"
        ",Ohne ID,\"hq_country in [DE]\"\n",
        encoding="utf-8",
    )
    out = tmp_path / "programs"
    report = import_programs(src, out)
    assert report.written == ["ok-1"]
    assert len(report.errors) == 2
    assert any("Zeile 3" in e for e in report.errors)
    assert any("Zeile 4" in e for e in report.errors)


def test_cli_import_programs(tmp_path, capsys):
    src = tmp_path / "export.csv"
    src.write_text(CSV, encoding="utf-8")
    out = tmp_path / "programs"
    rc = main(["import-programs", "--input", str(src), "--out", str(out)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert sorted(payload["written"]) == ["demo-1", "demo-2"]
    assert len(list(out.glob("*.json"))) == 2


def test_example_export_imports(tmp_path):
    repo = Path(__file__).resolve().parent.parent
    out = tmp_path / "programs"
    report = import_programs(repo / "examples" / "foerderdatenbank_export.csv", out)
    assert report.errors == [], report.errors
    assert sorted(report.written) == ["demo-1", "demo-2"]
    programs = {p.id: p for p in load_programs(out)}
    assert programs["demo-1"].funding == {"type": "Zuschuss", "max_rate": 0.5, "max_amount_eur": 100000}
    assert programs["demo-2"].funding["max_rate"] == 0.8
