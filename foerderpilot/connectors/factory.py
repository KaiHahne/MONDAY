from __future__ import annotations

import os
from typing import Any

from foerderpilot.connectors.base import DataLakeConnector


def _resolve_secret(value: str) -> str:
    """Erlaubt 'env:VAR_NAME' in der Config – der Wert wird zur Laufzeit aus der Umgebung gelesen."""
    if isinstance(value, str) and value.startswith("env:"):
        var = value[4:]
        resolved = os.environ.get(var)
        if resolved is None:
            raise KeyError(f"Umgebungsvariable '{var}' ist nicht gesetzt (in Config als env:{var} referenziert).")
        return resolved
    return value


def build_connectors(configs: list[dict[str, Any]]) -> list[DataLakeConnector]:
    """Erzeugt Connector-Instanzen aus der Config-Liste."""
    connectors: list[DataLakeConnector] = []
    for cfg in configs:
        cfg = dict(cfg)
        ctype = cfg.pop("type", None)
        if ctype == "local":
            from foerderpilot.connectors.local import LocalFileConnector

            connectors.append(LocalFileConnector(root=cfg.pop("root"), name=cfg.pop("name", "local")))
        elif ctype == "sql":
            from foerderpilot.connectors.sql import SQLConnector

            url = _resolve_secret(cfg.pop("url"))
            connectors.append(SQLConnector(url=url, name=cfg.pop("name", "sql"), schema=cfg.pop("schema", None)))
        elif ctype == "s3":
            from foerderpilot.connectors.s3 import S3Connector

            connectors.append(
                S3Connector(
                    bucket=cfg.pop("bucket"),
                    prefix=cfg.pop("prefix", ""),
                    endpoint_url=cfg.pop("endpoint_url", None),
                    region=cfg.pop("region", None),
                    name=cfg.pop("name", "s3"),
                )
            )
        else:
            raise ValueError(f"Unbekannter Connector-Typ: {ctype!r} (erwartet: local, sql, s3)")
        if cfg:
            raise ValueError(f"Unbekannte Connector-Optionen: {sorted(cfg)}")
    return connectors
