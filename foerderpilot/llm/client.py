from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol, runtime_checkable

ENV_API_KEY = "FOERDERPILOT_LLM_API_KEY"
ENV_BASE_URL = "FOERDERPILOT_LLM_BASE_URL"
ENV_MODEL = "FOERDERPILOT_LLM_MODEL"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMClient(Protocol):
    """Schnittstelle fuer das LLM, das die Agenten nutzen."""

    def complete(self, system: str, prompt: str, *, temperature: float = 0.2, max_tokens: int = 4000) -> str:
        ...


class OpenAICompatibleClient:
    """Client fuer OpenAI-kompatible Chat-Completions-APIs.

    Der API-Key wird ausschliesslich zur Laufzeit aus der Umgebung gelesen
    (FOERDERPILOT_LLM_API_KEY) und niemals geloggt oder persistiert.
    """

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL, timeout: float = 120.0):
        if not api_key:
            raise LLMError(f"Kein API-Key uebergeben. Bitte {ENV_API_KEY} in der Umgebung setzen.")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        api_key = os.environ.get(ENV_API_KEY)
        if not api_key:
            raise LLMError(
                f"Umgebungsvariable {ENV_API_KEY} ist nicht gesetzt. "
                f"Optional: {ENV_BASE_URL} und {ENV_MODEL}."
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL),
            model=os.environ.get(ENV_MODEL, DEFAULT_MODEL),
        )

    def _build_payload(self, system: str, prompt: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }

    def complete(self, system: str, prompt: str, *, temperature: float = 0.2, max_tokens: int = 4000) -> str:
        url = f"{self.base_url}/chat/completions"
        body = json.dumps(self._build_payload(system, prompt, temperature, max_tokens)).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"LLM-API-Fehler (HTTP {exc.code}) bei {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"LLM-API nicht erreichbar ({url}): {exc.reason}") from exc
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unerwartete LLM-Antwort ohne choices[0].message.content: {str(payload)[:300]}") from exc
