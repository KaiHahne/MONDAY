import json

import pandas as pd
import pytest

from foerderpilot.catalog import DataCatalog
from foerderpilot.connectors.factory import build_connectors
from foerderpilot.connectors.local import LocalFileConnector
from foerderpilot.profile import extract_profile


@pytest.fixture()
def lake(tmp_path):
    stammdaten = tmp_path / "stammdaten.csv"
    pd.DataFrame(
        [
            {
                "firma": "Muster GmbH",
                "rechtsform": "GmbH",
                "land": "DE",
                "bundesland": "BY",
                "branche": "Maschinenbau",
                "mitarbeiter": 120,
                "umsatz": "12.500.000",
                "gruendungsjahr": 1998,
            }
        ]
    ).to_csv(stammdaten, index=False)
    kennzahlen = tmp_path / "kennzahlen.json"
    kennzahlen.write_text(
        json.dumps(
            [
                {"kennzahl": "investitionsbetrag", "wert": "250000"},
                {"kennzahl": "vorhaben", "wert": "Digitalisierung der Fertigung"},
                {"kennzahl": "energieverbrauch", "wert": 900000},
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "unrelated.parquet").parent.mkdir(exist_ok=True)
    pd.DataFrame({"x": [1, 2, 3]}).to_parquet(tmp_path / "unrelated.parquet")
    return tmp_path


def test_local_connector_lists_and_reads(lake):
    conn = LocalFileConnector(lake)
    refs = conn.list_datasets()
    names = {r.name for r in refs}
    assert {"stammdaten", "kennzahlen", "unrelated"} <= names
    df = conn.read_dataset(next(r for r in refs if r.name == "stammdaten"))
    assert list(df.columns)[0] == "firma"
    df_limited = conn.read_dataset(next(r for r in refs if r.name == "unrelated"), max_rows=2)
    assert len(df_limited) == 2


def test_factory_builds_local(lake):
    connectors = build_connectors([{"type": "local", "root": str(lake), "name": "lake_lokal"}])
    assert connectors[0].name == "lake_lokal"


def test_factory_rejects_unknown_type():
    with pytest.raises(ValueError):
        build_connectors([{"type": "ftp"}])


def test_factory_env_secret_resolution(monkeypatch):
    monkeypatch.setenv("MY_DB_URL", "sqlite:///:memory:")
    connectors = build_connectors([{"type": "sql", "url": "env:MY_DB_URL"}])
    assert connectors[0].name == "sql"


def test_factory_env_secret_missing(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(KeyError):
        build_connectors([{"type": "sql", "url": "env:MISSING_VAR"}])


def test_profile_extraction_from_lake(lake):
    connectors = build_connectors([{"type": "local", "root": str(lake)}])
    catalog = DataCatalog(sample_rows=10).build(connectors)
    profile = extract_profile(catalog, overrides={"hq_country": "DE"})
    assert profile["company_name"] == "Muster GmbH"
    assert profile["hq_country"] == "DE"
    assert profile["hq_state"] == "BY"
    assert profile["employees"] == 120
    assert profile["revenue_eur"] == 12500000
    assert profile["founded_year"] == 1998
    assert profile["investment_amount_eur"] == 250000
    assert "Digitalisierung" in profile["purpose"]
    assert profile["energy_consumption_kwh"] == 900000
    assert profile["_sources"]


def test_sql_connector_sqlite(tmp_path):
    db = tmp_path / "lake.db"
    df = pd.DataFrame([{"firma": "SQL GmbH", "mitarbeiter": 42, "land": "DE"}])
    engine_url = f"sqlite:///{db}"
    import sqlalchemy

    df.to_sql("stammdaten", sqlalchemy.create_engine(engine_url), index=False)
    connectors = build_connectors([{"type": "sql", "url": engine_url}])
    catalog = DataCatalog().build(connectors)
    assert [d.ref.name for d in catalog.datasets] == ["stammdaten"]
    profile = extract_profile(catalog)
    assert profile["company_name"] == "SQL GmbH"
    assert profile["employees"] == 42
