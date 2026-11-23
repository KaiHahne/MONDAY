# Beispiel: Data-Lake-Layout und End-to-End-Run

Dieses Verzeichnis ist ein lauffaehiges Beispiel. Aus dem Repo-Root:

```bash
export FOERDERPILOT_LLM_API_KEY=...     # Pflicht, nie commiten
foerderpilot run --config examples/config.yaml
```

Ergebnisse landen in `examples/out/` (`catalog.json`, `profile.json`, `matches.json`, `applications/*.md`, `trace.json`).

## Empfohlenes Data-Lake-Layout

```
data_lake/
  stammdaten/
    unternehmen.csv        # genau 1 Zeile mit den Stammdaten des Unternehmens
  kennzahlen/
    kennzahlen.json        # Key-Value-Liste: [{"kennzahl": "...", "wert": ...}, ...]
  projekte/
    projektliste.parquet   # beliebige weitere Datasets (CSV/JSON/JSONL/Parquet)
```

Der `DataLakeExplorer`-Agent erkennt automatisch:

1. **Stammdaten-Tabellen** – am Tabellennamen (`stammdaten`, `firma`, `company`, `enterprise`, `profil`, `profile`, `organisation`) oder an mindestens 2 bekannten Profildaten-Spalten.
2. **Key-Value-Tabellen** – Spaltenpaar aus Schluessel (`schluessel`/`key`/`kennzahl`/`name`/`kpi`/`metrik`/`metric`) + Wert (`wert`/`value`/`betrag`/`amount`), max. 4 Spalten.

## Erkannte Spalten (DE/EN, Gross-/Kleinschreibung egal)

| Profil-Feld | erkannte Spalten (Auswahl) |
|---|---|
| `company_name` | firma, firmenname, company, name, unternehmensname |
| `legal_form` | rechtsform |
| `hq_country` | land, country |
| `hq_state` | bundesland, state, region |
| `hq_city` | stadt, ort, city |
| `industry` | branche, industry, sector, wirtschaftszweig, nace |
| `employees` | mitarbeiter, beschaeftigte, employees, headcount, fte |
| `revenue_eur` | umsatz, revenue, jahresumsatz, erloes |
| `founded_year` | gruendungsjahr, founded |
| `investment_amount_eur` | investitionsbetrag, investition, vorhabenkosten, projektkosten |
| `rd_share` | fue_anteil, rd_share, forschungsanteil |
| `energy_consumption_kwh` | energieverbrauch, stromverbrauch, kwh |
| `co2_emissions_t` | co2, co2_emissionen |
| `export_share` | exportanteil, export_share |
| `purpose` | vorhaben, purpose, projekt, foerderzweck |

Zahlen werden automatisch geparst, auch deutsches Format (`9.500.000` = 9500000, `0,08` = 0.08).

Vollstaendige Alias-Liste: `foerderpilot/profile.py` (`FIELD_ALIASES`).

## Was das Beispiel zeigt

Mit den Beispiel-Stammdaten (80 Mitarbeiter, 9,5 Mio. EUR Umsatz, Investition 150.000 EUR,
Vorhaben „Digitalisierung …") matchen die Regeln aus `programs/`:

- **KfW ERP-Digitalisierung** – eligible, Score 10 (Top-Match → Antrag wird generiert)
- **BAFA Energieberatung** – eligible, Score 7
- **BMWK ZIM** – eligible, Score 7

In `examples/out/matches.json` siehst du pro Programm, welche Kriterien erfuellt/fehlgeschlagen sind.
