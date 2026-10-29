"""Open-bug batch 2026-10-29 (live-reproduced first; each fix re-checked live):

KI-311  "person-days in Dalu block for FY 2023-24 and FY 2024-25" answered one year
        -> two or more named years resolve to year_key_list (c09); live per-year rows.
KI-359 / KI-426  Focus Plus "by district" grouped on district_name_raw (30,400) while every
        other district figure reads lgd_district (30,369) -> _focusplus_lgd_district_column.
KI-364  "Compare the number of beneficiaries with Ri Bhoi" after East Khasi Hills answered
        Ri Bhoi only -> _compare_with_place_followup_question (both places).
KI-318  "go back to Mawphlang" was not read as a reference -> topic_memory._bare_place.
KI-355  "Which district had the highest administrative expenditure?" named no district
        -> the statewide admin answer names the non-zero records (live: Demdema, WGH).
KI-422  "pending at level 2" answered "pending" -> _cme_level_pending_wording.

OFFLINE: the real functions; place index / DB faked where needed.
    .venv/Scripts/python.exe -m pytest tests/test_open_bugs_batch_2026_10_29.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_policy as cp, entity_resolver, pipeline as p, topic_memory  # noqa: E402


# ── KI-359 / KI-426 ──────────────────────────────────────────────────────────
RAW = ("SELECT district_name_raw AS district, COUNT(DISTINCT beneficiary_key) AS b FROM curated.v_focus_plus "
       "WHERE financial_year_short = '2022-23' GROUP BY district_name_raw ORDER BY b DESC")


def test_focus_plus_district_figures_read_lgd_district():
    out = p._focusplus_lgd_district_column("beneficiaries in each district", ["Focus Plus"], RAW)
    assert "district_name_raw" not in out and "GROUP BY lgd_district" in out


@pytest.mark.parametrize("q,schemes", [("beneficiaries by raw district name", ["Focus Plus"]),
                                       ("by district", ["MGNREGA"])])
def test_raw_asked_or_other_schemes_keep_the_query(q, schemes):
    assert p._focusplus_lgd_district_column(q, schemes, RAW) == RAW


# ── KI-364 ───────────────────────────────────────────────────────────────────
@pytest.fixture
def ri_bhoi(monkeypatch):
    monkeypatch.setattr(entity_resolver, "place_mentions",
                        lambda q: {"RI BHOI": "district"} if "Ri Bhoi" in (q or "") else {})


PREV = SimpleNamespace(route="data", schemes=["Focus Plus"],
                       resolved_entities={"district": "EAST KHASI HILLS", "year_key": 2025})
STATE = SimpleNamespace(district="EAST KHASI HILLS", block=None, village=None, year=2025, year_all=False,
                        scheme="Focus Plus")


def test_compare_with_a_new_place_keeps_the_old_one(ri_bhoi):
    q = "Compare the number of beneficiaries with Ri Bhoi"
    out = p._compare_with_place_followup_question(q, PREV, cp.plan_state_merge(q, STATE, prev=PREV), STATE)
    assert "East Khasi Hills and Ri Bhoi" in out and "Focus Plus" in out and "2025-26" in out


def test_compare_without_a_measure_is_left_to_the_model(ri_bhoi):
    q = "Compare with Ri Bhoi"
    assert p._compare_with_place_followup_question(q, PREV, cp.plan_state_merge(q, STATE, prev=PREV), STATE) is None


# ── KI-318 ───────────────────────────────────────────────────────────────────
def test_go_back_to_a_bare_place_is_a_reference(monkeypatch):
    monkeypatch.setattr(entity_resolver, "place_mentions",
                        lambda q: {"MAWPHLANG": "block"} if "Mawphlang" in (q or "") else
                        {"EAST KHASI HILLS": "district"} if "East Khasi Hills" in (q or "") else {})
    ref = topic_memory.parse_backward("go back to Mawphlang")
    assert ref is not None and ref.target == "Mawphlang"
    assert topic_memory.parse_backward("continue with MGNREGA beneficiaries in East Khasi Hills") is None


# ── KI-422 ───────────────────────────────────────────────────────────────────
def test_level_answers_do_not_say_pending():
    q = "How many CM Elevate applications are pending at level 2?"
    out = p._cme_level_pending_wording(q, ["CM Elevate"], "There are 310 pending applications at level 2.")
    assert out.startswith("There are 310 applications at level 2.") and "current_level" in out
    same = "There are 903 pending applications."
    assert p._cme_level_pending_wording("How many are on hold?", ["CM Elevate"], same) == same
    assert p._cme_level_pending_wording(q, ["CM Elevate Legacy"], same) == same


# ── KI-311 / KI-355 (prompt line; the resolver and the admin answer need the DB — live-checked) ─
def test_named_years_ask_for_one_row_each():
    from app import prompt_builder as pb
    block = pb._entities_block({"resolved": {"year_key_list": [2023, 2024]}}, "", ["MGNREGA"])
    assert "year_key BETWEEN 2023 AND 2024" in block and "its own row" in block
