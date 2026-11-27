from __future__ import annotations

import json
from typing import Any

from foerderpilot.sap.guide import Recipe


def step_actions(recipe: Recipe, index: int) -> list[dict[str, Any]]:
    """Tool-neutrale Action-Liste fuer einen Schritt: TCode -> Felder -> Automation -> Export."""
    step = recipe.steps[index]
    actions: list[dict[str, Any]] = []
    if step.tcode and step.tcode != "-":
        actions.append({"action": "SendKeys", "keys": f"/{step.tcode}{{ENTER}}", "comment": f"TCode {step.tcode} ausführen"})
    for field_name, value in step.enter.items():
        actions.append(
            {
                "action": "SetText",
                "control": f"<Feld '{field_name}' – Control-ID per Recorder/Scripting-Tracker ermitteln>",
                "text": value,
            }
        )
    actions.extend(step.automation)
    if step.export:
        actions.append({"action": "ClickMenu", "path": step.export.get("menu", ""), "comment": "Export-Menü öffnen"})
        actions.append({"action": "ChooseFormat", "format": step.export.get("format", "")})
        actions.append({"action": "SetText", "control": "<Dateiname-Feld>", "text": step.export.get("filename", "")})
        actions.append({"action": "Click", "control": "Speichern", "comment": "Export speichern"})
    return actions


def render_actions(recipe: Recipe) -> list[dict[str, Any]]:
    """Komplette Action-Sequenz des Rezepts (Launch + Schritte + Abschluss-Hinweis)."""
    out: list[dict[str, Any]] = []
    auto = recipe.automation or {}
    if auto.get("app"):
        out.append({"action": "LaunchApplication", "app": auto["app"], "args": auto.get("launch_args", "")})
    out.extend(auto.get("actions", []))
    for i in range(len(recipe.steps)):
        out.append({"action": "Comment", "text": f"--- Schritt {i + 1}: {recipe.steps[i].menu} ---"})
        out.extend(step_actions(recipe, i))
    out.append({"action": "Notify", "text": f"Rezept '{recipe.id}' fertig – Datei nach {recipe.drop_into} legen und 'foerderpilot run' starten."})
    return out


def render_pad(recipe: Recipe) -> dict[str, Any]:
    """Power-Automate-Desktop-Flow (vereinfachtes JSON; in PAD Desktop als Flow-Schritte uebernehmbar)."""
    return {
        "tool": "power-automate-desktop",
        "recipe": recipe.id,
        "title": recipe.title,
        "note": "Control-IDs mit dem PAD-Recorder bzw. SAP Scripting-Tracker (Alt+F12) nachtragen; "
                "Menüs alternativ per UI-Automation aufzeichnen.",
        "actions": render_actions(recipe),
    }


_VBA_HEADER = """' ============================================================
' SAP-GUI-Scripting-Makro – generiert von: foerderpilot sap-guide --emit vba
' Rezept: {rid} – {title}
' Voraussetzungen:
'   1) SAP GUI Optionen -> Barrierefreiheit -> "Scripting aktivieren"
'   2) VBA-Editor: Extras -> Verweise -> "SAP GUI Scripting API"
'   3) Feld-IDs einmalig mit Scripting-Tracker (Alt+F12) aufzeichnen
' ============================================================
Sub RunFoerderExtraction()
    Dim SapGuiApp As Object, Conn As Object, session As Object
    Set SapGuiApp = GetObject("SAPGUI")
    Set Conn = SapGuiApp.Children(0)
    Set session = Conn.Children(0)
    session.findById("wnd[0]").maximize
"""

_VBA_FOOTER = """    MsgBox "Rezept {rid} fertig. Datei nach {drop} legen und 'foerderpilot run' starten.", vbInformation
End Sub
"""


def render_vba(recipe: Recipe) -> str:
    """VBA-Makro-Skelett (SAP GUI Scripting API) fuer das Rezept."""
    lines = [_VBA_HEADER.format(rid=recipe.id, title=recipe.title)]
    for action in render_actions(recipe):
        kind = action.get("action")
        if kind == "Comment":
            lines.append(f"    ' {action.get('text', '')}")
        elif kind == "LaunchApplication":
            lines.append(f"    ' TODO: {action.get('app')} starten ({action.get('args', '')}) – oder SAP Logon bereits offen lassen")
        elif kind == "WaitForWindow":
            lines.append(f"    ' TODO: warten auf Fenster '{action.get('titleContains', '')}' (DoEvents/Sleep Schleife)")
        elif kind == "SendKeys":
            keys = str(action.get("keys", "")).replace("{ENTER}", "")
            lines.append(f"    session.findById(\"wnd[0]/tbar[0]/okcd\").text = \"{keys}\"")
            lines.append("    session.findById(\"wnd[0]\").sendVKey 0  ' Enter")
        elif kind == "SetText":
            lines.append(f"    ' TODO Feld-ID eintragen: {action.get('control')}")
            lines.append(f"    ' session.findById(\"wnd[0]/usr/...\").text = \"{action.get('text', '')}\"")
        elif kind == "PressKey":
            lines.append(f"    ' Taste {action.get('key')}: Key-Code per Tracker ermitteln, z. B. sendVKey 8 ' F8")
        elif kind == "ClickMenu":
            lines.append(f"    ' TODO Menüpfad per UI-Element aufzeichnen: {action.get('path')}")
        elif kind == "ChooseFormat":
            lines.append(f"    ' TODO Exportformat wählen: {action.get('format')}")
        elif kind == "Click":
            lines.append(f"    ' TODO Klick auf '{action.get('control')}' (z. B. sendVKey 11 ' F11/Speichern je Dialog)")
        elif kind == "Notify":
            lines.append(f"    ' Hinweis: {action.get('text')}")
    lines.append(_VBA_FOOTER.format(rid=recipe.id, drop=recipe.drop_into))
    return "\n".join(lines)


RENDERERS = {
    "actions": lambda recipe: json.dumps(render_actions(recipe), ensure_ascii=False, indent=2),
    "pad": lambda recipe: json.dumps(render_pad(recipe), ensure_ascii=False, indent=2),
    "vba": render_vba,
}
