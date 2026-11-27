from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from foerderpilot.config import load_config
from foerderpilot.pipeline import run_pipeline

EXAMPLE_CONFIG = """# foerderpilot Konfiguration
# Secrets NIE in Klartext eintragen – immer als env:VAR_NAME referenzieren.

connectors:
  - type: local
    name: lake_lokal
    root: ./data_lake            # Parquet/CSV/JSON/JSONL
  # - type: sql
  #   name: lake_sql
  #   url: env:FOERDERPILOT_DB_URL
  # - type: s3
  #   name: lake_s3
  #   bucket: mein-data-lake
  #   prefix: unternehmen/stammdaten
  #   endpoint_url: https://s3.eu-central-1.amazonaws.com   # optional, auch MinIO
  #   region: eu-central-1

programs_dir: ./programs         # JSON/YAML mit Foerderprogramm-Regeln
output_dir: ./out
sample_rows: 5                   # Zeilen-Probe pro Dataset fuer Katalog/Profil
max_applications: 5              # soviele Antraege sollen erstellt werden

# Profil-Felder, die im Data Lake nicht (vollstaendig) vorhanden sind:
profile_overrides:
  hq_country: DE
# profile_file: ./profil.yaml    # optional: manuell gepflegte Stammdaten

# LLM nur aus der Umgebung (nie Klartext):
#   FOERDERPILOT_LLM_API_KEY (Pflicht), FOERDERPILOT_LLM_BASE_URL, FOERDERPILOT_LLM_MODEL
# Mistral: BASE_URL=https://api.mistral.ai/v1, MODEL=mistral-small-latest
"""

EXAMPLE_PROGRAM = """{
  "id": "beispiel-investitionszuschuss",
  "name": "Beispiel: Investitionszuschuss Digitalisierung",
  "provider": "Beispiel-Behoerde",
  "description": "Zuschuss fuer Digitalisierungsvorhaben von KMU.",
  "url": "https://example.org/foerderung",
  "region": ["DE"],
  "purposes": ["digitalization"],
  "criteria": [
    {"field": "hq_country", "op": "in", "value": ["DE"], "required": true, "weight": 2},
    {"field": "employees", "op": "<=", "value": 250, "required": true, "weight": 2},
    {"field": "revenue_eur", "op": "<=", "value": 50000000, "required": true, "weight": 1},
    {"field": "investment_amount_eur", "op": ">=", "value": 10000, "required": true, "weight": 3},
    {"field": "purpose", "op": "contains", "value": "digital", "required": false, "weight": 2}
  ],
  "funding": {"type": "grant", "max_rate": 0.5, "max_amount_eur": 100000},
  "required_documents": ["Handelsregisterauszug", "Projektbeschreibung", "Kostenplan"],
  "deadline": null
}
"""


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = run_pipeline(config)
    summary = {
        "output_dir": str(result.output_dir),
        "datasets": len(result.context.catalog.datasets) if result.context.catalog else 0,
        "programs_matched": len(result.context.matches),
        "eligible": sum(1 for m in result.context.matches if m.eligible),
        "applications": [a["file"] for a in result.context.applications],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / "config.yaml"
    programs_dir = target / "programs"
    programs_dir.mkdir(exist_ok=True)
    example_path = programs_dir / "beispiel.json"
    if config_path.exists() or example_path.exists():
        print(f"Bereits vorhanden, nichts ueberschrieben: {config_path}, {example_path}", file=sys.stderr)
        return 1
    config_path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    example_path.write_text(EXAMPLE_PROGRAM, encoding="utf-8")
    print(f"Beispiel-Config erstellt: {config_path}\nBeispiel-Programm erstellt: {example_path}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    from foerderpilot.programs.importer import import_programs

    report = import_programs(args.input, args.out, args.mapping, force=args.force, dry_run=args.dry_run)
    print(
        json.dumps(
            {
                "written": report.written,
                "skipped": report.skipped,
                "errors": report.errors,
                "dry_run": report.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not report.errors else 1


def _cmd_research(args: argparse.Namespace) -> int:
    from foerderpilot.config import load_config
    from foerderpilot.llm.client import OpenAICompatibleClient
    from foerderpilot.pipeline import run_pipeline
    from foerderpilot.research import build_backend, research_programs

    config = load_config(args.config)
    llm = OpenAICompatibleClient.from_env()
    profile = {}
    if args.use_lake_profile:
        result = run_pipeline(config, llm_client=llm)
        profile = result.context.profile
    levels = [l.strip() for l in args.levels.split(",")] if args.levels else None
    report = research_programs(
        config,
        llm=llm,
        search_backend=build_backend(config),
        out_dir=args.out,
        levels=levels,
        max_per_level=args.max_per_level,
        profile=profile,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not report.errors else 1


def _cmd_sap_guide(args: argparse.Namespace) -> int:
    from foerderpilot.config import load_config
    from foerderpilot.sap import intake_dir_from_config, load_runbook, run_interactive, run_once

    config = None
    if args.config and Path(args.config).exists():
        config = load_config(args.config)
    drop_dir = intake_dir_from_config(config)
    recipes = load_runbook(args.runbook)
    if args.list:
        for r in recipes:
            print(f"{r.id:24s} [{r.domain:7s}] {r.title}")
        return 0
    if not args.goal:
        print("Bitte --goal angeben, z. B. --goal 'Kosten je Kostenstelle Ist 2025' (oder --list).", file=sys.stderr)
        return 2
    if args.batch:
        run_once(args.goal, args.domain, drop_dir, out=print, runbook_path=args.runbook)
    else:
        run_interactive(args.goal, args.domain, drop_dir, runbook_path=args.runbook)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import os

    from foerderpilot.web.server import DEFAULT_HOST, DEFAULT_PORT, serve

    host = args.host or os.environ.get("FOERDERPILOT_WEB_HOST", DEFAULT_HOST)
    port = args.port or int(os.environ.get("FOERDERPILOT_WEB_PORT", DEFAULT_PORT))
    serve(args.config, host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="foerderpilot",
        description="Multi-Agent-Tool: Data Lakes durchsuchen, passende Foerderprogramme finden, Antraege erstellen.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Pipeline ausfuehren (braucht FOERDERPILOT_LLM_API_KEY in der Umgebung)")
    run_p.add_argument("--config", default="config.yaml", help="Pfad zur YAML-Config (Default: config.yaml)")
    run_p.set_defaults(func=_cmd_run)
    serve_p = sub.add_parser(
        "serve",
        help="Web-UI starten (Default nur 127.0.0.1; braucht FOERDERPILOT_WEB_TOKEN als Bearer-Token)",
    )
    serve_p.add_argument("--config", default="config.yaml", help="Pfad zur YAML-Config (Default: config.yaml)")
    serve_p.add_argument("--host", default=None, help="Bind-Adresse (Default: 127.0.0.1 bzw. FOERDERPILOT_WEB_HOST)")
    serve_p.add_argument("--port", type=int, default=None, help="Port (Default: 8000 bzw. FOERDERPILOT_WEB_PORT)")
    serve_p.set_defaults(func=_cmd_serve)
    init_p = sub.add_parser("init", help="Beispiel-Config und Beispiel-Programm anlegen")
    init_p.add_argument("--dir", default=".", help="Zielverzeichnis (Default: aktuelles Verzeichnis)")
    init_p.set_defaults(func=_cmd_init)
    imp_p = sub.add_parser(
        "import-programs",
        help="Foerderprogramm-Export (CSV/JSON) in programs/<id>.json-Regeln importieren",
    )
    imp_p.add_argument("--input", required=True, help="Export-Datei (.csv oder .json)")
    imp_p.add_argument("--out", default="programs", help="Zielverzeichnis (Default: programs)")
    imp_p.add_argument("--mapping", default=None, help="optionale YAML mit Spaltenmapping (siehe examples/import_mapping.example.yaml)")
    imp_p.add_argument("--force", action="store_true", help="bestehende Programm-Dateien ueberschreiben")
    imp_p.add_argument("--dry-run", action="store_true", help="nur pruefen/melden, nichts schreiben")
    imp_p.set_defaults(func=_cmd_import)
    res_p = sub.add_parser(
        "research",
        help="Foerderprogramme pro Verwaltungsebene recherchieren (EU/Bund/Land/Gemeinde) -> Drafts in programs/research/",
    )
    res_p.add_argument("--config", default="config.yaml", help="Pfad zur YAML-Config (Default: config.yaml)")
    res_p.add_argument("--levels", default=None, help="kommagetrennt, z. B. 'eu,bund,land' (Default: alle vier Ebenen)")
    res_p.add_argument("--max-per-level", type=int, default=5, help="max. Drafts pro Ebene (Default: 5)")
    res_p.add_argument("--out", default="programs/research", help="Zielverzeichnis fuer Drafts (Default: programs/research)")
    res_p.add_argument("--use-lake-profile", action="store_true", help="vorher Pipeline laufen lassen und Profil aus dem Data Lake fuer die Such-Queries nutzen")
    res_p.set_defaults(func=_cmd_research)
    sap_p = sub.add_parser(
        "sap-guide",
        help="Souffleur-Agent: Schritt-fuer-Schritt-Anleitung fuer SAP-Extraktionen (TCode/Menü/Export)",
    )
    sap_p.add_argument("--config", default="config.yaml", help="Config – bestimmt den Intake-Ordner (local root + /sap_exports)")
    sap_p.add_argument("--goal", default=None, help="Datenziel, z. B. 'Kosten je Kostenstelle Ist 2025'")
    sap_p.add_argument("--domain", default=None, help="SAP-Domain: co | bw | fi | sd | mm | general")
    sap_p.add_argument("--runbook", default=None, help="eigenes Runbook-YAML (Default: eingebautes foerderpilot/sap/runbook.yaml)")
    sap_p.add_argument("--list", action="store_true", help="alle Rezepte auflisten und beenden")
    sap_p.add_argument("--batch", action="store_true", help="nicht-interaktiv: komplettes Rezept ausgeben")
    sap_p.set_defaults(func=_cmd_sap_guide)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
