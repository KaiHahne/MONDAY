from __future__ import annotations

import pandas as pd
from sqlalchemy import create_engine, inspect

from foerderpilot.connectors.base import DataLakeConnector, DatasetRef


class SQLConnector:
    """Data-Lake-Connector fuer relationale Datenbanken via SQLAlchemy."""

    def __init__(self, url: str, name: str = "sql", schema: str | None = None):
        try:
            self._engine = create_engine(url)
        except ImportError as exc:
            raise ImportError(
                "SQL-Support fehlt: bitte 'pip install foerderpilot[sql]' (SQLAlchemy) installieren."
            ) from exc
        self.name = name
        self.schema = schema
        self._inspector = inspect(self._engine)

    def list_datasets(self) -> list[DatasetRef]:
        tables = self._inspector.get_table_names(schema=self.schema)
        refs = []
        for table in sorted(tables):
            try:
                rows = self._inspector.get_columns(table, schema=self.schema)
                columns = [c["name"] for c in rows]
            except Exception:
                columns = []
            refs.append(
                DatasetRef(
                    connector=self.name,
                    name=table,
                    format="sql_table",
                    extra={"schema": self.schema, "columns": columns},
                )
            )
        return refs

    def read_dataset(self, ref: DatasetRef, max_rows: int | None = None) -> pd.DataFrame:
        query = f'SELECT * FROM "{ref.name}"'
        if max_rows is not None:
            dialect = self._engine.dialect.name
            if dialect in ("postgresql", "mysql", "sqlite"):
                query += f" LIMIT {int(max_rows)}"
            elif dialect == "mssql":
                query = f"SELECT TOP {int(max_rows)} * FROM \"{ref.name}\""
            else:
                query += f" LIMIT {int(max_rows)}"
        return pd.read_sql(query, self._engine)
