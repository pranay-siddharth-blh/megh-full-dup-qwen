"""
The conversation harness itself (tests/conversation_harness): the expectation checks,
the banner parser and every scenario file — offline, no models, no DB.
"""
from pathlib import Path

import yaml

from tests.conversation_harness.checks import (TurnRecord, answer_numbers, check_turn, parse_banner,
                                               validate_scenario)
from tests.conversation_harness.run import load_scenarios

SCENARIO_DIR = Path(__file__).resolve().parent / "conversation_harness" / "scenarios"


def test_banner_parsing():
    sc = parse_banner("MGNREGA · West Garo Hills · FY 2023-24 (from earlier)")
    assert (sc.scheme, sc.place, sc.year, sc.from_earlier) == ("MGNREGA", "West Garo Hills", "FY 2023-24", True)
    sc = parse_banner("Focus Plus · All of Meghalaya")
    assert (sc.scheme, sc.place, sc.year) == ("Focus Plus", "All of Meghalaya", None)
    sc = parse_banner("MGNREGA + PMAY-G · Ri Bhoi · FY 2022-23")
    assert sc.scheme == "MGNREGA + PMAY-G" and sc.year == "FY 2022-23"
    assert parse_banner(None).scheme is None


def test_answer_numbers_ignore_commas_and_keep_decimals():
    assert answer_numbers("8,996.36 lakh across 10 blocks in FY 2023-24") >= {8996.36, 10.0, 2023.0}


def _rec(**kw):
    base = dict(say="q", route="data", answer="", banner=None, chips=[])
    base.update(kw)
    return TurnRecord(**base)


def test_scope_checks():
    rec = _rec(answer="West Garo Hills had 80,923 job cards in FY 2023-24.", banner="MGNREGA · West Garo Hills · FY 2023-24")
    assert check_turn({"route": "data", "scheme": "MGNREGA", "place": "West Garo Hills", "year": "FY 2023-24",
                       "numbers_any": [80923]}, rec, []) == []
    assert check_turn({"place": "all"}, rec, []) == ["place 'West Garo Hills', expected 'all'"]
    assert check_turn({"year": "none"}, rec, [])[0].startswith("year 'FY 2023-24'")
    statewide = _rec(banner="PMAY-G · All of Meghalaya")
    assert check_turn({"place": "all", "year": "none"}, statewide, []) == []


def test_same_scope_as_with_exception_and_leak():
    first = _rec(answer="64,939", banner="MGNREGA · West Garo Hills · FY 2024-25")
    third = _rec(answer="80,923 in Shillong", banner="MGNREGA · West Garo Hills · FY 2023-24")
    assert check_turn({"same_scope_as": 1, "except": ["year"]}, third, [first]) == []
    fails = check_turn({"same_scope_as": 1, "answer_not_contains": ["Shillong"]}, third, [first])
    assert any("year" in f for f in fails) and any("leak" in f for f in fails)


def test_same_numbers_as_and_truth():
    first = _rec(answer="East Khasi Hills generated 3,408,697 person-days in FY 2022-23.")
    recap = _rec(route="edge", edge_type="recap", answer="Here's what I said last: 3,408,697 person-days in FY 2022-23.")
    assert check_turn({"route": "edge", "edge_type": "recap", "same_numbers_as": 1}, recap, [first]) == []
    wrong = _rec(route="edge", edge_type="recap", answer="3,408,000 person-days")
    assert check_turn({"same_numbers_as": 1}, wrong, [first])
    assert check_turn({"truth": {"sql": "SELECT 1"}}, first, [], truth_value=3408697.0) == []
    assert check_turn({"truth": {"sql": "SELECT 1", "within": 1}}, first, [], truth_value=3408698.0) == []
    assert check_turn({"truth": {"sql": "SELECT 1"}}, first, [], truth_value=None) == \
        ["truth value not available (DB not reachable or query failed)"]


def test_pause_and_chips():
    rec = _rec(route="pause", pause_rule="year-not-specified", answer="Which year?", chips=["FY 2025-26", "FY 2024-25"])
    assert check_turn({"route": "pause", "pause_rule": "year-not-specified", "chips_contain": ["FY 2024-25"], "chips_min": 2},
                      rec, []) == []
    assert check_turn({"chips_min": 3}, rec, []) == ["2 chips, expected at least 3"]
    clar = _rec(route="clarification", pause_rule="scope-not-specified")
    assert check_turn({"route": "pause"}, clar, []) == []          # the HTTP shape of a pause


def test_validate_scenario_catches_mistakes():
    assert validate_scenario({"name": "x", "turns": [{"say": "a", "expect": {"same_scope_as": 1}}]}) == \
        ["turn 1: same_scope_as must point to an earlier turn"]
    assert validate_scenario({"name": "x", "turns": [{"say": "a", "expect": {"routes": "data"}}]}) == \
        ["turn 1: unknown expect keys ['routes']"]
    assert validate_scenario({"turns": []}) == ["missing name", "turns must be a non-empty list"]


def test_every_scenario_file_is_valid_and_names_are_unique():
    scenarios = load_scenarios()
    assert scenarios, "no scenario files found"
    names = [s["name"] for s in scenarios]
    assert len(names) == len(set(names)), f"duplicate scenario names: {names}"
    for sc in scenarios:
        assert validate_scenario(sc) == [], (sc["name"], validate_scenario(sc))
        for t in sc["turns"]:
            exp = t.get("expect") or {}
            if "truth" in exp:
                sql = exp["truth"]["sql"].strip().lower()
                assert sql.startswith("select") and ";" not in sql, (sc["name"], "truth must be a single SELECT")


def test_scenario_files_parse_as_lists():
    for f in SCENARIO_DIR.glob("*.yaml"):
        docs = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert isinstance(docs, list) and docs, f.name
