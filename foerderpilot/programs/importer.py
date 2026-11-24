from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from foerderpilot.programs.loader import ProgramValidationError
from foerderpilot.programs.models import Criterion, FundingProgram

# Standard-Spaltenmapping fuer typische Exporte (Zuwendungsgeber/Foerderdatenbank-artig, DE/EN)
DEFAULT_COLUMN_ALIASES: dict[str, list[str]] = {
    "id": ["id", "program_id", "programm_id", "foerderprogramm_id", "rid"],
    "name": ["name", "titel", "programm", "foerderprogramm", "bezeichnung"],
    "provider": ["provider", "zuwendungsgeber", "traeger", "behoerde", "antragsstelle"],
    "description": ["description", "beschreibung", "kurzbeschreibung"],
    "url": ["url", "link", "webseite", "homepage"],
    "region": ["region", "gilt_fuer", "laender", "regionen"],
    "purposes": ["purposes", "zwecke", "foerderzwecke", "themen"],
    "deadline": ["deadline", "frist", "antragsfrist", "stichtag"],
    "criteria": ["criteria", "kriterien", "voraussetzungen", "bedingungen", "conditions"],
    "funding_type": ["funding_type", "foerderart", "art"],
    "funding_max_rate": ["max_rate", "foerdersatz", "foerderquote", "max_foerdersatz"],
    "funding_max_amount_eur": ["max_amount_eur", "max_betrag", "max_förderbetrag", "hoechstbetrag"],
    "required_documents": ["required_documents", "erforderliche_unterlagen", "anlagen", "documents"],
}

# Symbolische Operatoren duerfen direkt am Feld stehen ('employees<=250'),
# Wort-Operatoren brauchen zwingend Leerzeichen ('hq_country in [DE]'),
# damit 'kein operator hier' nicht als ke+in fehlparst.
_CRIT_SYM_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.*?)\s*$")
_CRIT_WORD_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(in|not_in|contains|exists)\s*(.*?)\s*$")
_SAFE_ID_RE = re.compile(r"[^a-z0-9_-]+")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _safe_id(value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("-", value.strip().lower()).strip("-")
    if not cleaned:
        raise ProgramValidationError(f"id ergibt keinen gueltigen Dateinamen: {value!r}")
    return cleaned


def _parse_value(raw: str) -> Any:
    """Parst Kriterium-Werte: JSON (Zahlen, Listen, Strings), Prozent, Fallbacks."""
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return json.loads(raw)
    except ValueError:
        pass
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        pass
    if raw.startswith(('"', "'")) and raw.endswith(raw[0]) and len(raw) >= 2:
        return raw[1:-1]
    return raw


def _parse_rate(raw: Any) -> float:
    text = str(raw).strip()
    if text.endswith("%"):
        return float(text[:-1].strip().replace(",", ".")) / 100.0
    return float(_parse_value(text))


def parse_criterion(text: str) -> Criterion:
    """Parst eine Kriterien-Zeile: 'field op value' mit optionalen Modifikatoren '| required=false | weight=3'."""
    parts = [p.strip() for p in text.split("|")]
    match = _CRIT_SYM_RE.match(parts[0]) or _CRIT_WORD_RE.match(parts[0])
    if not match:
        raise ProgramValidationError(f"Kriterium nicht parsebar: {text!r}")
    field_name, op, raw_value = match.group(1), match.group(2), match.group(3)
    mods = {}
    for part in parts[1:]:
        if "=" in part:
            key, val = part.split("=", 1)
            mods[key.strip()] = val.strip()
    criterion = Criterion(
        field=field_name,
        op=op,
        value=_parse_value(raw_value),
        required=mods.get("required", "true").lower() not in ("false", "0", "no"),
        weight=float(mods.get("weight", "1")),
    )
    criterion.validate()
    return criterion


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    text = str(value).strip()
    if not text:
        return []
    parsed = _parse_value(text)
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    if isinstance(parsed, str):
        return [p.strip() for p in re.split(r"[;,]", parsed) if p.strip()]
    return [str(parsed)]


def row_to_program(row: dict[str, Any], mapping: dict[str, list[str]] | None = None) -> FundingProgram:
    aliases = mapping or DEFAULT_COLUMN_ALIASES
    norm_row = {_norm(k): v for k, v in row.items() if k is not None}

    def get(field_name: str) -> Any:
        for alias in aliases.get(field_name, []):
            key = _norm(alias)
            if key in norm_row and str(norm_row[key]).strip() != "":
                return norm_row[key]
        return None

    raw_id, raw_name = get("id"), get("name")
    if not raw_id or not raw_name:
        raise ProgramValidationError("Zeile ohne id/titel – Spaltenmapping pruefen (--mapping).")

    criteria: list[Criterion] = []
    raw_criteria = get("criteria")
    if raw_criteria:
        for entry in re.split(r"[;\n]+", str(raw_criteria)):
            if entry.strip():
                criteria.append(parse_criterion(entry))

    funding: dict[str, Any] = {}
    if get("funding_type"):
        funding["type"] = str(get("funding_type")).strip()
    if get("funding_max_rate") is not None and str(get("funding_max_rate")).strip() != "":
        funding["max_rate"] = _parse_rate(get("funding_max_rate"))
    if get("funding_max_amount_eur") is not None and str(get("funding_max_amount_eur")).strip() != "":
        funding["max_amount_eur"] = _parse_value(str(get("funding_max_amount_eur")))

    program = FundingProgram(
        id=_safe_id(str(raw_id)),
        name=str(raw_name).strip(),
        provider=str(get("provider") or "").strip(),
        description=str(get("description") or "").strip(),
        url=str(get("url") or "").strip(),
        region=_as_list(get("region")),
        purposes=_as_list(get("purposes")),
        criteria=criteria,
        funding=funding,
        required_documents=_as_list(get("required_documents")),
        deadline=str(get("deadline")).strip() or None,
    )
    program.validate()
    return program


def load_source(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Export-Datei existiert nicht: {p}")
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("records", [data])
        if not isinstance(data, list):
            raise ValueError(f"{p}: JSON muss eine Liste (oder Objekt mit 'records') sein.")
        return [dict(r) for r in data]
    if p.suffix.lower() == ".csv":
        with open(p, newline="", encoding="utf-8-sig") as fh:
            return [dict(r) for r in csv.DictReader(fh)]
    raise ValueError(f"Nur .csv und .json werden unterstuetzt (bekommen: {p.suffix})")


@dataclass
class ImportReport:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False


def load_mapping(mapping_path: str | Path | None) -> dict[str, list[str]] | None:
    if not mapping_path:
        return None
    data = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8")) or {}
    columns = data.get("columns")
    if not isinstance(columns, dict):
        raise ValueError(f"Mapping-Datei {mapping_path} braucht einen Abschnitt 'columns:' (ziel: [spalten-aliases])")
    return {str(k): [str(a) for a in v] for k, v in columns.items()}


def import_programs(
    input_path: str | Path,
    out_dir: str | Path,
    mapping_path: str | Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> ImportReport:
    """Konvertiert einen Foerderprogramm-Export (CSV/JSON) in einzelne programs/<id>.json-Regeln."""
    rows = load_source(input_path)
    mapping = load_mapping(mapping_path)
    out = Path(out_dir)
    report = ImportReport(dry_run=dry_run)
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
    first_data_line = 2 if str(input_path).lower().endswith(".csv") else 1
    for i, row in enumerate(rows, start=first_data_line):
        try:
            program = row_to_program(row, mapping)
        except (ProgramValidationError, ValueError) as exc:
            report.errors.append(f"Zeile {i}: {exc}")
            continue
        target = out / f"{program.id}.json"
        if target.exists() and not force:
            report.skipped.append(program.id)
            continue
        if not dry_run:
            target.write_text(json.dumps(program.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report.written.append(program.id)
    return report
