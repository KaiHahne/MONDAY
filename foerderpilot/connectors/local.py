from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from foerderpilot.connectors.base import DataLakeConnector, DatasetRef

SUPPORTED_SUFFIXES = {".csv", ".json", ".jsonl", ".parquet"}


class LocalFileConnector:
    """Data-Lake-Connector fuer ein lokales Verzeichnis (Parquet/CSV/JSON/JSONL)."""

    def __init__(self, root: str | Path, name: str = "local"):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"Lokaler Data-Lake-Pfad existiert nicht: {self.root}")
        self.name = name

    def _iter_files(self):
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                yield path

    def list_datasets(self) -> list[DatasetRef]:
        refs = []
        for path in self._iter_files():
            rel = path.relative_to(self.root).with_suffix("")
            refs.append(
                DatasetRef(
                    connector=self.name,
                    name=str(rel).replace("\\", "/"),
                    format=path.suffix.lower().lstrip("."),
                    extra={"path": str(path)},
                )
            )
        return refs

    def read_dataset(self, ref: DatasetRef, max_rows: int | None = None) -> pd.DataFrame:
        path = Path(ref.extra["path"])
        fmt = ref.format
        if fmt == "csv":
            df = pd.read_csv(path)
        elif fmt == "jsonl":
            df = pd.read_json(path, lines=True)
        elif fmt == "json":
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data = data.get("records", [data])
            df = pd.DataFrame(data)
        elif fmt == "parquet":
            try:
                df = pd.read_parquet(path)
            except ImportError as exc:
                raise ImportError(
                    "Parquet-Support fehlt: bitte 'pip install foerderpilot[parquet]' (pyarrow) installieren."
                ) from exc
        else:
            raise ValueError(f"Nicht unterstuetztes Format: {fmt}")
        if max_rows is not None:
            df = df.head(max_rows)
        return df
