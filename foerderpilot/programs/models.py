from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_OPS = {"==", "!=", ">=", "<=", ">", "<", "in", "not_in", "contains", "exists"}


@dataclass(frozen=True)
class Criterion:
    """Ein einzelnes Foerderkriterium gegen das Unternehmensprofil.

    field:    Schluessel im Profil (z. B. 'employees', 'hq_country')
    op:       einer von ==, !=, >=, <=, >, <, in, not_in, contains, exists
    value:    Vergleichswert (bei 'exists' optional)
    required: Muss erfuellt sein, damit das Programm infrage kommt (Default: True)
    weight:   Gewichtung fuer den Match-Score (Default: 1)
    """

    field: str
    op: str
    value: Any = None
    required: bool = True
    weight: float = 1.0

    def validate(self) -> None:
        if self.op not in VALID_OPS:
            raise ValueError(
                f"Ungueltiger Operator {self.op!r} in Kriterium fuer Feld {self.field!r}. "
                f"Erlaubt: {sorted(VALID_OPS)}"
            )


@dataclass(frozen=True)
class FundingProgram:
    """Ein Foerderprogramm als maschinenlesbare Regeldefinition."""

    id: str
    name: str
    provider: str
    description: str = ""
    url: str = ""
    region: list[str] = field(default_factory=list)
    purposes: list[str] = field(default_factory=list)
    criteria: list[Criterion] = field(default_factory=list)
    funding: dict[str, Any] = field(default_factory=dict)
    required_documents: list[str] = field(default_factory=list)
    deadline: str | None = None
    contact: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id or not self.name:
            raise ValueError("Foerderprogramm braucht mindestens 'id' und 'name'.")
        seen = set()
        for crit in self.criteria:
            crit.validate()
            key = (crit.field, crit.op, repr(crit.value))
            if key in seen:
                raise ValueError(f"Doppeltes Kriterium in Programm {self.id!r}: {key}")
            seen.add(key)
        email = str(self.contact.get("email", ""))
        if email and "@" not in email:
            raise ValueError(f"contact.email in Programm {self.id!r} ist keine Adresse: {email!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "description": self.description,
            "url": self.url,
            "region": self.region,
            "purposes": self.purposes,
            "criteria": [
                {
                    "field": c.field,
                    "op": c.op,
                    "value": c.value,
                    "required": c.required,
                    "weight": c.weight,
                }
                for c in self.criteria
            ],
            "funding": self.funding,
            "required_documents": self.required_documents,
            "deadline": self.deadline,
            "contact": self.contact,
        }
