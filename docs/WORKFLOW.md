# Gesamtsequenz: Research → Import → Lake → Lückensuche → Match → Klärung → Antrag

## Sequenzdiagramm

```mermaid
sequenceDiagram
    autonumber
    participant U as Nutzer
    participant CLI as foerderpilot CLI
    participant R as Research-Agent
    participant P as Pipeline (Agenten-Kette)
    participant L as Data Lake / proprietäre Systeme (local, SQL/HANA, S3, REST: Jira, Outlook, Power BI …)
    participant LLM as LLM (OpenAI-kompatibel, z. B. Mistral)
    U->>CLI: foerderpilot research --config C --levels eu,bund,land,gemeinde [--use-lake-profile]
    CLI->>R: pro Ebene × Topic: Websuche (ddg/static) → Seite fetchen
    R->>LLM: Seite → Programm-Cards (Kriterien, Formalismen, contact)
    R-->>U: programs/research/*.json (status: draft) + research-report.json
    U->>U: Review der Drafts, dann: mv programs/research/x.json programs/
    Note over U,CLI: alternativ: foerderpilot import-programs --input export.csv --out programs/
    U->>CLI: foerderpilot run --config C   (oder: foerderpilot serve + Web-UI → POST /api/run)
    CLI->>P: Phase 1 Explorer: connectors lesen → catalog.json, profile.json
    P->>L: lesen (Dateien/DB/S3/REST)
    P->>P: Phase 2 Matcher: programs/*.json × Profil → matches.json (eligible/score, passed/failed)
    P->>P: Phase 3 GapAnalysis → gaps.json (fehlende Felder/Unterlagen/kein Kontakt)
    P->>L: Phase 4 GapSearch: gezielte Suche in REST-Quellen → gap_evidence.json, Profil-Update
    P->>P: falls Profil gefüllt: Re-Match + Re-Gap
    P->>LLM: Phase 5 Clarification (optional): extern an contact.email (Anrede mit contact.stelle) + intern an Wissensträger → out/emails/<id>.md + internal-wissenstraeger.md + emails.json
    P->>LLM: Phase 6 Writer: Antrags-Entwürfe → out/applications/<id>.md + applications.json
    P->>P: Phase 7 Coverage → out/coverage.json (alle Inputs: ok/override/offen, programm- wie unternehmensseitig)
    P-->>U: out/ (catalog, profile, matches, gaps, gap_evidence, emails, applications, coverage, trace)
    Note over U: Klärungs-Mails manuell prüfen/senden; Anträge reviewen
```

## Schritt-Tabelle: Befehl, Inputs, Outputs

| # | Schritt | Befehl | Inputs (Voraussetzungen) | Outputs |
|---|---|---|---|---|
| 0 | Setup | `pip install -e ".[all,test]"` | Python ≥3.10; Env: `FOERDERPILOT_LLM_API_KEY` (+ `…_BASE_URL`/`…_MODEL`), `FOERDERPILOT_WEB_TOKEN` (serve), Connector-Creds als Env (`env:`-Referenzen) | – |
| 1 | Research Förderprogramme (+Multi-Hop) | `foerderpilot research --config C [--levels …] [--max-per-level N] [--use-lake-profile]` | `config.research` (backend, levels, topics, query_template, sources, `link_follow.max_depth` für verlinkte PDFs/Seiten, robots/crawl/retry, PDF via `foerderpilot[pdf]`); LLM-Key | `programs/research/<ebene>-<id>.json` (Drafts mit criteria/contact/funding/`source_url`/`crawl_depth`) + `research-report.json` (inkl. `manual`-Liste) |
| 1b | Review + Freigabe | manuell: `mv programs/research/x.json programs/` | Mensch prüft Kriterien/Formalismen/Kontakt | aktive Regel in `programs/` |
| 1c | Import statt Research | `foerderpilot import-programs --input export.csv --out programs/ [--mapping M] [--force] [--dry-run]` | CSV/JSON-Export (Spalten-Aliase DE/EN, Kriterien-Syntax `field op value \| required=false \| weight=3`) | `programs/<id>.json` + JSON-Report (written/skipped/errors) |
| 2 | Manuelle SAP-Extraktion (Souffleur) | `foerderpilot sap-guide --goal "…" [--domain co\|bw\|…] [--batch] [--emit actions\|pad\|vba --out …]` | Runbook `foerderpilot/sap/runbook.yaml` (+ `automation:`-Blöcke); SAP-Zugang des Nutzers | Anleitung / PAD-Flow / VBA-Makro; Downloads landen in `<local-root>/sap_exports/` |
| 3 | Pipeline-Lauf | `foerderpilot run --config C` oder `foerderpilot serve --config C` → Web-UI → „Pipeline starten“ (`POST /api/run`) | `config.yaml`: connectors (local/sql/s3/rest), `programs_dir`, `output_dir`, `sample_rows`, `max_applications`, `profile_overrides`, `clarification:`; Data Lake gemäß [README](../README.md#proprietäre-Unternehmensquellen-agentische-lückensuche) | `out/catalog.json`, `out/profile.json` |
| 3a | Match | (in Lauf, Phase 2) | `programs/*.json` + Profil | `out/matches.json` (pro Programm: eligible, score, passed/failed mit Ist-Werten) |
| 3b | Lücken | (Phase 3) | matches + Katalog | `out/gaps.json` (missing_profile_field / failed_required_criterion / missing_document / no_contact) |
| 3c | Lückensuche in proprietären Systemen | (Phase 4) | REST-Connectoren mit `search()` (Jira/Graph/Power BI/generic) + Env-Token | `out/gap_evidence.json` (Quelle, Query, Hit/URL/Snippet); Profil ggf. gefüllt → Re-Match |
| 3d | Klärungs-Mails | (Phase 5, `clarification.enabled`) | eligible Matches mit Lücken + `contact.email` im Programm; LLM-Key | `out/emails/<id>.md` (An/Betreff/Text) + `out/emails.json` – **nur Entwürfe** |
| 3e | Anträge | (Phase 6) | eligible Matches, max. `max_applications`; LLM-Key | `out/applications/<id>.md` + `out/applications.json` |
| 3f | Audit | (immer) | – | `out/trace.json` (jeder Agentenschritt mit Zeitstempel) |
| 4 | Web-UI | `foerderpilot serve --config C [--host 127.0.0.1] [--port 8000]` | `FOERDERPILOT_WEB_TOKEN` (Bearer, Pflicht) | UI + API: `/api/status`, `/api/run`, `/api/matches`, `/api/gaps`, `/api/evidence`, `/api/emails[/<id>]`, `/api/applications[/<id>]`, `/api/trace` |

## Mindest-Inputs (Checkliste)

- [ ] `config.yaml` (von `foerderpilot init` oder `config.example.yaml`) mit mindestens einem Connector
- [ ] Data Lake erreichbar: lokal (Parquet/CSV/JSON unter `root`), SQL (`url: env:…`), S3, oder REST-Preset – **Stammdaten-Dataset + Kennzahlen-KV** mit den Feld-Aliasen aus `foerderpilot/profile.py`
- [ ] `programs/` gefüllt (Research-Drafts gereviewt oder `import-programs`)
- [ ] Env: `FOERDERPILOT_LLM_API_KEY` (+ Base/Model), ggf. `FOERDERPILOT_WEB_TOKEN`, Connector-Tokens – nie in Dateien committen
- [ ] Optional: `profile_overrides`/`profile_file` für Felder, die nirgendwo im System stehen

## Outputs (alles unter `out/` bzw. `programs/research/`)

| Datei | Inhalt |
|---|---|
| `catalog.json` | alle Datasets aller Quellen inkl. Schema-Probe |
| `profile.json` | extrahiertes Unternehmensprofil + `_sources`/`_evidence_sources` |
| `matches.json` | Ranking: eligible, score, erfüllte/fehlende Kriterien mit Ist-Werten |
| `gaps.json` | Lücken pro Programm |
| `gap_evidence.json` | Treffer aus proprietären Quellen (Jira/Outlook/…) mit URL/Snippet |
| `emails.json` + `emails/*.md` | Klärungs-Mail-Entwürfe an die recherchierte Stelle |
| `applications.json` + `applications/*.md` | fertige Antragsentwürfe (LLM) |
| `trace.json` | Audit-Trace aller Agenten |
| `coverage.json` | Coverage-Report: offene vs. identifizierte Inputs beider Seiten (Programmkriterien, Unterlagen, Kontakt, Profil-Felder) |
| `programs/research/*.json` + `research-report.json` | Research-Drafts (vor Review) |
