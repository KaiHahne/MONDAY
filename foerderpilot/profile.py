from __future__ import annotations

import re
from typing import Any

from foerderpilot.catalog import DataCatalog, DatasetInfo

# Kanonisches Feld -> erkannte Spaltennamen (deutsch/englisch, case-insensitive)
FIELD_ALIASES: dict[str, list[str]] = {
    "company_name": ["firma", "firmenname", "company", "company_name", "name", "unternehmensname"],
    "legal_form": ["rechtsform", "legal_form"],
    "hq_country": ["land", "country", "hq_country", "stammsitz_land"],
    "hq_state": ["bundesland", "state", "region", "hq_state", "bundesland_code"],
    "hq_city": ["stadt", "ort", "city"],
    "industry": ["branche", "industry", "sektor", "sector", "wirtschaftszweig", "nace", "nace_code"],
    "employees": [
        "mitarbeiter", "beschaeftigte", "employees", "headcount",
        "anzahl_mitarbeiter", "mitarbeiterzahl", "fte",
    ],
    "revenue_eur": ["umsatz", "revenue", "jahresumsatz", "revenue_eur", "umsatz_eur", "erloes"],
    "founded_year": ["gruendungsjahr", "founded", "founded_year", "jahr_der_gruendung"],
    "investment_amount_eur": [
        "investitionsbetrag", "investition", "investment", "investment_amount_eur",
        "investitionssumme", "vorhabenkosten", "projektkosten",
    ],
    "rd_share": ["fue_anteil", "rd_share", "forschungsanteil", "fue_aufwandsanteil"],
    "energy_consumption_kwh": ["energieverbrauch", "stromverbrauch", "energy_consumption_kwh", "kwh"],
    "co2_emissions_t": ["co2", "co2_emissionen", "co2_emissions_t", "co2_ausstoss"],
    "digitalization_score": ["digitalisierungsgrad", "digitalization_score", "reife_digital"],
    "export_share": ["exportanteil", "export_share", "auslandsanteil"],
    "purpose": ["vorhaben", "purpose", "foerderzweck", "projekt", "vorhabensbeschreibung"],
}

# Dataset-Namen, die typischerweise Stammdaten des Unternehmens enthalten
COMPANY_TABLE_HINTS = ["stammdaten", "firma", "company", "enterprise", "profil", "profile", "organisation"]

# Key-Value-Tabellen (z. B. Kennzahlen): erkannte Spaltenpaare
KV_KEY_COLUMNS = ["schluessel", "key", "kennzahl", "name", "kpi", "metrik", "metric"]
KV_VALUE_COLUMNS = ["wert", "value", "betrag", "amount"]

_DE_GROUPED = re.compile(r"-?\d{1,3}(\.\d{3})+(,\d+)?$")
_EN_GROUPED = re.compile(r"-?\d{1,3}(,\d{3})+(\.\d+)?$")
_DE_DECIMAL = re.compile(r"-?\d+,\d+$")
_PLAIN = re.compile(r"-?\d+(\.\d+)?$")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _to_number(value: Any) -> float | int | None:
    """Parst Zahlen aus DE- ('12.500.000,50') und EN-Formaten ('12,500,000.50')."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not text:
        return None
    if _DE_GROUPED.match(text):
        text = text.replace(".", "").replace(",", ".")
    elif _EN_GROUPED.match(text):
        text = text.replace(",", "")
    elif _DE_DECIMAL.match(text):
        text = text.replace(",", ".")
    elif not _PLAIN.match(text):
        return None
    try:
        num = float(text)
    except ValueError:
        return None
    return int(num) if num.is_integer() else num


def _first_scalar(df_columns: list[str], sample: list[dict[str, Any]], aliases: list[str]) -> Any:
    normalized = {_norm(c): c for c in df_columns}
    for alias in aliases:
        col = normalized.get(_norm(alias))
        if col is None:
            continue
        for row in sample:
            val = row.get(col)
            if val is not None and str(val).strip() != "":
                return val
    return None


def _looks_like_company_table(info: DatasetInfo) -> bool:
    name = info.ref.name.lower()
    if any(hint in name for hint in COMPANY_TABLE_HINTS):
        return True
    hits = sum(
        1
        for field_aliases in FIELD_ALIASES.values()
        if any(_norm(c) in {_norm(a) for a in field_aliases} for c in info.columns)
    )
    return hits >= 2


def _looks_like_kv_table(info: DatasetInfo) -> bool:
    norm_cols = {_norm(c) for c in info.columns}
    has_key = any(_norm(k) in norm_cols for k in KV_KEY_COLUMNS)
    has_value = any(_norm(v) in norm_cols for v in KV_VALUE_COLUMNS)
    return has_key and has_value and len(info.columns) <= 4


def _alias_for_key(key: str) -> str | None:
    nk = _norm(key)
    for field, aliases in FIELD_ALIASES.items():
        if nk in {_norm(a) for a in aliases}:
            return field
    return None


def extract_profile(catalog: DataCatalog, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Destilliert ein kanonisches Unternehmensprofil aus dem Data-Catalog.

    Nutzt (1) Stammdaten-Tabellen und (2) Key-Value-Kennzahlentabellen.
    Explizite Overrides aus der Config gewinnen immer.
    """
    profile: dict[str, Any] = {}
    sources: list[str] = []

    for info in catalog.datasets:
        if _looks_like_kv_table(info):
            key_col = next(c for c in info.columns if _norm(c) in {_norm(k) for k in KV_KEY_COLUMNS})
            val_col = next(c for c in info.columns if _norm(c) in {_norm(v) for v in KV_VALUE_COLUMNS})
            for row in info.sample:
                field = _alias_for_key(row.get(key_col, ""))
                if field and field not in profile:
                    raw = row.get(val_col)
                    profile[field] = _to_number(raw) if _to_number(raw) is not None else raw
            sources.append(f"{info.ref.connector}:{info.ref.name} (kv)")
            continue
        if _looks_like_company_table(info):
            for field, aliases in FIELD_ALIASES.items():
                if field in profile:
                    continue
                val = _first_scalar(info.columns, info.sample, aliases)
                if val is not None:
                    num = _to_number(val)
                    profile[field] = num if num is not None else val
            sources.append(f"{info.ref.connector}:{info.ref.name}")

    if overrides:
        profile.update(overrides)
        sources.append("config:profile_overrides")

    profile["_sources"] = sources
    return profile
