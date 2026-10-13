"""PMAY-G sheet test run 2026-10-10 (Test Case Results - 30th Sep 26.xlsx,
PMAY-OFF-001..028): regression tests for the failures, against the real functions."""
import asyncio

import pytest

from app import pipeline as p


# ── placeholder registrations stated beside the beneficiary count (OFF-011/015) ─
def test_beneficiary_line_states_placeholders_too():
    spec = {"metrics": ["houses"], "word": "beneficiaries", "date": None, "year_key": None, "calendar_year": None}
    line = p._pmay_lines(spec, {"houses": 6122, "placeholders": 3})[0]
    assert "6,122 with a sanctioned house" in line and "6,125 registrations in all" in line
    assert p._pmay_lines(spec, {"houses": 6122, "placeholders": 0})[0] == "PMAY-G beneficiaries: 6,122"


def test_placeholder_query_skipped_for_a_year():
    spec = {"metrics": ["houses"], "year_key": 2023, "date": None, "calendar_year": None, "stages": [],
            "dim": "block", "entities": ["DEMDEMA"]}
    rows = [{"entity_key": "DEMDEMA", "houses": 10}]
    asyncio.run(p._pmay_attach_placeholders(spec, rows))
    assert "placeholders" not in rows[0]


# ── the year chip's scope is not a request for the list of years ────────────
@pytest.mark.parametrize("q,is_list", [
    ("Give me the overall PMAY performance of East Khasi Hills across all financial years", False),
    ("Give me the PMAY financial summary for Mawphlang, all financial years combined", False),
    ("give me financial years in MGNREGA", True),
    ("Which financial years does PMAY-G have?", True),
])
def test_years_list_question(q, is_list):
    assert p._is_years_list_question(q) is is_list


# ── figure summaries of a place are data, definitions stay knowledge ───────
def test_figure_summary_patterns():
    q = "What is the PMAY-G financial summary for Amlarem, the block, not another area type"
    assert p._FIGURE_SUMMARY_RE.search(q) and p._AREA_CHIP_MARKER_RE.search(q)
    assert p._DEFINITION_ASK_RE.search("What is a financial summary in PMAY-G?")
    assert p._DEFINITION_ASK_RE.search("What does the house status breakdown mean in PMAY-G?")


# ── comparison and summary questions overrule a model scope verdict ────────
@pytest.mark.parametrize("q", ["Which has more completed houses: DILBOT or UMKAIT?",
                               "Give me the PMAY financial summary for Siju."])
def test_pmay_data_questions_overrule_scope(q):
    assert p._overrules_scope_verdict(q)


def test_place_name_harm_is_cleared(monkeypatch):
    async def scan(text, scheme):
        return None
    monkeypatch.setattr(p, "_scan_village_in_question", scan)
    monkeypatch.setattr(p, "_canonical_in_question",
                        lambda q, s, d: "CHOKPOT" if d == "block" and "chokpot" in q.lower() else None)
    hit = {"type": "violence"}
    assert asyncio.run(p._harm_only_from_place_name("Give me the PMAY financial summary for Chokpot.", hit))
    assert not asyncio.run(p._harm_only_from_place_name("I want to choke someone in Chokpot", hit))


def test_hyphen_suffix_kept_in_name_run():
    assert p._unknown_word_runs("Give me the house status breakdown for chisakgre - a.") == ["chisakgre - a"]


def test_chip_questions_are_never_rephrased(monkeypatch):
    called = []

    async def fake(q):
        called.append(q)
        return q.replace(" I ", " ")
    monkeypatch.setattr(p, "rephrase_question", fake)
    monkeypatch.setattr(p, "_needs_rephrase", lambda q: True)
    t = {"question": "How many beneficiaries in SEINDULI I have received their full sanctioned amount, "
                     "MAWSHYNRUT block, WEST KHASI HILLS", "is_followup_rewrite": False, "scope_resumed": False}
    asyncio.run(p._turn_rephrase_stage(t, None))
    assert not called and "SEINDULI I " in t["question"]
