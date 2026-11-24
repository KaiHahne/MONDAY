# foerderpilot

Multi-Agent-Tool, das die **Data Lakes eines Unternehmens** durchsucht, das passende
**Förderprogramm** per Regel-Engine findet und daraus **Förderanträge** (Markdown-Entwürfe) erstellt.

## Architektur

Vier Agenten laufen sequenziell über einen geteilten Kontext (jeder Schritt wird in `out/trace.json` auditiert):

| Agent | Aufgabe |
|---|---|
| `DataLakeExplorer` | Erkundet alle konfigurierten Data Lakes, baut den Datenkatalog und destilliert das Unternehmensprofil (Stammdaten- + Kennzahlentabellen, DE/EN-Spalten, Key-Value-Tabellen). |
| `ProgramMatcher` | Lädt Förderprogramme als JSON/YAML-Regeln (`programs/`) und matcht sie gegen das Profil: Eligibility (alle `required`-Kriterien) + gewichteter Score, absteigend gerankt. |
| `ApplicationWriter` | Erstellt per LLM für die besten eligible Matches fertige Antragsentwürfe unter `out/applications/<programm-id>.md`. |
| `Orchestrator` | Koordiniert die Agenten und zeichnet den Trace. |

## Data-Lake-Connectoren

- **lokal**: Verzeichnis mit `Parquet` / `CSV` / `JSON` / `JSONL`
- **SQL**: beliebige Datenbank via SQLAlchemy (`pip install foerderpilot[sql]`)
- **S3**: S3-kompatible Object Stores inkl. MinIO (`pip install foerderpilot[s3]`); Credentials nur aus der Umgebung (`AWS_*` bzw. `FOERDERPILOT_S3_*`)

## Förderprogramm-Regeln

Programme sind maschinenlesbare JSON/YAML-Definitionen (siehe `programs/`):

```json
{
  "id": "mein-programm",
  "name": "Investitionszuschuss Beispiel",
  "provider": "Behörde X",
  "criteria": [
    {"field": "hq_country", "op": "in", "value": ["DE"], "required": true, "weight": 2},
    {"field": "employees", "op": "<=", "value": 250, "required": true, "weight": 2},
    {"field": "investment_amount_eur", "op": ">=", "value": 10000, "required": true, "weight": 3}
  ],
  "funding": {"type": "grant", "max_rate": 0.5, "max_amount_eur": 100000},
  "required_documents": ["Projektbeschreibung"]
}
```

Operatoren: `==`, `!=`, `>=`, `<=`, `>`, `<`, `in`, `not_in`, `contains`, `exists`.
`field` bezieht sich auf das extrahierte Profil (z. B. `employees`, `revenue_eur`, `hq_country`, `hq_state`, `industry`, `investment_amount_eur`, `purpose`, ... – siehe `foerderpilot/profile.py` für alle Aliase).

### Förderprogramme aus einem Export importieren

```bash
foerderpilot import-programs --input foerderdatenbank_export.csv --out programs/
# optional: --mapping mein_spaltenmapping.yaml  --force  --dry-run
```

Konvertiert CSV/JSON-Exporte (z. B. aus Förderdatenbanken) in einzelne `programs/<id>.json`-Regeln. Erkannt werden DE/EN-Standardspalten (`id`, `titel`, `zuwendungsgeber`, `foerderart`, `max_foedersatz` (auch `80%`), `max_förderbetrag`, `frist`, `kriterien`, `erforderliche_unterlagen`, ...); eigenes Mapping siehe [`examples/import_mapping.example.yaml`](examples/import_mapping.example.yaml). Beispiel-Export: [`examples/foerderdatenbank_export.csv`](examples/foerderdatenbank_export.csv).

**Kriterien-Syntax** in der Spalte `kriterien` – getrennt durch `;` oder Zeilenumbruch:

```
hq_country in [DE, BY]; employees<=250 | weight=2; purpose contains digital | required=false | weight=3
```

`field op value` mit Operatoren wie oben; `value` als JSON/Zahl/Liste (`[DE, BY]`) oder Text; Modifikatoren `| required=false` und `| weight=N` optional. Zeilen mit Fehlern werden gemeldet (mit Zeilennummer), ohne den Rest des Imports abzubrechen.

## Nutzung

```bash
pip install -e ".[all]"
foerderpilot init --dir .        # Beispiel-Config + Beispiel-Programm anlegen
# config.yaml anpassen (Connectoren, programs_dir)
export FOERDERPILOT_LLM_API_KEY=...   # nie commiten!
foerderpilot run --config config.yaml
```

**Lauffaehiges Beispiel** (Data-Lake-Layout + Config + erklaerte Stammdaten): siehe [`examples/`](examples/README.md) – Start mit `foerderpilot run --config examples/config.yaml`.

Relative Pfade in der Config (`root`, `programs_dir`, `output_dir`, `profile_file`) werden gegen das Verzeichnis der Config-Datei aufgeloest.

Ausgabe in `out/`:

- `catalog.json` – alle gefundenen Datasets inkl. Schema-Probe
- `profile.json` – extrahiertes Unternehmensprofil + Quellen
- `matches.json` – alle Programme mit Eligibility, Score und erfüllten/fehlenden Kriterien
- `applications/<programm-id>.md` – fertige Antragsentwürfe (LLM)
- `applications.json`, `trace.json` – Übersicht + Audit-Trace

## Web-UI (auch mobil, z. B. iPhone/Safari)

```bash
export FOERDERPILOT_WEB_TOKEN=<zufaelliges-token>   # Pflicht, nie committen
foerderpilot serve --config examples/config.yaml   # Default: http://127.0.0.1:8000
```

- **Default nur Loopback** (`127.0.0.1`). Auf dem eigenen Server im internen Netz: `--host 0.0.0.0` (oder `FOERDERPILOT_WEB_HOST`/`FOERDERPILOT_WEB_PORT`) – dann nur mit Token und idealerweise nur per VPN/intern erreichbar halten.
- Alle Endpunkte (`/`, `/api/*`) verlangen `Authorization: Bearer $FOERDERPILOT_WEB_TOKEN`; ohne Token startet der Server nicht. Das Token wird per `hmac.compare_digest` geprüft.
- UI: Pipeline per Button starten (`POST /api/run`, laeuft im Hintergrund-Thread, ein Lauf gleichzeitig), Live-Status + Trace (`/api/status`), Matches (`/api/matches`), Antragsentwuerfe (`/api/applications`, `/api/applications/<id>`).
- Der LLM-Key kommt serverseitig wie gehabt aus `FOERDERPILOT_LLM_API_KEY` – das iPhone braucht nur das Web-Token.
- Reiner Python-Standardserver (`http.server`), keine zusaetzlichen Dependencies.

## LLM-Konfiguration (nur zur Laufzeit, nie im Repo)

| Umgebungsvariable | Bedeutung |
|---|---|
| `FOERDERPILOT_LLM_API_KEY` | Pflicht – API-Key |
| `FOERDERPILOT_LLM_BASE_URL` | optional – OpenAI-kompatibles Endpoint (Default: `https://api.openai.com/v1`) |
| `FOERDERPILOT_LLM_MODEL` | optional – Modell (Default: `gpt-4o-mini`) |

Die Config lehnt Klartext-Secrets ab; nutze `env:VAR_NAME`-Referenzen.

**Mistral** (OpenAI-kompatibles API): `FOERDERPILOT_LLM_BASE_URL=https://api.mistral.ai/v1` und z. B. `FOERDERPILOT_LLM_MODEL=mistral-small-latest`. Key nur lokal exportieren – nie committen, nie im Chat teilen; bei Leak sofort im [Mistral Console](https://console.mistral.ai/) revoken.

## Entwicklung

```bash
pip install -e ".[all,test]"
pytest
```

Interne Entwickler-Doku (Architektur, Erweiterungspunkte, Test-Konventionen): [docs/ENTWICKLER.md](docs/ENTWICKLER.md).
