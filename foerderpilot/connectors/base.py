from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class DatasetRef:
    """Eindeutige Referenz auf ein Dataset innerhalb eines Connectors."""

    connector: str
    name: str
    format: str
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DataLakeConnector(Protocol):
    """Schnittstelle fuer einen Data-Lake-Zugang (lokal, SQL, S3, ...)."""

    name: str

    def list_datasets(self) -> list[DatasetRef]:
        """Listet alle erreichbaren Datasets auf."""
        ...

    def read_dataset(self, ref: DatasetRef, max_rows: int | None = None) -> pd.DataFrame:
        """Liest ein Dataset als DataFrame (optional auf max_rows begrenzt)."""
        ...
