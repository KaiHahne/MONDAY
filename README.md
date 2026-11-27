# foerderpilot

Multi-Agent-Tool, das die **Data Lakes eines Unternehmens** durchsucht, das passende
**Förderprogramm** per Regel-Engine findet und daraus **Förderanträge** (Markdown-Entwürfe) erstellt.

**Gesamtsequenz inkl. Research & Input/Output pro Schritt:** [docs/WORKFLOW.md](docs/WORKFLOW.md) (Sequenzdiagramm + Schritt-Tabelle). Entwickler-Doku: [docs/ENTWICKLER.md](docs/ENTWICKLER.md).

## Architektur

Vier Agenten laufen sequenziell über einen geteilten Kontext (jeder Schritt wird in `out/trace.json` auditiert):

| Agent | Aufgabe |
|---|---|
| `DataLakeExplorer` | Erkundet alle konfigurierten Data Lakes, baut den Datenkatalog und destilliert das Unternehmensprofil (Stammdaten- + Kennzahlentabellen, DE/EN-Spalten, Key-Value-Tabellen). |
| `ProgramMatcher` | Lädt Förderprogramme als JSON/YAML-Regeln (`programs/`) und matcht sie gegen das Profil: Eligibility (alle `required`-Kriterien) + gewichteter Score, absteigend gerankt. |
| `GapAnalysis` | Ermittelt pro Match Informationslücken: fehlende/fehlgeschlagene Profil-Felder, nicht auffindbare Pflicht-Unterlagen im Lake, fehlender Ansprechpartner (`contact`). |
| `Clarification` | Formuliert per LLM zweiseitig Klärungs-Mails: **extern** an die recherchierte Stelle (`contact.email`, Anrede mit `contact.stelle`) und **intern** an den Wissensträger (`clarification.internal.email`) für fehlende Unternehmensdaten → `out/emails/*.md` (Entwürfe, nie automatisch gesendet). |
| `ApplicationWriter` | Erstellt per LLM für die besten eligible Matches fertige Antragsentwürfe unter `out/applications/<programm-id>.md`. |
| `Coverage` | Schreibt `out/coverage.json`: welche Inputs beider Seiten identifiziert sind (`ok`/`override`) und welche noch `offen` (Programmkriterien, Unterlagen, Kontakt, Profil-Felder). |
| `Orchestrator` | Koordiniert die Agenten und zeichnet den Trace. |

## Workflow: Research → Match → Klärung

1. **Research pro Verwaltungsebene** (EU/Bund/Land/Gemeinde) – Programme, Kriterien, Formalismen und Ansprechpartner recherchieren:
   ```bash
   foerderpilot research --config examples/config.yaml --levels bund,land --max-per-level 5
   # optional: --use-lake-profile (Profil aus dem Data Lake in die Such-Queries einbauen)
   # Backend: research.backend: ddg (Default, DuckDuckGo-HTML) oder static (research.sources in Config)
   ```
   Ergebnis: Drafts in `programs/research/<ebene>-<id>.json` inkl. `contact` (Stelle/E-Mail), `criteria`,
   `required_documents`, `funding`, `source_url`, `status: "draft"` + `research-report.json`.
   **Menschliches Review, dann verschieben:** `mv programs/research/bund-xyz.json programs/` – erst dann matcht die Pipeline das Programm.

   **Hardening beim Research** (keine Behörden-API nötig – Webseiten/PDFs werden gelesen):
   PDFs (Merkblätter/Richtlinien) werden automatisch als Text extrahiert (`pip install foerderpilot[pdf]`);
   `robots.txt` wird respektiert, Retry/Backoff bei 429/5xx, Crawl-Delay pro Host (alles in `config.research`
   konfigurierbar: `respect_robots`, `crawl_delay`, `max_retries`, `backoff_base`, `user_agent`).
   Quellen, die nicht automatisch lesbar sind (Login-Wall, JS-only, leere PDFs), landen als **`manual`-Liste**
   im `research-report.json` zum manuellen Nachtragen als Draft.
2. **Match gegen die proprietären Systeme** – `foerderpilot run` (Explorer liest Data Lake / SQL / S3, Matcher gegen `programs/`).
3. **Lücken → Klärungs-Mail (zweiseitig)** – `GapAnalysis` schreibt `out/gaps.json`, `Clarification` formuliert
   Mail-Entwürfe: extern an die Förderstelle (`out/emails/<id>.md`) und intern an den Wissensträger
   (`out/emails/internal-wissenstraeger.md`). Abschaltbar: `clarification: {enabled: false}`.
   `Coverage` schreibt `out/coverage.json` (offen vs. identifiziert). In der Web-UI (`foerderpilot serve`)
   sichtbar unter „Luecken & Klaerungs-Mails“ (`/api/gaps`, `/api/evidence`, `/api/coverage`, `/api/emails`, `/api/emails/<id>`). |

## Data-Lake-Connectoren

- **lokal**: Verzeichnis mit `Parquet` / `CSV` / `JSON` / `JSONL`
- **SQL**: beliebige Datenbank via SQLAlchemy (`pip install foerderpilot[sql]`)
- **S3**: S3-kompatible Object Stores inkl. MinIO (`pip install foerderpilot[s3]`); Credentials nur aus der Umgebung (`AWS_*` bzw. `FOERDERPILOT_S3_*`)

## SAP-Souffleur: manuelle Extraktion Schritt für Schritt guided

Ein Agent, der deinen Bildschirm live sieht, geht in dieser Umgebung nicht (kein Desktop/Screen-Zugriff) –
dafür gibt es den **Runbook-Agenten**: Du beschreibst das Datenziel, der Agent souffliert dir die exakten
SAP-Schritte (TCode, Menüpfad, Felder, Export), du arbeitest sie in der SAP-GUI ab und legst die Downloads
in den Intake-Ordner – der Data Lake liest sie automatisch ein.

```bash
foerderpilot sap-guide --list                                          # alle Rezepte
foerderpilot sap-guide --goal "Kosten je Kostenstelle Ist 2025" --domain co   # interaktiver Souffleur (next/back/switch/done)
foerderpilot sap-guide --goal "BW Query exportieren" --domain bw --batch    # nicht-interaktiv
```

- Runbook: `foerderpilot/sap/runbook.yaml` (CO: KSBT/S_ALR_87013611, COEP/COSP via SE16N; BW: RSA3/RSRT, RSA1;
  allgemein: SE16N, SM37/AL11, ALV-Export) – eigenes Runbook per `--runbook` möglich.
- Intake-Ordner: `<erster local-Connector-root>/sap_exports/` (wird angelegt); Dateien dort landen
  automatisch im Katalog/Profil bei `foerderpilot run`.
- REPL-Befehle: `next/n`, `back/b`, `repeat/r`, `switch <rezept-id>`, `help`, `done/q`.

### Rezepte als Automation ausgeben (Power Automate / SAP GUI Scripting / …)

Rezepte können pro Rezept und pro Schritt ein `automation:`-Block enthalten (tool-neutrale Action-Liste,
z. B. `SendKeys`, `SetText`, `ClickMenu`, `WaitForWindow`). Daraus rendert der Agent ausführbare Skripte:

```bash
foerderpilot sap-guide --goal "Kosten je Kostenstelle Ist 2025" --domain co --emit actions   # tool-neutrale Action-Liste (JSON)
foerderpilot sap-guide --goal "..." --domain co --emit pad --out flow.json   # Power-Automate-Desktop-Flow (JSON)
foerderpilot sap-guide --goal "..." --domain co --emit vba --out makro.vba  # SAP GUI Scripting (VBA-Makro)
```

- **Power Automate Desktop:** `flow.json` als Flow-Schritte übernehmen; Control-IDs einmalig per PAD-Recorder
  bzw. SAP Scripting-Tracker (Alt+F12) nachtragen (stehen als `<...>`- Platzhalter im JSON).
- **SAP GUI Scripting (VBA):** Makro erfordert im SAP GUI „Scripting aktivieren“ + VBA-Verweis auf die
  „SAP GUI Scripting API“; Feld-IDs (`wnd[0]/usr/...`) als TODO-Platzhalter markiert.
- Ablauf bleibt: Skript/Flow auf deinem Windows-Rechner mit SAP ausführen → Datei landet im Intake-Ordner →
  `foerderpilot run` verarbeitet sie weiter.

## Proprietäre Unternehmensquellen (agentische Lückensuche)

Neben Data Lakes (lokal/SQL/S3) können **proprietäre Systeme** als Connector vom Typ `rest`
angebunden werden. Der `GapSearchAgent` durchsucht sie nach den Lücken aus `gaps.json`
(fehlende Profil-Felder, fehlende Unterlagen), trägt gefundene Werte ins Profil ein
(`out/gap_evidence.json` protokolliert jeden Treffer mit Quelle/URL), und die Pipeline
matcht danach erneut.

| System | Anbindung | Auth (nur Env, nie in Config) |
|---|---|---|
| **SAP HANA** (ERP) | `type: sql` mit `url: env:FOERDERPILOT_HANA_URL` (`hana+hdbcli://...`, Extra: `pip install hdbcli`) | DB-User/Pass in der URL-Env |
| **Databricks** | `type: sql` (`databricks+connector://...` am SQL Warehouse) oder `preset: databricks` (REST-Übersicht) | Env |
| **Jira** | `preset: jira` | `env:JIRA_USER` + `env:JIRA_TOKEN` (Basic) |
| **Outlook / M365** | `preset: graph` (Microsoft Graph `/me/messages`) | `env:GRAPH_TOKEN` (Bearer) |
| **Power BI** | `preset: powerbi` | `env:POWERBI_TOKEN` (Bearer, Azure AD) |
| **Polarion, Planisware (OPX), Hebbia, Facton, Serdia, eigene SaaS** | `preset: generic` + eigene Pfade in der Config (`datasets_path`, `search_path` mit `{q}`/`{limit}`) | `env:…` (Bearer/Basic) |

```yaml
connectors:
  - type: sql
    name: sap_hana
    url: env:FOERDERPILOT_HANA_URL
  - type: rest
    name: jira
    preset: jira
    base_url: env:JIRA_BASE_URL
    auth: {scheme: basic, user: env:JIRA_USER, password: env:JIRA_TOKEN}
  - type: rest
    name: outlook
    preset: graph
    auth: {scheme: bearer, token: env:GRAPH_TOKEN}
  - type: rest
    name: polarion
    preset: generic
    base_url: env:POLARION_BASE_URL
    auth: {scheme: bearer, token: env:POLARION_TOKEN}
    datasets_path: /rest/v1/projects/{project}/workitems
    search_path: /rest/v1/workitems?query={q}
```

Alle REST-Connectoren landen automatisch im Katalog (Profil-Extraktion läuft auch über sie)
und stehen dem `GapSearchAgent` per `search()` zur Verfügung. Token landen nie in Logs/Outputs.

### SQL-Connector: Voraussetzungen & Berechtigungs-Pfad (key user ohne Admin-Rechte)

**Technisch nötig:** (1) Netzwerk-Route zum DB-Port (HANA `3xx15`, meist nur intern/VPN; Databricks 443),
(2) Treiber lokal: `pip install foerderpilot[sql]` + `hdbcli` (HANA) bzw. `databricks-sql-connector`,
(3) **read-only DB-Account** mit `SELECT` auf die relevanten Schemas + Katalog-Leserechten.

**Berechtigung:** Als key user schaltest du das nicht selbst frei (`GRANT` darf nur DBA/Schema-Owner) –
aber du brauchst auch keinen Admin bei dir, sondern ein Standard-Ticket, z. B.:

> „Bitte dedizierten read-only Service-Account anlegen (oder meinem User lesend gewähren):
> `SELECT` auf Schemas `SAPABAP1`, `<BW-Schema>` und `CATALOG READ`. Kein Schreibzugriff, kein DDL.
> Zweck: automatisierte Förderprogramm-Recherche (foerderpilot), nur lesend. DSVO: AVV vorhanden."

HANA-Beispiele (führt der DBA aus):

```sql
CREATE USER FOERDERPILOT_RO PASSWORD "..." CHANGE PASSWORD ON NEXT LOGON? NO;
GRANT SELECT ON SCHEMA SAPABAP1 TO FOERDERPILOT_RO;
GRANT SELECT ON SCHEMA _SYS_BIC TO FOERDERPILOT_RO;   -- BW-Content
GRANT CATALOG READ TO FOERDERPILOT_RO;                -- information_schema/Spalten-Katalog
-- Kerberos/X.509 statt Passwort: siehe Doku-Abschnitt „SSO"
```

**Headless-SSO statt Passwort** (kein Langzeit-Secret in der URL): Kerberos/SPNEGO (kinit-Ticket aus deinem AD-SSO),
X.509-Client-Zertifikat (mTLS, Zertifikat auf HANA-User gemappt) oder OAuth2/JWT über SAP IAS (kurzlebige Tokens).
Details/Implementierung im SQL-Connector: geplant als `auth:`-Modi `kerberos` / `x509` / `oauth_jwt` (alles über Env-Vars).

**Admin-freier Pfad (kein DBA-Ticket nötig):** SAP-GUI-Extraktion mit deinen normalen Rechten –
`foerderpilot sap-guide --goal "…" [--domain co|bw|fi|sd|mm]` souffliert TCode/Menü/Export (SE16N braucht nur
`S_TABU_DIS` auf die jeweilige Tabelle, das haben key user oft), Datei landet in `<lake-root>/sap_exports/`
und wird vom Explorer automatisch eingelesen. Gleiches gilt für ALV-Exporte von Standardberichten und
BW-Query-Exporte (RSA3/RSRT), die du mit Berichtsrechten eh ausführen darfst.

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
- `gaps.json`, `gap_evidence.json` – Lücken + Treffer aus proprietären Quellen
- `emails.json`, `emails/*.md` – Klärungs-Mail-Entwürfe (extern Förderstelle, intern Wissensträger)
- `coverage.json` – Coverage-Report: alle Inputs beider Seiten mit Status ok/override/offen
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
