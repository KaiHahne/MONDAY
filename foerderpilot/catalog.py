from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from foerderpilot.connectors.base import DataLakeConnector, DatasetRef


@dataclass
class DatasetInfo:
    ref: DatasetRef
    row_count: int | None
    columns: list[str]
    dtypes: dict[str, str] = field(default_factory=dict)
    sample: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector": self.ref.connector,
            "name": self.ref.name,
            "format": self.ref.format,
            "row_count": self.row_count,
            "columns": self.columns,
            "dtypes": self.dtypes,
            "sample": self.sample,
            **({"extra": self.ref.extra} if self.ref.extra else {}),
        }


class DataCatalog:
    """Katalog aller in den Data Lakes gefundenen Datasets inkl. Schema-Probe."""

    def __init__(self, sample_rows: int = 5):
        self.sample_rows = sample_rows
        self.datasets: list[DatasetInfo] = []

    def build(self, connectors: list[DataLakeConnector]) -> "DataCatalog":
        self.datasets = []
        for connector in connectors:
            for ref in connector.list_datasets():
                df = connector.read_dataset(ref, max_rows=self.sample_rows + 1)
                row_count = None if len(df) <= self.sample_rows else len(df)
                sample = df.head(self.sample_rows)
                self.datasets.append(
                    DatasetInfo(
                        ref=ref,
                        row_count=row_count if row_count is not None else len(df),
                        columns=[str(c) for c in df.columns],
                        dtypes={str(c): str(t) for c, t in df.dtypes.items()},
                        sample=sample.to_dict(orient="records"),
                    )
                )
        return self

    def find(self, name_contains: str) -> list[DatasetInfo]:
        needle = name_contains.lower()
        return [d for d in self.datasets if needle in d.ref.name.lower()]

    def to_dict(self) -> dict[str, Any]:
        return {"dataset_count": len(self.datasets), "datasets": [d.to_dict() for d in self.datasets]}
