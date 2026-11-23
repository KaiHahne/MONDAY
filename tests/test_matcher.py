import pytest

from foerderpilot.programs.loader import ProgramValidationError, load_programs
from foerderpilot.programs.matcher import evaluate_criterion, match_program, rank_matches
from foerderpilot.programs.models import Criterion, FundingProgram


def make_program(**kwargs) -> FundingProgram:
    defaults = dict(
        id="p1",
        name="Testprogramm",
        provider="Test",
        criteria=[
            Criterion(field="hq_country", op="in", value=["DE"]),
            Criterion(field="employees", op="<=", value=250),
            Criterion(field="purpose", op="contains", value="digital", required=False, weight=5),
        ],
    )
    defaults.update(kwargs)
    return FundingProgram(**defaults)


PROFILE = {
    "hq_country": "DE",
    "employees": 120,
    "purpose": "Digitalisierung der Produktion",
    "revenue_eur": 12_000_000,
}


def test_all_operators():
    assert evaluate_criterion({"a": 5}, Criterion("a", ">=", 5)).passed
    assert evaluate_criterion({"a": 5}, Criterion("a", ">", 5)).passed is False
    assert evaluate_criterion({"a": 5}, Criterion("a", "==", 5)).passed
    assert evaluate_criterion({"a": 5}, Criterion("a", "!=", 6)).passed
    assert evaluate_criterion({"a": "DE"}, Criterion("a", "in", ["DE", "AT"])).passed
    assert evaluate_criterion({"a": "CH"}, Criterion("a", "not_in", ["DE", "AT"])).passed
    assert evaluate_criterion({"a": "Digitalisierung"}, Criterion("a", "contains", "digital")).passed
    assert evaluate_criterion({"a": "x"}, Criterion("a", "exists")).passed
    assert evaluate_criterion({}, Criterion("a", "exists")).passed is False
    assert evaluate_criterion({"a": None}, Criterion("a", ">=", 1)).passed is False


def test_match_program_eligible_and_score():
    result = match_program(PROFILE, make_program())
    assert result.eligible
    assert result.score == 1 + 1 + 5
    assert len(result.passed) == 3
    assert not result.failed


def test_match_program_not_eligible_when_required_fails():
    result = match_program({**PROFILE, "employees": 999}, make_program())
    assert not result.eligible
    assert result.failed and result.failed[0].criterion.field == "employees"
    assert result.score == 1 + 5  # nur nicht-required + country


def test_rank_matches_sorts_eligible_first():
    p_eligible = make_program(id="eligible")
    p_big = make_program(
        id="big",
        criteria=[
            Criterion("employees", ">", 1000, required=True, weight=1),
            Criterion("revenue_eur", ">=", 1, required=False, weight=100),
        ],
    )
    results = rank_matches(PROFILE, [p_big, p_eligible])
    assert [r.program.id for r in results] == ["eligible", "big"]


def test_loader_rejects_invalid_op(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"id": "x", "name": "X", "criteria": [{"field": "a", "op": "~~", "value": 1}]}',
        encoding="utf-8",
    )
    with pytest.raises(ProgramValidationError):
        load_programs(bad)


def test_loader_rejects_duplicate_ids(tmp_path):
    dup = tmp_path / "dup.json"
    dup.write_text(
        '[{"id": "x", "name": "A"}, {"id": "x", "name": "B"}]',
        encoding="utf-8",
    )
    with pytest.raises(ProgramValidationError):
        load_programs(dup)


def test_loader_loads_example_programs():
    import pathlib

    repo_programs = pathlib.Path(__file__).resolve().parent.parent / "programs"
    programs = load_programs(repo_programs)
    assert len(programs) >= 3
    assert all(p.id and p.name for p in programs)
