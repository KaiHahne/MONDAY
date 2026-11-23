from __future__ import annotations

import io
import json
import os

import pandas as pd

from foerderpilot.connectors.base import DataLakeConnector, DatasetRef

S3_SUFFIXES = {".csv", ".json", ".jsonl", ".parquet"}


class S3Connector:
    """Data-Lake-Connector fuer S3-kompatible Object Stores (AWS S3, MinIO, ...).

    Zugangsdaten werden ausschliesslich aus der Umgebung gelesen
    (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN oder
    FOERDERPILOT_S3_ACCESS_KEY / FOERDERPILOT_S3_SECRET_KEY), nie aus Config-Dateien.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str | None = None,
        name: str = "s3",
    ):
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "S3-Support fehlt: bitte 'pip install foerderpilot[s3]' (boto3) installieren."
            ) from exc
        client_kwargs: dict = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if region:
            client_kwargs["region_name"] = region
        access_key = os.environ.get("FOERDERPILOT_S3_ACCESS_KEY") or os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("FOERDERPILOT_S3_SECRET_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
            session_token = os.environ.get("FOERDERPILOT_S3_SESSION_TOKEN") or os.environ.get("AWS_SESSION_TOKEN")
            if session_token:
                client_kwargs["aws_session_token"] = session_token
        self._s3 = boto3.client("s3", **client_kwargs)
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.name = name

    def _full_prefix(self) -> str:
        return f"{self.prefix}/" if self.prefix else ""

    def list_datasets(self) -> list[DatasetRef]:
        refs = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._full_prefix()):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                suffix = "." + key.rsplit(".", 1)[-1].lower() if "." in key else ""
                if suffix in S3_SUFFIXES:
                    name = key[len(self._full_prefix()):].rsplit(".", 1)[0]
                    refs.append(
                        DatasetRef(
                            connector=self.name,
                            name=name,
                            format=suffix.lstrip("."),
                            extra={"key": key, "size_bytes": obj.get("Size", 0)},
                        )
                    )
        return sorted(refs, key=lambda r: r.name)

    def read_dataset(self, ref: DatasetRef, max_rows: int | None = None) -> pd.DataFrame:
        obj = self._s3.get_object(Bucket=self.bucket, Key=ref.extra["key"])
        payload = obj["Body"].read()
        fmt = ref.format
        if fmt == "csv":
            df = pd.read_csv(io.BytesIO(payload))
        elif fmt == "jsonl":
            df = pd.read_json(io.BytesIO(payload), lines=True)
        elif fmt == "json":
            data = json.loads(payload.decode("utf-8"))
            if isinstance(data, dict):
                data = data.get("records", [data])
            df = pd.DataFrame(data)
        elif fmt == "parquet":
            try:
                df = pd.read_parquet(io.BytesIO(payload))
            except ImportError as exc:
                raise ImportError(
                    "Parquet-Support fehlt: bitte 'pip install foerderpilot[parquet]' (pyarrow) installieren."
                ) from exc
        else:
            raise ValueError(f"Nicht unterstuetztes Format: {fmt}")
        if max_rows is not None:
            df = df.head(max_rows)
        return df
