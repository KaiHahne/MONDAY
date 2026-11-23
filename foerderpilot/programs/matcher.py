from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from foerderpilot.programs.models import Criterion, FundingProgram


def _op_eq(a: Any, b: Any) -> bool:
    return a == b


def _op_ne(a: Any, b: Any) -> bool:
    return a != b


def _op_ge(a: Any, b: Any) -> bool:
    return a is not None and a >= b


def _op_le(a: Any, b: Any) -> bool:
    return a is not None and a <= b


def _op_gt(a: Any, b: Any) -> bool:
    return a is not None and a > b


def _op_lt(a: Any, b: Any) -> bool:
    return a is not None and a < b


def _op_in(a: Any, b: Any) -> bool:
    return isinstance(b, (list, tuple, set)) and a in b


def _op_not_in(a: Any, b: Any) -> bool:
    return isinstance(b, (list, tuple, set)) and a not in b


def _op_contains(a: Any, b: Any) -> bool:
    if a is None:
        return False
    if isinstance(a, str):
        return str(b).lower() in a.lower()
    if isinstance(a, (list, tuple, set)):
        return b in a
    return False


def _op_exists(a: Any, b: Any) -> bool:
    return a is not None and str(a) != ""


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "==": _op_eq,
    "!=": _op_ne,
    ">=": _op_ge,
    "<=": _op_le,
    ">": _op_gt,
    "<": _op_lt,
    "in": _op_in,
    "not_in": _op_not_in,
    "contains": _op_contains,
    "exists": _op_exists,
}


@dataclass
class CriterionResult:
    criterion: Criterion
    passed: bool
    actual: Any


@dataclass
class MatchResult:
    program: FundingProgram
    eligible: bool
    score: float
    passed: list[CriterionResult] = field(default_factory=list)
    failed: list[CriterionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program": self.program.to_dict(),
            "eligible": self.eligible,
            "score": self.score,
            "passed": [
                {"field": r.criterion.field, "op": r.criterion.op, "value": r.criterion.value, "actual": r.actual}
                for r in self.passed
            ],
            "failed": [
                {"field": r.criterion.field, "op": r.criterion.op, "value": r.criterion.value, "actual": r.actual}
                for r in self.failed
            ],
        }


def evaluate_criterion(profile: dict[str, Any], criterion: Criterion) -> CriterionResult:
    actual = profile.get(criterion.field)
    passed = OPERATORS[criterion.op](actual, criterion.value)
    return CriterionResult(criterion=criterion, passed=passed, actual=actual)


def match_program(profile: dict[str, Any], program: FundingProgram) -> MatchResult:
    """Bewertet ein einzelnes Programm gegen das Unternehmensprofil.

    eligible = alle required-Kriterien erfuellt.
    score    = Summe der Gewichte aller erfuellten Kriterien.
    """
    results = [evaluate_criterion(profile, crit) for crit in program.criteria]
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    eligible = all(r.passed for r in results if r.criterion.required)
    score = sum(r.criterion.weight for r in passed)
    return MatchResult(program=program, eligible=eligible, score=score, passed=passed, failed=failed)


def rank_matches(profile: dict[str, Any], programs: list[FundingProgram]) -> list[MatchResult]:
    """Matcht alle Programme und sortiert nach Eignung (eligible zuerst, dann Score)."""
    results = [match_program(profile, p) for p in programs]
    results.sort(key=lambda r: (r.eligible, r.score), reverse=True)
    return results
