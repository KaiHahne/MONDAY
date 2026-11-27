import pytest

from foerderpilot.cli import main
from foerderpilot.sap import (
    format_recipe,
    intake_dir_from_config,
    load_runbook,
    match_recipe,
    run_interactive,
    run_once,
)


def test_runbook_loads():
    recipes = load_runbook()
    assert len(recipes) >= 5
    domains = {r.domain for r in recipes}
    assert {"co", "bw", "general"} <= domains
    for r in recipes:
        assert r.steps and all(s.menu for s in r.steps)


def test_match_co_goal():
    recipe, alts = match_recipe("Kosten je Kostenstelle Ist 2025", domain="co")
    assert recipe.id == "co-kostenstellen-ist"
    assert any("SE16N" in s.tcode for s in recipe.steps)
    assert alts  # Alternativen werden angeboten


def test_match_bw_goal():
    recipe, _ = match_recipe("BW Query Ergebnis exportieren", domain="bw")
    assert recipe.id == "bw-query-export"


def test_unknown_goal_falls_back_to_general():
    recipe, _ = match_recipe("irgendwas komisches xyz", domain=None)
    assert recipe.domain == "general"


def test_format_recipe_contains_export_and_drop(tmp_path):
    recipe, _ = match_recipe("Kosten je Kostenstelle Ist 2025", domain="co")
    text = format_recipe(recipe, drop_dir=str(tmp_path / "sap_exports"))
    assert "TCode" in text and "Export" in text
    assert "sap_exports" in text
    assert "XLSX" in text or "xlsx" in text


def test_run_once_batch(capsys):
    lines = []
    recipe = run_once("Kosten je Kostenstelle Ist 2025", "co", "sap_exports", out=lines.append)
    assert recipe.id == "co-kostenstellen-ist"
    out = "\n".join(lines)
    assert "Schritt 1/" in out and "S_ALR_87013611" in out


def test_interactive_repl_navigation():
    recipe, _ = match_recipe("Kosten je Kostenstelle Ist 2025", domain="co")
    cmds = iter(["n", "n", "b", "done"])
    out_lines = []

    def fake_input(prompt):
        return next(cmds)

    run_interactive("Kosten je Kostenstelle Ist 2025", "co", "sap_exports", input_fn=fake_input, out=out_lines.append)
    text = "\n".join(out_lines)
    assert "Schritt 1/" in text and "Schritt 2/" in text
    assert "automatisch" in text  # Abschluss-Hinweis aufs Einlesen


def test_cli_list_and_batch(tmp_path, capsys):
    rc = main(["sap-guide", "--list"])
    assert rc == 0
    assert "co-kostenstellen-ist" in capsys.readouterr().out
    rc = main(["sap-guide", "--goal", "Kosten je Kostenstelle Ist 2025", "--domain", "co", "--batch", "--config", "/nonexistent.yaml"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "S_ALR_87013611" in out and "SE16N" in out
    # Intake-Ordner wurde angelegt
    assert (tmp_path / "sap_exports").exists() or __import__("pathlib").Path("./sap_exports").exists()


def test_intake_dir_from_local_connector(tmp_path):
    config = {"connectors": [{"type": "local", "root": str(tmp_path / "lake")}]}
    d = intake_dir_from_config(config)
    assert d.endswith("sap_exports")
    assert (tmp_path / "lake" / "sap_exports").is_dir()
