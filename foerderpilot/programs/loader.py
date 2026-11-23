from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from foerderpilot.programs.models import Criterion, FundingProgram


class ProgramValidationError(ValueError):
    pass


def _program_from_dict(data: dict[str, Any], source: str) -> FundingProgram:
    if not isinstance(data, dict):
        raise ProgramValidationError(f"{source}: Programmdefinition muss ein Objekt sein.")
    try:
        criteria = [
            Criterion(
                field=str(c["field"]),
                op=str(c["op"]),
                value=c.get("value"),
                required=bool(c.get("required", True)),
                weight=float(c.get("weight", 1.0)),
            )
            for c in data.get("criteria", [])
        ]
        program = FundingProgram(
            id=str(data["id"]),
            name=str(data["name"]),
            provider=str(data.get("provider", "")),
            description=str(data.get("description", "")),
            url=str(data.get("url", "")),
            region=list(data.get("region", [])),
            purposes=list(data.get("purposes", [])),
            criteria=criteria,
            funding=dict(data.get("funding", {})),
            required_documents=list(data.get("required_documents", [])),
            deadline=data.get("deadline"),
        )
    except KeyError as exc:
        raise ProgramValidationError(f"{source}: Pflichtfeld fehlt: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ProgramValidationError(f"{source}: ungueltige Programmdefinition: {exc}") from exc
    try:
        program.validate()
    except ValueError as exc:
        raise ProgramValidationError(f"{source}: {exc}") from exc
    return program


def load_programs(path: str | Path) -> list[FundingProgram]:
    """Laedt Foerderprogramme aus einer JSON/YAML-Datei oder einem Verzeichnis damit."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Foerderprogramm-Pfad existiert nicht: {p}")
    files = sorted(p.glob("*.json")) + sorted(p.glob("*.yaml")) + sorted(p.glob("*.yml")) if p.is_dir() else [p]
    programs: list[FundingProgram] = []
    seen_ids: set[str] = set()
    for file in files:
        text = file.read_text(encoding="utf-8")
        if file.suffix == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            program = _program_from_dict(entry, source=str(file))
            if program.id in seen_ids:
                raise ProgramValidationError(f"Doppelte Programm-ID {program.id!r} (Quelle: {file})")
            seen_ids.add(program.id)
            programs.append(program)
    if not programs:
        raise ProgramValidationError(f"Keine Foerderprogramme in {p} gefunden.")
    return programs
