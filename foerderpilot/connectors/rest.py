from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pandas as pd

from foerderpilot.connectors.base import DatasetRef
from foerderpilot.connectors.presets import PRESETS


def _dig(obj: Any, path: str | None) -> Any:
    """Dotted-Path-Zugriff ('fields.summary'); None/leer -> obj bzw. None."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _flatten(obj: Any, prefix: str = "", depth: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if depth > 4:
        return {prefix.rstrip("_"): json.dumps(obj, ensure_ascii=False, default=str)[:500]}
    if isinstance(obj, dict):
        for key, val in obj.items():
            out.update(_flatten(val, f"{prefix}{key}_", depth + 1))
    elif isinstance(obj, list):
        out[prefix.rstrip("_")] = json.dumps(obj, ensure_ascii=False, default=str)[:2000]
    else:
        out[prefix.rstrip("_")] = obj
    return out


class RestConnector:
    """Generischer REST-Connector fuer proprietäre Systeme (Jira, Outlook/Graph, Power BI, ...).

    Authentifizierung ausschliesslich ueber Umgebungsvariablen (Config: env:VAR_NAME),
    Token werden nie geloggt. Nutzt das DataLakeConnector-Protokoll (Katalog) plus
    search() fuer den GapSearchAgent.
    """

    def __init__(
        self,
        name: str,
        preset: str,
        base_url: str,
        auth: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ):
        if preset not in PRESETS:
            raise ValueError(f"Unbekanntes REST-Preset {preset!r} (bekannt: {sorted(PRESETS)})")
        self.name = name
        self.preset_name = preset
        self.spec = {**PRESETS[preset], **(params or {})}
        base = base_url or self.spec.get("base_url_default")
        if not base:
            raise ValueError(f"REST-Connector {name!r}: base_url fehlt (Preset {preset!r} hat keine Default-URL).")
        self.base_url = base.rstrip("/")
        self.auth = auth or {"scheme": self.spec.get("auth", "none")}
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "foerderpilot/0.1"}
        scheme = str(self.auth.get("scheme", "none")).lower()
        if scheme == "bearer":
            headers["Authorization"] = f"Bearer {self.auth.get('token', '')}"
        elif scheme == "basic":
            raw = f"{self.auth.get('user', '')}:{self.auth.get('password', '')}"
            headers["Authorization"] = "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return headers

    def _fmt(self, template: str, q: str = "", limit: int = 5) -> str:
        values = {k: str(v) for k, v in self.spec.items() if isinstance(v, (str, int)) and not k.endswith(("_path", "_list"))}
        values.update({"base": self.base_url, "q": urllib.parse.quote(q), "limit": limit})
        return template.format(**values)

    def _get(self, path: str) -> Any:
        url = path if path.startswith("http") else self.base_url + path
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"REST-Fehler {exc.code} von {self.name} ({url.split('?')[0]})") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{self.name} nicht erreichbar: {exc.reason}") from exc

    # --- DataLakeConnector-Protokoll ---
    def list_datasets(self) -> list[DatasetRef]:
        path = self.spec.get("datasets_path")
        if not path:
            return []
        return [
            DatasetRef(
                connector=self.name,
                name=f"{self.preset_name}",
                format="rest_json",
                extra={"path": self._fmt(path), "list": self.spec.get("datasets_list")},
            )
        ]

    def read_dataset(self, ref: DatasetRef, max_rows: int | None = None) -> pd.DataFrame:
        data = self._get(ref.extra["path"])
        items = _dig(data, ref.extra.get("list")) or []
        df = pd.DataFrame([_flatten(item) for item in items])
        return df.head(max_rows) if max_rows is not None else df

    # --- GapSearch ---
    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        path = self.spec.get("search_path")
        if not path:
            return []
        data = self._get(self._fmt(path, q=query, limit=limit))
        items = _dig(data, self.spec.get("search_list")) or []
        item_map = self.spec.get("item", {})
        hits = []
        for item in items[:limit]:
            item_id = _dig(item, item_map.get("id", "id"))
            url = str(item_map.get("url", "")).replace("{base}", self.base_url)
            for token in ("id", "key"):
                url = url.replace("{" + token + "}", str(item_id or ""))
            hits.append(
                {
                    "id": str(item_id or ""),
                    "title": str(_dig(item, item_map.get("title", "title")) or ""),
                    "url": url,
                    "snippet": str(_dig(item, item_map.get("text", "description")) or "")[:800],
                }
            )
        return hits
