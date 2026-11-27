# Entwickler-Doku: foerderpilot

Interne Doku für Entwicklerinnen/Entwickler, die am Tool selbst arbeiten.
Nutzer-Doku siehe [README.md](../README.md), lauffähiges Beispiel siehe [examples/README.md](../examples/README.md).

## 1. Was das Tool tut ( fachlich )

Multi-Agent-Pipeline: Data Lakes eines Unternehmens werden durchsucht, daraus wird ein
Unternehmensprofil destilliert, dieses wird gegen maschinenlesbare Förderprogramm-Regeln
gematcht, und per LLM werden Antragsentwürfe für die besten Matches geschrieben.

## 2. Architektur

```
config.yaml ──► load_config() ──► AgentContext (geteilt, wird sequenziell befüllt)
                                        │
   Orchestrator ──► DataLakeExplorerAgent ──► connectors/* ──► DataCatalog ──► profile
                        │                        (local / sql / s3)        (profile.py)
                        ├─► ProgramMatcherAgent ──► programs/loader.py ──► programs/matcher.py
                        │                        (JSON/YAML-Regeln)        (Regel-Engine, Ranking)
                        └─► ApplicationWriterAgent ──► llm/client.py ──► out/applications/*.md
                                        │
                              pipeline.run_pipeline() schreibt out/: catalog/profile/matches/applications/trace
                              web/server.py exponiert das als Web-UI (Bearer-Token, Loopback-Default)
```

Kernprinzipien:

- **Agenten sind klein und austauschbar**: Basisklasse `Agent` (`agents/base.py`), Methode
  `run(context)`. Alle Agenten teilen einen `AgentContext` und loggen jeden Schritt als
  `AgentEvent` – daraus entsteht `out/trace.json` (Audit-Trail).
- **Matching ist deterministisch** (reine Regel-Engine, kein LLM). Das LLM wird nur im
  Writer für Antragstext genutzt.
- **Keine Secrets im Code/Repo**: LLM-Key nur aus `FOERDERPILOT_LLM_API_KEY` zur Laufzeit,
  Web-Token nur aus `FOERDERPILOT_WEB_TOKEN`, S3-Creds nur aus `AWS_*`/`FOERDERPILOT_S3_*`,
  DB-URL in der Config nur als `env:VAR`-Referenz (wird von `config.py` abgelehnt, wenn
  Klartext).

## 3. Projektstruktur

```
foerderpilot/
  cli.py                  # argparse: run | serve | init | import-programs
  config.py               # YAML-Config laden, Defaults, Secret-Check, Pfade relativ zur Config
  pipeline.py             # run_pipeline(): Orchestrator + Schreiben von out/*.json
  orchestrator.py         # führt Agenten sequenziell aus, Trace
  catalog.py              # DataCatalog: Datasets + Schema-Probe pro Connector
  profile.py              # Profil-Extraktion (FIELD_ALIASES, KV-Tabellen, DE/EN-Zahlen)
  connectors/             # base (Protocol + DatasetRef), local, sql, s3, rest (Presets), factory, presets.py
  programs/
    models.py             # FundingProgram (inkl. contact), Criterion (validate())
    loader.py             # JSON/YAML laden + validieren (ProgramValidationError)
    matcher.py            # OPERATORS, evaluate_criterion, match_program, rank_matches
    importer.py           # CSV/JSON-Export -> programs/<id>.json (import-programs)
  research/               # backend.py (SearchBackend: static/ddg, fetch_text), agent.py (research_programs -> Drafts)
  sap/                    # runbook.yaml (Rezepte + automation-Blöcke), guide.py (Souffleur), automation.py (Renderer: actions/pad/vba)
  llm/client.py           # LLMClient-Protokoll + OpenAICompatibleClient (env-basiert)
  agents/                 # base, explorer, matcher, gap, gapsearch, clarification, writer
  web/                    # server.py (stdlib http.server, Bearer-Token), index.html (mobil)
programs/                 # Beispiel-Regeln (BAFA, KfW, ZIM) – vom Nutzer gepflegt
examples/                 # lauffaehiges Data-Lake-Beispiel + Export-Beispiele
tests/                    # pytest: matcher, connectors/profile, config, llm (Loopback), pipeline, web, importer
docs/                     # diese Doku
```

## 4. Datenfluss im Detail

1. `load_config()` liest YAML, füllt Defaults (`connectors`, `programs_dir`, `output_dir`,
   `sample_rows`, `max_applications`, `profile_overrides`), löst relative Pfade gegen das
   Config-Verzeichnis auf und lehnt Klartext-Secrets ab.
2. `DataLakeExplorerAgent`: `build_connectors()` erzeugt Connectoren aus der Config
   (`type: local|sql|s3`). `DataCatalog.build()` listet Datasets und liest je `sample_rows`
   Zeilen. `extract_profile()` destilliert das Profil: Stammdaten-Tabellen (Name enthält
   `stammdaten`/`firma`/`company`/… oder ≥2 bekannte Spalten) + Key-Value-Tabellen
   (`kennzahl`/`wert`-Paare). Overrides aus der Config gewinnen.
3. `ProgramMatcherAgent`: `load_programs(programs_dir)` → `rank_matches(profile, programs)`.
   Eligibility = alle `required`-Kriterien erfüllt; Score = Summe der Gewichte erfüllter
   Kriterien; Sortierung: eligible zuerst, dann Score.
4. `ApplicationWriterAgent`: für die Top-`max_applications` eligible Matches je ein
   LLM-Call (Prompt = Programm-JSON + Profil + erfüllte Kriterien + Dataset-Stichproben);
   Ergebnis: `out/applications/<id>.md`.
5. `run_pipeline()` schreibt `catalog.json`, `profile.json`, `matches.json`,
   `applications.json`, `trace.json` nach `output_dir`.

## 5. Erweiterungspunkte (How to extend)

### Neuen Data-Lake-Connector hinzufügen
1. Klasse mit `name`, `list_datasets() -> list[DatasetRef]`,
   `read_dataset(ref, max_rows=None) -> pd.DataFrame` in `connectors/` anlegen
   (siehe `local.py` als Referenz; `DatasetRef.extra` für interne Infos wie Pfad/Key).
2. In `connectors/factory.py: build_connectors()` registrieren (`type: "adls"` o. ä.).
3. Optionale Dependency als Extra in `pyproject.toml` (z. B. `adls = ["adfs…"]`), nie in
   die Core-Deps.
4. Test in `tests/test_connectors_profile.py` (Fixture-Lake im tmp_path).

### Neues Profil-Feld
`FIELD_ALIASES` in `profile.py` erweitern (kanonischer Feldname → DE/EN-Spalten-Aliase).
Danach kann es in Programm-Kriterien als `field` genutzt werden. Test in
`test_connectors_profile.py` nachziehen.

### Neuen Matching-Operator
`OPERATORS` in `programs/matcher.py` um `"op_name": funktion(actual, value)` ergänzen,
dazu `VALID_OPS` in `models.py` – sonst lehnt der Loader/Validator den Op ab.
Test in `test_matcher.py`.

### Neuen Agenten
Von `agents/base.py: Agent` erben, `name` setzen, `run(context)` implementieren
(`context.log(...)` nicht vergessen). In `pipeline.run_pipeline()` an der passenden
Stelle in die Agentenliste einreihen. Der Orchestrator zeichnet alles automatisch mit.

### Anderen LLM-Anbieter / lokal
`llm/client.py` implementiert `LLMClient` (Methode `complete(system, prompt, …)`).
Einfach eine weitere Klasse gegen das `LLMClient`-Protokoll und in `run_pipeline(config,
llm_client=…)` injizieren – so machen es auch die Tests (`FakeLLMClient`). Für
`foerderpilot run` reicht es, `FOERDERPILOT_LLM_BASE_URL`/`FOERDERPILOT_LLM_MODEL` zu setzen
(jeder OpenAI-kompatible `/chat/completions`-Endpoint, z. B. Mistral, vLLM, Ollama).

### Research-Agent erweitern
`research/agent.py: research_programs()` läuft pro Ebene (`eu/bund/land/gemeinde`) × Topic:
Suche (`SearchBackend`) → Seite fetchen (`fetch_text`) → LLM extrahiert Programm-Cards als JSON
(`extract_program_cards`) → Draft nach `programs/research/<ebene>-<id>.json` mit `status: "draft"`,
`source_url`, `contact`. Drafts werden NICHT automatisch gematcht – Review + `mv` nach `programs/`.
Neues Such-Backend: `SearchBackend`-Protokoll in `research/backend.py` implementieren und in
`build_backend()` registrieren. Tests: `StaticBackend` + Loopback-HTTP-Server + FakeLLM
(siehe `tests/test_research.py`).

### Proprietäre Quelle (REST) hinzufügen
Preset in `connectors/presets.py` anlegen (auth-Scheme, datasets/search-Pfade mit `{q}`/`{limit}`,
Item-Mapping als Dotted Paths) oder `preset: generic` mit eigenen Pfaden in der Config nutzen.
SAP HANA / Databricks-SQL-Warehouses / Planisware-DB gehen über den bestehenden `sql`-Connector
(`hana+hdbcli://…`, `databricks+connector://…`). Auth immer `env:VAR` – `_resolve_secret` in
`factory.py` löst zur Laufzeit auf. Tests mit Loopback-Fake-Server (siehe `tests/test_proprietary.py`).

### GapSearchAgent erweitern
`agents/gapsearch.py`: Wunschliste = Lücken aus `GapAnalysis` (Felder + Dokumente), pro Quelle
`search()` mit Feld-Aliasen, Werte per `extract_value()` (Regex `alias: wert`) ins Profil eintragen,
Evidence nach `context.evidence` → `out/gap_evidence.json`. Danach re-matched die Pipeline automatisch
(siehe Phasen in `pipeline.run_pipeline`).

### SAP-Runbook erweitern
Rezepte liegen in `foerderpilot/sap/runbook.yaml` (id, domain, keywords fürs Matching, tables, steps mit
tcode/menu/enter/expect/export, notes, drop_into, optional `automation` pro Rezept und pro Schritt).
Matching: `match_recipe()` (Keyword-Overlap + Domain-Bonus, Fallback auf `general`). REPL in
`run_interactive()` (next/back/switch/done). Intake-Ordner: `intake_dir_from_config()` =
erster local-Connector-root + `/sap_exports`. Tests: `tests/test_sap_guide.py`, `tests/test_sap_automation.py`.

### Automation-Renderer erweitern
`automation.py`: `render_actions()` baut die tool-neutrale Action-Sequenz (Launch + pro Schritt:
SendKeys/SetText/Automation/Export-Menü), `render_pad()` (Power-Automate-Desktop-JSON), `render_vba()`
(SAP-GUI-Scripting-Makro mit TODO-Platzhaltern für Feld-IDs). CLI: `--emit actions|pad|vba [--out DATEI]`.
Neue Action-Typen in `render_vba()` und `step_actions()` abbilden.

### Web-API erweitern
Neuer Endpunkt = weiterer `elif`-Zweig in `web/server.py: WebHandler.do_GET/do_POST`
(nach dem Auth-Check!). Programm-IDs/Dateinamen immer gegen Pfad-Traversal härten
(siehe `_APP_ID_RE`). Server läuft in Tests auf `127.0.0.1` mit Port 0 (siehe
`tests/test_web.py`).

### Import-Spalten erweitern
`DEFAULT_COLUMN_ALIASES` in `programs/importer.py` ergänzen oder eigenes Mapping per
`--mapping` übergeben. Kriterien-Syntax ist in `parse_criterion()` zentral geparst –
Änderungen dort wirken auf alle Imports.

## 6. Entwicklungsumgebung & Tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all,test]"      # all = sql + s3 + parquet
pytest                             # 33 Tests
foerderpilot run --config examples/config.yaml     # braucht FOERDERPILOT_LLM_API_KEY
foerderpilot serve --config examples/config.yaml   # braucht FOERDERPILOT_WEB_TOKEN, dann http://127.0.0.1:8000
```

Test-Konventionen:

- LLM wird nie echt angesprochen: `run_pipeline(config, llm_client=FakeLLMClient())`.
- LLM-HTTP-Pfad wird gegen einen lokalen `http.server`-Stub auf 127.0.0.1 getestet
  (`test_llm_client.py`); Web-UI ebenfalls nur Loopback (`test_web.py`).
- Jeder neue Codepfad braucht mindestens einen Test; Fixtures bauen Mini-Lakes in `tmp_path`.
- `pytest` muss grün sein vor jedem Commit.

## 7. Konventionen

- Sprache: Code/Bezeichner Englisch, Doku/CLI/Commit-Messages/UI Deutsch.
- Keine neuen Dependencies ohne Diskussion – Web-Layer und Kern bleiben stdlib-schlank
  (Core: nur `pandas` + `PyYAML`; sql/s3/parquet sind Extras).
- Secrets: nie in Code, Config, Commits, Logs oder Chat. Config erzwingt `env:`-Referenzen;
  `.env` ist gitignored. Bei geleaktem Key: sofort revoken.
- Pfade in der Config sind relativ zur Config-Datei.
- Commits klein und thematisch; Branch `vibe/<slug>-e226fc`, Push direkt auf den Branch
  (kein PR-Zwang, Repo-Default ist der Arbeits-Branch).
- Änderungen an der Kriterien-Syntax / am Profil-Schema sind breaking für bestehende
  `programs/*.json` – im Commit-Message und README vermerken.

## 8. CLI-Referenz (intern)

| Befehl | Zweck |
|---|---|
| `foerderpilot run --config C` | Pipeline einmalig ausführen → `out/` |
| `foerderpilot serve --config C [--host H] [--port P]` | Web-UI (Token-Pflicht, Default 127.0.0.1:8000) |
| `foerderpilot init --dir D` | Beispiel-Config + Beispiel-Programm anlegen |
| `foerderpilot import-programs --input E --out programs/ [--mapping M] [--force] [--dry-run]` | Förder-Export → Regeldateien |
| `foerderpilot research --config C [--levels eu,bund] [--max-per-level 5] [--out programs/research] [--use-lake-profile]` | Programme pro Verwaltungsebene recherchieren → Drafts |
| `foerderpilot sap-guide --goal "…" [--domain co|bw|fi|sd|mm|general] [--batch] [--list] [--runbook R]` | Souffleur: SAP-Extraktionsschritte ausgeben (interaktiv oder Batch) |

## 9. Häufige Stolpersteine

- `run` bricht mit `LLMError: FOERDERPILOT_LLM_API_KEY …` ab → Key nicht exportiert (nur der
  Writer braucht ihn; Explorer/Matcher laufen ohne).
- Profil-Feld fehlt im Match → Spalte ergänzen (`FIELD_ALIASES`) oder Wert per
  `profile_overrides` in der Config nachtragen; Quellen stehen in `profile.json` unter `_sources`.
- Programm wird nicht eligible → in `matches.json` steht pro Kriterium `actual` (Ist-Wert)
  neben dem Soll – so sieht man sofort, welches Kriterium nicht greift.
- Web-UI meldet 401 → Token falsch oder `FOERDERPILOT_WEB_TOKEN` auf Server-Seite nicht gesetzt.
