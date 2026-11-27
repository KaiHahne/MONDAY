from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

DEFAULT_RUNBOOK = Path(__file__).parent / "runbook.yaml"


@dataclass
class Step:
    tcode: str
    menu: str
    enter: dict[str, str] = field(default_factory=dict)
    expect: str = ""
    export: dict[str, str] | None = None
    automation: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Recipe:
    id: str
    domain: str
    title: str
    keywords: list[str]
    tables: list[str]
    steps: list[Step]
    notes: list[str]
    drop_into: str
    automation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "domain": self.domain,
            "title": self.title,
            "keywords": self.keywords,
            "tables": self.tables,
            "steps": [s.__dict__ for s in self.steps],
            "notes": self.notes,
            "drop_into": self.drop_into,
            "automation": self.automation,
        }


def load_runbook(path: str | Path | None = None) -> list[Recipe]:
    p = Path(path) if path else DEFAULT_RUNBOOK
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    recipes = []
    for r in data.get("recipes", []):
        recipes.append(
            Recipe(
                id=str(r["id"]),
                domain=str(r.get("domain", "general")),
                title=str(r.get("title", r["id"])),
                keywords=[str(k).lower() for k in r.get("keywords", [])],
                tables=[str(t) for t in r.get("tables", [])],
                steps=[
                    Step(
                        tcode=str(s.get("tcode", "-")),
                        menu=str(s.get("menu", "")),
                        enter={str(k): str(v) for k, v in (s.get("enter") or {}).items()},
                        expect=str(s.get("expect", "")),
                        export=(dict(s["export"]) if s.get("export") else None),
                        automation=[dict(a) for a in s.get("automation", [])],
                    )
                    for s in r.get("steps", [])
                ],
                notes=[str(n) for n in r.get("notes", [])],
                drop_into=str(r.get("drop_into", "sap_exports/")),
                automation=dict(r.get("automation") or {}),
            )
        )
    if not recipes:
        raise ValueError(f"Runbook {p} enthaelt keine Rezepte.")
    return recipes


def _tokens(text: str) -> list[str]:
    import re

    return [t for t in re.split(r"[^a-z0-9äöüß_/]+", text.lower()) if len(t) > 2]


def score_recipe(recipe: Recipe, goal: str, domain: str | None) -> int:
    goal_tokens = set(_tokens(goal))
    hits = sum(1 for k in recipe.keywords if k in goal_tokens or any(k in t for t in goal_tokens))
    if domain and recipe.domain == domain:
        hits += 3
    return hits


def match_recipe(goal: str, domain: str | None = None, runbook_path: str | Path | None = None) -> tuple[Recipe, list[Recipe]]:
    recipes = load_runbook(runbook_path)
    if domain:
        pool = [r for r in recipes if r.domain == domain] or recipes
    else:
        pool = recipes
    ranked = sorted(pool, key=lambda r: score_recipe(r, goal, domain), reverse=True)
    best = ranked[0]
    if score_recipe(best, goal, domain) == 0:
        general = next((r for r in ranked if r.domain == "general"), ranked[0])
        return general, [r for r in ranked if r is not general][:3]
    return best, [r for r in ranked[1:] if r is not best][:3]


def format_step(recipe: Recipe, index: int, drop_dir: str | None = None) -> str:
    step = recipe.steps[index]
    lines = [
        f"--- Schritt {index + 1}/{len(recipe.steps)} | Rezept: {recipe.title} ---",
        f"TCode:  /{step.tcode}" if step.tcode != "-" else "TCode:  (keiner – Menüweg)",
        f"Menü:   {step.menu}",
    ]
    if step.enter:
        lines.append("Eingeben:")
        lines += [f"  • {k}: {v}" for k, v in step.enter.items()]
    if step.expect:
        lines.append(f"Erwartet: {step.expect}")
    if step.export:
        lines.append("Export:")
        lines.append(f"  • Menü: {step.export.get('menu', '')}")
        lines.append(f"  • Format: {step.export.get('format', '')}")
        lines.append(f"  • Datei: {step.export.get('filename', '')}")
        if drop_dir:
            lines.append(f"  → Datei danach nach {drop_dir} legen (wird automatisch eingelesen)")
    return "\n".join(lines)


def format_recipe(recipe: Recipe, drop_dir: str | None = None) -> str:
    parts = [
        f"Rezept: {recipe.id} – {recipe.title} (Domain: {recipe.domain})",
        f"Tabellen: {', '.join(recipe.tables) if recipe.tables else '-'} | Drop-Zone: {drop_dir or recipe.drop_into}",
        "",
    ]
    parts += [format_step(recipe, i, drop_dir) for i in range(len(recipe.steps))]
    if recipe.notes:
        parts.append("Hinweise:")
        parts += [f"  • {n}" for n in recipe.notes]
    return "\n".join(parts)


def intake_dir_from_config(config: dict[str, Any] | None) -> str:
    """Erster local-Connector-Root + /sap_exports als Intake-Ordner; sonst ./sap_exports."""
    if config:
        for conn in config.get("connectors", []):
            if isinstance(conn, dict) and conn.get("type") == "local":
                base = Path(conn.get("root", "./data_lake"))
                target = base / "sap_exports"
                target.mkdir(parents=True, exist_ok=True)
                return str(target)
    target = Path("./sap_exports")
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def run_once(goal: str, domain: str | None, drop_dir: str | None, out: Callable[[str], None], runbook_path: str | Path | None = None) -> Recipe:
    recipe, alternatives = match_recipe(goal, domain, runbook_path)
    out(format_recipe(recipe, drop_dir))
    if alternatives:
        out("\nAlternativen: " + ", ".join(f"{r.id} ({r.domain})" for r in alternatives))
    return recipe


def run_interactive(
    goal: str,
    domain: str | None,
    drop_dir: str | None,
    input_fn: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    runbook_path: str | Path | None = None,
) -> None:
    """Souffleur-REPL: next/n, back/b, repeat, why, done/q. Befehle: help."""
    recipe, alternatives = match_recipe(goal, domain, runbook_path)
    out(f"Rezept: {recipe.id} – {recipe.title} ({len(recipe.steps)} Schritte)")
    if alternatives:
        out("Alternativen: " + ", ".join(r.id for r in alternatives) + "  (Befehl: 'switch <id>')")
    idx = 0
    out(format_step(recipe, idx, drop_dir))
    while True:
        try:
            cmd = input_fn("souffleur> ").strip().lower()
        except EOFError:
            break
        if cmd in ("q", "quit", "done", "exit"):
            out(f"Fertig. Dateien nach {drop_dir or recipe.drop_into} legen – 'foerderpilot run' liest sie automatisch ein.")
            break
        if cmd in ("n", "next", ""):
            idx = min(idx + 1, len(recipe.steps) - 1)
        elif cmd in ("b", "back"):
            idx = max(idx - 1, 0)
        elif cmd in ("r", "repeat"):
            pass
        elif cmd.startswith("switch "):
            new_id = cmd.split(None, 1)[1]
            alt = next((r for r in alternatives if r.id == new_id), None)
            if alt:
                recipe, idx = alt, 0
                out(f"Wechsel zu {recipe.id} – {recipe.title}")
            else:
                out(f"Unbekanntes Rezept: {new_id}")
                continue
        elif cmd in ("help", "h", "?"):
            out("Befehle: next/n/Enter, back/b, repeat/r, switch <id>, help, done/q")
            continue
        else:
            out(f"Unbekannt: {cmd!r} – 'help' für Befehle.")
            continue
        out(format_step(recipe, idx, drop_dir))
