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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="foerderpilot",
        description="Multi-Agent-Tool: Data Lakes durchsuchen, passende Foerderprogramme finden, Antraege erstellen.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Pipeline ausfuehren (braucht FOERDERPILOT_LLM_API_KEY in der Umgebung)")
    run_p.add_argument("--config", default="config.yaml", help="Pfad zur YAML-Config (Default: config.yaml)")
    run_p.set_defaults(func=_cmd_run)
    init_p = sub.add_parser("init", help="Beispiel-Config und Beispiel-Programm anlegen")
    init_p.add_argument("--dir", default=".", help="Zielverzeichnis (Default: aktuelles Verzeichnis)")
    init_p.set_defaults(func=_cmd_init)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
