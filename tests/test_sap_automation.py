import json

from foerderpilot.cli import main
from foerderpilot.sap import load_runbook, match_recipe, render_actions, render_pad, render_vba


def get_recipe(goal, domain):
    recipe, _ = match_recipe(goal, domain)
    return recipe


def test_runbook_has_automation_blocks():
    recipes = {r.id: r for r in load_runbook()}
    assert recipes["co-kostenstellen-ist"].automation.get("tool") == "power-automate-desktop"
    assert recipes["bw-query-export"].automation.get("app") == "saplogon.exe"
    assert any(s.automation for s in recipes["co-kostenstellen-ist"].steps)


def test_render_actions_sequence():
    recipe = get_recipe("Kosten je Kostenstelle Ist 2025", "co")
    actions = render_actions(recipe)
    kinds = [a["action"] for a in actions]
    assert "LaunchApplication" in kinds
    assert "SendKeys" in kinds
    send = next(a for a in actions if a["action"] == "SendKeys")
    assert "/S_ALR_87013611{ENTER}" in send["keys"]
    assert "SetText" in kinds and "ClickMenu" in kinds and "Notify" in kinds
    export = next(a for a in actions if a["action"] == "ClickMenu")
    assert "Exportieren" in export["path"]


def test_render_pad_is_json_with_actions():
    recipe = get_recipe("BW Query exportieren", "bw")
    pad = render_pad(recipe)
    assert pad["tool"] == "power-automate-desktop"
    assert pad["recipe"] == "bw-query-export"
    assert any(a["action"] == "SendKeys" and "/SE38" in a.get("keys", "") for a in pad["actions"])
    json.dumps(pad)  # serialisierbar


def test_render_vba_skeleton():
    recipe = get_recipe("Kosten je Kostenstelle Ist 2025", "co")
    vba = render_vba(recipe)
    assert 'GetObject("SAPGUI")' in vba
    assert '"/S_ALR_87013611"' in vba
    assert "usr/" in vba and "TODO" in vba  # Feld-IDs als Platzhalter
    assert "co-kostenstellen-ist" in vba


def test_cli_emit_vba_and_pad(tmp_path, capsys):
    out_file = tmp_path / "makro.vba"
    rc = main(["sap-guide", "--goal", "Kosten je Kostenstelle Ist 2025", "--domain", "co",
               "--emit", "vba", "--out", str(out_file), "--config", "/nonexistent.yaml"])
    assert rc == 0
    text = out_file.read_text(encoding="utf-8")
    assert "RunFoerderExtraction" in text and "S_ALR_87013611" in text
    capsys.readouterr()  # bisherige Ausgabe verwerfen

    rc = main(["sap-guide", "--goal", "Kosten je Kostenstelle Ist 2025", "--domain", "co", "--emit", "pad"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "power-automate-desktop"
    assert payload["actions"]
